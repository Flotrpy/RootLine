package incident

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/flotrpy/rootline/controller/internal/catalog"
	"github.com/flotrpy/rootline/controller/internal/health"
	"github.com/flotrpy/rootline/controller/internal/inject"
)

// fakeClock advances instantly on Sleep.
type fakeClock struct {
	mu  sync.Mutex
	now time.Time
}

func (c *fakeClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

func (c *fakeClock) Sleep(ctx context.Context, d time.Duration) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	c.mu.Lock()
	c.now = c.now.Add(d)
	c.mu.Unlock()
	return nil
}

// scriptedProbe returns samples in order, repeating the last one.
type scriptedProbe struct {
	samples []health.Sample
	i       int
}

func (p *scriptedProbe) Sample(context.Context) (health.Sample, error) {
	s := p.samples[min(p.i, len(p.samples)-1)]
	p.i++
	return s, nil
}

type recordingSnap struct {
	reqs []SnapshotRequest
	err  error
	// seen captures injector state at snapshot time.
	onSnap func()
}

func (s *recordingSnap) Snapshot(_ context.Context, r SnapshotRequest) error {
	s.reqs = append(s.reqs, r)
	if s.onSnap != nil {
		s.onSnap()
	}
	return s.err
}

var t0 = time.Date(2026, 11, 7, 23, 0, 0, 0, time.UTC)

func flagNames() []string {
	var n []string
	for _, f := range catalog.All() {
		if f.Flag != "" {
			n = append(n, f.Flag)
		}
	}
	return n
}

func newRunner(t *testing.T, probe health.Probe) (*Runner, *inject.FakeFlags, *recordingSnap, *fakeClock) {
	t.Helper()
	in, ff, _, _ := inject.NewFake(flagNames()...)
	snap := &recordingSnap{}
	clk := &fakeClock{now: t0}
	return &Runner{
		Injector:    in,
		Probe:       probe,
		Snapshotter: snap,
		Clock:       clk,
		Protocol:    Pilot,
		LabelsDir:   t.TempDir(),
	}, ff, snap, clk
}

func TestRunProtocol(t *testing.T) {
	base := health.Sample{ErrorRatio: 0.01, P99Ms: 300}
	bad := health.Sample{ErrorRatio: 0.3, P99Ms: 300}
	probe := &scriptedProbe{samples: []health.Sample{base, bad, bad, base}}
	r, ff, snap, _ := newRunner(t, probe)
	f, _ := catalog.Lookup("paymentFailure")

	var flagAtSnap string
	snap.onSnap = func() { flagAtSnap = ff.State["paymentFailure"] }

	res, err := r.Run(context.Background(), f, 1, true)
	if err != nil {
		t.Fatal(err)
	}

	wantT0 := t0.Add(Pilot.Warmup + Pilot.Baseline)
	if res.T0UnixMs != wantT0.UnixMilli() {
		t.Errorf("T0 = %d, want %d", res.T0UnixMs, wantT0.UnixMilli())
	}
	if len(snap.reqs) != 1 {
		t.Fatalf("want 1 snapshot, got %d", len(snap.reqs))
	}
	req := snap.reqs[0]
	if req.StartMs != wantT0.Add(-5*time.Minute).UnixMilli() || req.WindowMs != (10*time.Minute).Milliseconds() {
		t.Errorf("window = %+v", req)
	}
	if flagAtSnap != "50%" {
		t.Errorf("fault must be active during snapshot, flag was %q", flagAtSnap)
	}
	if ff.State["paymentFailure"] != "off" {
		t.Errorf("fault not cleared")
	}
	if !res.Recovered || res.RecoverySeconds != 2*Pilot.RecoveryPoll.Seconds() {
		t.Errorf("recovery = %v after %.0fs", res.Recovered, res.RecoverySeconds)
	}
	if res.Baseline != base {
		t.Errorf("baseline = %+v", res.Baseline)
	}

	raw, err := os.ReadFile(filepath.Join(r.LabelsDir, "paymentFailure-r1.json"))
	if err != nil {
		t.Fatal(err)
	}
	var label map[string]any
	if err := json.Unmarshal(raw, &label); err != nil {
		t.Fatal(err)
	}
	if label["service"] != "payment" || label["layer"] != "application" {
		t.Errorf("label = %v", label)
	}
}

func TestRunGivesUpAfterRecoveryMax(t *testing.T) {
	base := health.Sample{ErrorRatio: 0.01, P99Ms: 300}
	bad := health.Sample{ErrorRatio: 0.3, P99Ms: 300}
	r, _, _, _ := newRunner(t, &scriptedProbe{samples: []health.Sample{base, bad}})
	f, _ := catalog.Lookup("emailMemoryLeak")
	res, err := r.Run(context.Background(), f, 2, false)
	if err != nil {
		t.Fatal(err)
	}
	if res.Recovered {
		t.Fatal("should not recover")
	}
	if res.RecoverySeconds != Pilot.RecoveryMax.Seconds() {
		t.Fatalf("gave up after %.0fs, want %.0fs", res.RecoverySeconds, Pilot.RecoveryMax.Seconds())
	}
}

func TestRunClearsFaultWhenSnapshotFails(t *testing.T) {
	base := health.Sample{ErrorRatio: 0.01, P99Ms: 300}
	r, ff, snap, _ := newRunner(t, &scriptedProbe{samples: []health.Sample{base}})
	snap.err = errors.New("disk full")
	f, _ := catalog.Lookup("adHighCpu")
	if _, err := r.Run(context.Background(), f, 1, false); err == nil {
		t.Fatal("want error")
	}
	if ff.State["adHighCpu"] != "off" {
		t.Fatal("fault left active after a failed run")
	}
}

func TestCampaignResumes(t *testing.T) {
	base := health.Sample{ErrorRatio: 0.01, P99Ms: 300}
	r, _, snap, _ := newRunner(t, &scriptedProbe{samples: []health.Sample{base}})
	progress := filepath.Join(t.TempDir(), "progress.json")
	plan := Plan{Name: "test", Replicas: 2, Faults: []string{"healthy", "toxiLatency"}}

	// Interrupt after the second snapshot.
	ctx, cancel := context.WithCancel(context.Background())
	snap.onSnap = func() {
		if len(snap.reqs) == 2 {
			cancel()
		}
	}
	prog, err := r.Campaign(ctx, plan, progress)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("want cancellation, got %v", err)
	}
	if len(prog.Done) != 1 {
		t.Fatalf("done after interrupt = %d, want 1", len(prog.Done))
	}

	snap.onSnap = nil
	prog, err = r.Campaign(context.Background(), plan, progress)
	if err != nil {
		t.Fatal(err)
	}
	if len(prog.Done) != 4 || len(prog.Pending) != 0 || len(prog.Failed) != 0 {
		t.Fatalf("final progress: done=%d pending=%v failed=%v", len(prog.Done), prog.Pending, prog.Failed)
	}
	// 2 snapshots in the first run (the second interrupted) + 3 remaining.
	if len(snap.reqs) != 5 {
		t.Fatalf("snapshots = %d, want 5", len(snap.reqs))
	}
	if snap.reqs[2].IncidentID != "toxiLatency-r1" {
		t.Fatalf("resume restarted at %s", snap.reqs[2].IncidentID)
	}
}

func TestPlanExpand(t *testing.T) {
	items, err := Plan{Replicas: 2}.Expand()
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 30 {
		t.Fatalf("pilot plan = %d incidents, want 30", len(items))
	}
	if items[0].ID() != "paymentFailure-r1" || items[15].ID() != "paymentFailure-r2" {
		t.Fatalf("order: %s, %s", items[0].ID(), items[15].ID())
	}
	seed := uint64(7)
	a, _ := Plan{Replicas: 2, Seed: &seed}.Expand()
	b, _ := Plan{Replicas: 2, Seed: &seed}.Expand()
	for i := range a {
		if a[i].ID() != b[i].ID() {
			t.Fatal("seeded shuffle is not reproducible")
		}
	}
	if _, err := (Plan{Replicas: 1, Faults: []string{"nope"}}).Expand(); err == nil {
		t.Fatal("want error for unknown fault")
	}
}

func TestLoadPlanFile(t *testing.T) {
	p, err := LoadPlan("../../../plans/pilot.yaml")
	if err != nil {
		t.Fatal(err)
	}
	items, err := p.Expand()
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 30 {
		t.Fatalf("plans/pilot.yaml expands to %d incidents, want 30", len(items))
	}
}
