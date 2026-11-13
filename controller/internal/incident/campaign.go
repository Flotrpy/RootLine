package incident

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"math/rand/v2"
	"os"

	"gopkg.in/yaml.v3"

	"github.com/flotrpy/rootline/controller/internal/catalog"
)

// Plan is a campaign file such as plans/pilot.yaml.
type Plan struct {
	Name     string   `yaml:"name"`
	Replicas int      `yaml:"replicas"`
	Faults   []string `yaml:"faults"` // empty means every catalog fault
	Seed     *uint64  `yaml:"seed"`   // set to shuffle the run order reproducibly
}

// Item is one planned incident.
type Item struct {
	Fault   catalog.Fault
	Replica int
}

// ID returns the incident ID.
func (i Item) ID() string { return catalog.IncidentID(i.Fault.Name, i.Replica) }

// LoadPlan reads and validates a plan file.
func LoadPlan(path string) (Plan, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return Plan{}, err
	}
	var p Plan
	dec := yaml.NewDecoder(bytes.NewReader(raw))
	dec.KnownFields(true)
	if err := dec.Decode(&p); err != nil {
		return Plan{}, fmt.Errorf("parse plan %s: %w", path, err)
	}
	if p.Replicas < 1 {
		return Plan{}, fmt.Errorf("plan %s: replicas must be >= 1", path)
	}
	return p, nil
}

// Expand lists the plan's incidents: replica 1 of every fault, then replica
// 2, and so on, optionally shuffled with the plan's seed.
func (p Plan) Expand() ([]Item, error) {
	var faults []catalog.Fault
	if len(p.Faults) == 0 {
		faults = catalog.All()
	} else {
		for _, n := range p.Faults {
			f, ok := catalog.Lookup(n)
			if !ok {
				return nil, fmt.Errorf("plan: unknown fault %q", n)
			}
			faults = append(faults, f)
		}
	}
	var items []Item
	for r := 1; r <= p.Replicas; r++ {
		for _, f := range faults {
			items = append(items, Item{Fault: f, Replica: r})
		}
	}
	if p.Seed != nil {
		rng := rand.New(rand.NewPCG(*p.Seed, 0))
		rng.Shuffle(len(items), func(i, j int) { items[i], items[j] = items[j], items[i] })
	}
	return items, nil
}

// Progress is the campaign's resumable state file.
type Progress struct {
	Plan    string            `json:"plan"`
	Done    map[string]Result `json:"done"`
	Failed  map[string]string `json:"failed"`
	Pending []string          `json:"pending"`
}

// LoadProgress reads a progress file, or returns an empty one if missing.
func LoadProgress(path string) (*Progress, error) {
	p := &Progress{Done: map[string]Result{}, Failed: map[string]string{}}
	raw, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return p, nil
	}
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal(raw, p); err != nil {
		return nil, fmt.Errorf("parse progress %s: %w", path, err)
	}
	if p.Done == nil {
		p.Done = map[string]Result{}
	}
	if p.Failed == nil {
		p.Failed = map[string]string{}
	}
	return p, nil
}

// Save writes the progress file atomically.
func (p *Progress) Save(path string) error {
	b, err := json.MarshalIndent(p, "", "  ")
	if err != nil {
		return err
	}
	return WriteFileAtomic(path, b)
}

// Campaign runs every incident in a plan that is not already done, saving
// progress after each one so Ctrl-C and a rerun pick up where it stopped.
// A failed incident is recorded and retried on the next run; the campaign
// keeps going.
func (r *Runner) Campaign(ctx context.Context, plan Plan, progressPath string) (*Progress, error) {
	items, err := plan.Expand()
	if err != nil {
		return nil, err
	}
	prog, err := LoadProgress(progressPath)
	if err != nil {
		return nil, err
	}
	prog.Plan = plan.Name
	prog.Pending = prog.Pending[:0]
	for _, it := range items {
		if _, done := prog.Done[it.ID()]; !done {
			prog.Pending = append(prog.Pending, it.ID())
		}
	}
	if err := prog.Save(progressPath); err != nil {
		return nil, err
	}

	warm := true
	for _, it := range items {
		id := it.ID()
		if _, done := prog.Done[id]; done {
			continue
		}
		res, err := r.Run(ctx, it.Fault, it.Replica, warm)
		warm = false
		if ctx.Err() != nil {
			return prog, ctx.Err()
		}
		if err != nil {
			r.log().Error("incident failed", "incident", id, "err", err)
			prog.Failed[id] = err.Error()
		} else {
			prog.Done[id] = res
			delete(prog.Failed, id)
		}
		prog.Pending = removeID(prog.Pending, id)
		if err := prog.Save(progressPath); err != nil {
			return prog, err
		}
	}
	return prog, nil
}

func removeID(ids []string, id string) []string {
	out := ids[:0]
	for _, x := range ids {
		if x != id {
			out = append(out, x)
		}
	}
	return out
}
