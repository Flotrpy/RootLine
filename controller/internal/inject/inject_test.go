package inject

import (
	"context"
	"testing"

	"github.com/flotrpy/rootline/controller/internal/catalog"
)

func flagNames() []string {
	var n []string
	for _, f := range catalog.All() {
		if f.Flag != "" {
			n = append(n, f.Flag)
		}
	}
	return n
}

func TestInjectAndClearEveryFault(t *testing.T) {
	ctx := context.Background()
	for _, f := range catalog.All() {
		t.Run(f.Name, func(t *testing.T) {
			in, ff, ft, fn := NewFake(flagNames()...)
			if err := in.Inject(ctx, f); err != nil {
				t.Fatal(err)
			}
			switch f.Kind {
			case catalog.KindFlag:
				if ff.State[f.Flag] != f.Variant {
					t.Fatalf("flag %s = %q", f.Flag, ff.State[f.Flag])
				}
			case catalog.KindToxic:
				p := DefaultEdges[f.Edge].Proxy
				if len(ft.Toxics[p]) != 1 || ft.Toxics[p][0].Type != f.Toxic.Type {
					t.Fatalf("toxics on %s: %+v", p, ft.Toxics[p])
				}
			case catalog.KindNetem:
				c := DefaultEdges[f.Edge].Container
				if fn.Rules[c] != f.LossPct {
					t.Fatalf("loss on %s = %d", c, fn.Rules[c])
				}
			}
			if err := in.Clear(ctx, f); err != nil {
				t.Fatal(err)
			}
			for name, v := range ff.State {
				if v != "off" {
					t.Errorf("flag %s still %q", name, v)
				}
			}
			for p, ts := range ft.Toxics {
				if len(ts) != 0 {
					t.Errorf("toxics left on %s", p)
				}
			}
			if len(fn.Rules) != 0 {
				t.Errorf("netem left: %v", fn.Rules)
			}
		})
	}
}

func TestClearAllResetsEverything(t *testing.T) {
	ctx := context.Background()
	in, ff, ft, fn := NewFake(flagNames()...)
	for _, name := range []string{"paymentFailure", "toxiLatency", "netemLoss", "toxiBandwidth"} {
		f, _ := catalog.Lookup(name)
		if err := in.Inject(ctx, f); err != nil {
			t.Fatal(err)
		}
	}
	if err := in.ClearAll(ctx); err != nil {
		t.Fatal(err)
	}
	if ff.State["paymentFailure"] != "off" || len(fn.Rules) != 0 {
		t.Fatal("flags or netem not reset")
	}
	for p, ts := range ft.Toxics {
		if len(ts) != 0 {
			t.Errorf("toxics left on %s", p)
		}
	}
}

func TestUnknownEdge(t *testing.T) {
	in, _, _, _ := NewFake()
	in.Edges = map[string]Edge{}
	f, _ := catalog.Lookup("toxiLatency")
	if err := in.Inject(context.Background(), f); err == nil {
		t.Fatal("want error for unwired edge")
	}
}

func TestManualFaultsGoThroughTheOperator(t *testing.T) {
	ctx := context.Background()
	in, _, ft, fn := NewFake(flagNames()...)
	f, _ := catalog.Lookup("hwPowerCut")
	if err := in.Inject(ctx, f); err == nil {
		t.Fatal("manual fault without an operator must fail")
	}
	op := &FakeOperator{}
	in.Operator = op
	if err := in.Inject(ctx, f); err != nil {
		t.Fatal(err)
	}
	if err := in.Clear(ctx, f); err != nil {
		t.Fatal(err)
	}
	if len(op.Steps) != 2 || op.Steps[0] != "hwPowerCut/inject" || op.Steps[1] != "hwPowerCut/clear" {
		t.Fatalf("steps = %v", op.Steps)
	}
	if len(ft.Toxics) != 0 || len(fn.Rules) != 0 {
		t.Fatal("manual faults must not touch Toxiproxy or netem")
	}
}
