// Package inject turns a catalog fault into calls on flagd, Toxiproxy or
// netem, and clears them again.
package inject

import (
	"context"
	"errors"
	"fmt"
	"sort"

	"github.com/flotrpy/rootline/controller/internal/catalog"
	"github.com/flotrpy/rootline/controller/internal/flagd"
	"github.com/flotrpy/rootline/controller/internal/netem"
	"github.com/flotrpy/rootline/controller/internal/toxi"
)

// Edge says how one service-to-service edge is wired in compose.override.yml.
type Edge struct {
	Proxy     string // Toxiproxy proxy name
	Container string // netem sidecar sharing the edge proxy's network namespace
}

// DefaultEdges matches compose.override.yml. Each edge gets its own
// Toxiproxy container, and a netem sidecar that shares that container's
// network namespace (the Toxiproxy image has no tc binary), so a netem rule
// on one edge never touches the other.
var DefaultEdges = map[string]Edge{
	catalog.EdgeCheckoutPayment: {Proxy: "payment", Container: "netem-payment"},
	catalog.EdgeFrontendCatalog: {Proxy: "product-catalog", Container: "netem-catalog"},
}

// ToxicName is the name every Rootline toxic gets inside Toxiproxy.
func ToxicName(fault string) string { return "rootline-" + fault }

// Injector applies and clears faults.
type Injector struct {
	Flags    flagd.Flags
	Toxi     toxi.Proxies
	Netem    netem.Shaper
	Edges    map[string]Edge
	Operator Operator // manual (hardware) faults only
}

// Operator carries out the physical steps of a manual fault.
type Operator interface {
	Do(ctx context.Context, fault, phase, instruction string) error
}

func (in *Injector) operate(ctx context.Context, f catalog.Fault, phase, instruction string) error {
	if in.Operator == nil {
		return fmt.Errorf("fault %s needs an operator", f.Name)
	}
	return in.Operator.Do(ctx, f.Name, phase, instruction)
}

func (in *Injector) edge(name string) (Edge, error) {
	e, ok := in.Edges[name]
	if !ok {
		return Edge{}, fmt.Errorf("no wiring for edge %q", name)
	}
	return e, nil
}

// Inject applies a fault.
func (in *Injector) Inject(ctx context.Context, f catalog.Fault) error {
	switch f.Kind {
	case catalog.KindFlag:
		return in.Flags.Set(f.Flag, f.Variant)
	case catalog.KindToxic:
		e, err := in.edge(f.Edge)
		if err != nil {
			return err
		}
		return in.Toxi.AddToxic(ctx, e.Proxy, toxi.Toxic{
			Name:       ToxicName(f.Name),
			Type:       f.Toxic.Type,
			Toxicity:   f.Toxic.Toxicity,
			Attributes: f.Toxic.Attributes,
		})
	case catalog.KindNetem:
		e, err := in.edge(f.Edge)
		if err != nil {
			return err
		}
		return in.Netem.Loss(ctx, e.Container, f.LossPct)
	case catalog.KindManual:
		return in.operate(ctx, f, "inject", f.Steps)
	case catalog.KindNone:
		return nil
	}
	return fmt.Errorf("unknown fault kind %q", f.Kind)
}

// Clear removes a fault.
func (in *Injector) Clear(ctx context.Context, f catalog.Fault) error {
	switch f.Kind {
	case catalog.KindFlag:
		return in.Flags.Set(f.Flag, flagd.OffVariant)
	case catalog.KindToxic, catalog.KindNetem:
		return in.ClearEdge(ctx, f.Edge)
	case catalog.KindManual:
		return in.operate(ctx, f, "clear", f.Undo)
	case catalog.KindNone:
		return nil
	}
	return fmt.Errorf("unknown fault kind %q", f.Kind)
}

// ClearEdge removes every toxic and netem rule on an edge.
func (in *Injector) ClearEdge(ctx context.Context, edge string) error {
	e, err := in.edge(edge)
	if err != nil {
		return err
	}
	return errors.Join(
		toxi.ClearAll(ctx, in.Toxi, e.Proxy),
		in.Netem.Clear(ctx, e.Container),
	)
}

// ClearAll resets every flag and every edge. It tries everything and
// returns all errors together, so one broken piece does not leave the rest
// faulty.
func (in *Injector) ClearAll(ctx context.Context) error {
	errs := []error{in.Flags.ResetAll()}
	names := make([]string, 0, len(in.Edges))
	for n := range in.Edges {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		errs = append(errs, in.ClearEdge(ctx, n))
	}
	return errors.Join(errs...)
}
