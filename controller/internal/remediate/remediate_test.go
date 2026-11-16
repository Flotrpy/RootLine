package remediate

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/flotrpy/rootline/controller/internal/catalog"
	"github.com/flotrpy/rootline/controller/internal/health"
	"github.com/flotrpy/rootline/controller/internal/incident"
	"github.com/flotrpy/rootline/controller/internal/inject"
)

func label(t *testing.T, fault string) catalog.Label {
	t.Helper()
	f, ok := catalog.Lookup(fault)
	if !ok {
		t.Fatalf("no fault %s", fault)
	}
	return f.LabelFor(fault + "-r1")
}

func TestHarmful(t *testing.T) {
	tests := []struct {
		name   string
		action Action
		fault  string
		want   bool
	}{
		{"no action on healthy", Action{NoAction, ""}, "healthy", false},
		{"restart on healthy", Action{Restart, "payment"}, "healthy", true},
		{"right service", Action{DisableFeature, "payment"}, "paymentFailure", false},
		{"wrong service", Action{Restart, "checkout"}, "paymentFailure", true},
		{"right edge", Action{ClearNetworkFault, catalog.EdgeCheckoutPayment}, "toxiReset", false},
		{"wrong edge", Action{ClearNetworkFault, catalog.EdgeFrontendCatalog}, "toxiReset", true},
		{"network fix on app fault on same edge", Action{ClearNetworkFault, catalog.EdgeCheckoutPayment}, "paymentUnreachable", true},
		{"no action on real fault", Action{NoAction, ""}, "toxiLatency", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := Harmful(tt.action, label(t, tt.fault)); got != tt.want {
				t.Fatalf("Harmful = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestValidate(t *testing.T) {
	tests := []struct {
		a       Action
		wantErr bool
	}{
		{Action{NoAction, ""}, false},
		{Action{Restart, "product-catalog"}, false},
		{Action{Restart, "payment; rm -rf /"}, true},
		{Action{Restart, "--privileged"}, true},
		{Action{ClearNetworkFault, "checkout->payment"}, false},
		{Action{ClearNetworkFault, "ad->cart"}, true},
		{Action{"exec", "sh"}, true},
	}
	for _, tt := range tests {
		if err := tt.a.Validate(inject.DefaultEdges); (err != nil) != tt.wantErr {
			t.Errorf("%+v: err = %v, wantErr %v", tt.a, err, tt.wantErr)
		}
	}
}

type fakeRunner struct{ calls []string }

func (f *fakeRunner) Run(_ context.Context, name string, args ...string) ([]byte, error) {
	f.calls = append(f.calls, name+" "+strings.Join(args, " "))
	return nil, nil
}

type fakeClock struct{ now time.Time }

func (c *fakeClock) Now() time.Time { return c.now }
func (c *fakeClock) Sleep(_ context.Context, d time.Duration) error {
	c.now = c.now.Add(d)
	return nil
}

// stateProbe reports "bad" while the payment flag is on.
type stateProbe struct{ flags *inject.FakeFlags }

func (p *stateProbe) Sample(context.Context) (health.Sample, error) {
	if p.flags.State["paymentFailure"] != "off" {
		return health.Sample{ErrorRatio: 0.4, P99Ms: 300}, nil
	}
	return health.Sample{ErrorRatio: 0.01, P99Ms: 300}, nil
}

func flagNames() []string {
	var n []string
	for _, f := range catalog.All() {
		if f.Flag != "" {
			n = append(n, f.Flag)
		}
	}
	return n
}

func TestTrial(t *testing.T) {
	tests := []struct {
		name          string
		action        Action
		wantRecovered bool
		wantHarmful   bool
		wantDocker    int
	}{
		{"correct fix", Action{DisableFeature, "payment"}, true, false, 0},
		{"wrong fix", Action{Restart, "checkout"}, false, true, 1},
		{"do nothing", Action{NoAction, ""}, false, false, 0},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			in, ff, _, _ := inject.NewFake(flagNames()...)
			runner := &fakeRunner{}
			tr := &Trial{
				Executor: &Executor{Injector: in, Runner: runner},
				Probe:    &stateProbe{flags: ff},
				Clock:    &fakeClock{},
				Protocol: incident.Pilot,
			}
			res, err := tr.Run(context.Background(), "paymentFailure-r1", tt.action)
			if err != nil {
				t.Fatal(err)
			}
			if res.Recovered != tt.wantRecovered || res.Harmful != tt.wantHarmful {
				t.Fatalf("recovered=%v harmful=%v", res.Recovered, res.Harmful)
			}
			if res.BeforeFix.ErrorRatio < 0.3 {
				t.Fatal("fault was not live before the fix")
			}
			if len(runner.calls) != tt.wantDocker {
				t.Fatalf("docker calls = %v", runner.calls)
			}
			if ff.State["paymentFailure"] != "off" {
				t.Fatal("trial left the fault active")
			}
		})
	}
}

func TestTrialRejectsOffMenuAction(t *testing.T) {
	in, _, _, _ := inject.NewFake(flagNames()...)
	runner := &fakeRunner{}
	tr := &Trial{Executor: &Executor{Injector: in, Runner: runner}, Clock: &fakeClock{}, Protocol: incident.Pilot}
	if _, err := tr.Run(context.Background(), "paymentFailure-r1", Action{"exec", "sh -c id"}); err == nil {
		t.Fatal("want rejection")
	}
	if len(runner.calls) != 0 {
		t.Fatal("nothing should run")
	}
}
