// Package remediate executes a model's chosen fix from the fixed action menu
// and checks whether the shop recovers. Free-form commands are never run.
package remediate

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"time"

	"github.com/flotrpy/rootline/controller/internal/catalog"
	"github.com/flotrpy/rootline/controller/internal/health"
	"github.com/flotrpy/rootline/controller/internal/incident"
	"github.com/flotrpy/rootline/controller/internal/inject"
	"github.com/flotrpy/rootline/controller/internal/netem"
)

// Action types, matching the model output contract.
const (
	Restart           = "restart"
	DisableFeature    = "disable_feature"
	ClearNetworkFault = "clear_network_fault"
	NoAction          = "no_action"
)

// Action is one menu item with its target.
type Action struct {
	Type   string `json:"type"`
	Target string `json:"target"`
}

// Wait is how long a trial waits after acting before checking recovery.
const Wait = 120 * time.Second

var serviceRe = regexp.MustCompile(`^[a-z][a-z0-9-]{0,62}$`)

// Validate rejects anything outside the menu, and targets that are not plain
// service or edge names, before anything touches the system.
func (a Action) Validate(edges map[string]inject.Edge) error {
	switch a.Type {
	case NoAction:
		return nil
	case Restart, DisableFeature:
		if !serviceRe.MatchString(a.Target) {
			return fmt.Errorf("invalid service target %q", a.Target)
		}
		return nil
	case ClearNetworkFault:
		if _, ok := edges[a.Target]; !ok {
			return fmt.Errorf("unknown edge %q", a.Target)
		}
		return nil
	}
	return fmt.Errorf("action %q is not on the menu", a.Type)
}

// Harmful reports whether an action counts as harmful for an incident: any
// action on a healthy run, or an action aimed at the wrong place. no_action
// is never harmful.
func Harmful(a Action, l catalog.Label) bool {
	if a.Type == NoAction {
		return false
	}
	if l.Layer == catalog.LayerNone {
		return true
	}
	if a.Type == ClearNetworkFault {
		return l.Layer != catalog.LayerNetwork || l.Edge == nil || *l.Edge != a.Target
	}
	return a.Target != l.Service
}

// Executor applies actions to the live system.
type Executor struct {
	Injector *inject.Injector
	Runner   netem.Runner // runs `docker restart`
}

// Apply performs one action.
func (e *Executor) Apply(ctx context.Context, a Action) error {
	if err := a.Validate(e.Injector.Edges); err != nil {
		return err
	}
	switch a.Type {
	case NoAction:
		return nil
	case Restart:
		_, err := e.Runner.Run(ctx, "docker", "restart", a.Target)
		return err
	case DisableFeature:
		// The model names the service; the controller turns off whichever
		// flags target it, so the model only needs service and action class.
		var errs []error
		for _, f := range catalog.ByFlagService(a.Target) {
			errs = append(errs, e.Injector.Clear(ctx, f))
		}
		return errors.Join(errs...)
	case ClearNetworkFault:
		return e.Injector.ClearEdge(ctx, a.Target)
	}
	return fmt.Errorf("unreachable action %q", a.Type)
}

// TrialResult is the outcome of one live remediation trial.
type TrialResult struct {
	IncidentID string        `json:"incident_id"`
	Action     Action        `json:"action"`
	Baseline   health.Sample `json:"baseline"`
	BeforeFix  health.Sample `json:"before_fix"`
	AfterFix   health.Sample `json:"after_fix"`
	Recovered  bool          `json:"recovered"`
	Harmful    bool          `json:"harmful"`
}

// Trial re-creates an incident, applies the action while the fault is live,
// waits 120 s, and checks recovery against the pre-fault baseline. It always
// resets everything before returning.
type Trial struct {
	Executor *Executor
	Probe    health.Probe
	Clock    incident.Clock
	Protocol incident.Protocol
}

// Run executes the trial for incidentID.
func (t *Trial) Run(ctx context.Context, incidentID string, a Action) (res TrialResult, err error) {
	name, _, err := catalog.ParseIncidentID(incidentID)
	if err != nil {
		return res, err
	}
	f, ok := catalog.Lookup(name)
	if !ok {
		return res, fmt.Errorf("unknown fault %q", name)
	}
	if err := a.Validate(t.Executor.Injector.Edges); err != nil {
		return res, err
	}
	res = TrialResult{IncidentID: incidentID, Action: a, Harmful: Harmful(a, f.LabelFor(incidentID))}
	in := t.Executor.Injector

	if err := in.ClearAll(ctx); err != nil {
		return res, err
	}
	defer func() {
		cctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if cerr := in.ClearAll(cctx); cerr != nil && err == nil {
			err = fmt.Errorf("reset: %w", cerr)
		}
	}()

	if err := t.Clock.Sleep(ctx, t.Protocol.Baseline); err != nil {
		return res, err
	}
	if res.Baseline, err = t.Probe.Sample(ctx); err != nil {
		return res, err
	}
	if err := in.Inject(ctx, f); err != nil {
		return res, err
	}
	if err := t.Clock.Sleep(ctx, t.Protocol.Fault); err != nil {
		return res, err
	}
	if res.BeforeFix, err = t.Probe.Sample(ctx); err != nil {
		return res, err
	}
	if err := t.Executor.Apply(ctx, a); err != nil {
		return res, fmt.Errorf("apply %s(%s): %w", a.Type, a.Target, err)
	}
	if err := t.Clock.Sleep(ctx, Wait); err != nil {
		return res, err
	}
	if res.AfterFix, err = t.Probe.Sample(ctx); err != nil {
		return res, err
	}
	res.Recovered = health.Recovered(res.Baseline, res.AfterFix)
	return res, nil
}
