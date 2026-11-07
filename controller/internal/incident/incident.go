// Package incident runs the Rootline incident protocol: baseline, inject,
// snapshot, clear, cool down, check recovery.
package incident

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/flotrpy/rootline/controller/internal/catalog"
	"github.com/flotrpy/rootline/controller/internal/health"
	"github.com/flotrpy/rootline/controller/internal/inject"
)

// Protocol holds the timings from the charter. Change them only with
// flotrpy's sign-off: they are part of the experiment design.
type Protocol struct {
	VUs          int           // load generator users (set in compose.override.yml)
	Warmup       time.Duration // first run of a campaign only
	Baseline     time.Duration
	Fault        time.Duration
	WindowBefore time.Duration // snapshot window starts this long before T0
	WindowAfter  time.Duration // and ends this long after
	Cooldown     time.Duration
	RecoveryMax  time.Duration
	RecoveryPoll time.Duration
}

// Pilot is the v0.1 protocol.
var Pilot = Protocol{
	VUs:          20,
	Warmup:       10 * time.Minute,
	Baseline:     5 * time.Minute,
	Fault:        5 * time.Minute,
	WindowBefore: 5 * time.Minute,
	WindowAfter:  5 * time.Minute,
	Cooldown:     3 * time.Minute,
	RecoveryMax:  10 * time.Minute,
	RecoveryPoll: 15 * time.Second,
}

// Clock lets tests run the protocol without waiting.
type Clock interface {
	Now() time.Time
	Sleep(ctx context.Context, d time.Duration) error
}

// RealClock uses wall time.
type RealClock struct{}

// Now implements Clock.
func (RealClock) Now() time.Time { return time.Now() }

// Sleep implements Clock and returns early if ctx is cancelled.
func (RealClock) Sleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

// SnapshotRequest asks the snapshotter to freeze a window.
type SnapshotRequest struct {
	IncidentID string            `json:"incident_id"`
	T0UnixMs   int64             `json:"t0_unix_ms"`
	StartMs    int64             `json:"start_unix_ms"`
	WindowMs   int64             `json:"window_ms"`
	Extra      map[string]string `json:"extra,omitempty"`
}

// Snapshotter freezes telemetry windows.
type Snapshotter interface {
	Snapshot(ctx context.Context, req SnapshotRequest) error
}

// HTTPSnapshotter posts to the snapshotter's /snapshot endpoint, which
// answers once the Parquet files and manifest are on disk.
type HTTPSnapshotter struct {
	Base string
	HTTP *http.Client
}

// Snapshot implements Snapshotter.
func (h *HTTPSnapshotter) Snapshot(ctx context.Context, req SnapshotRequest) error {
	b, err := json.Marshal(req)
	if err != nil {
		return err
	}
	r, err := http.NewRequestWithContext(ctx, http.MethodPost, h.Base+"/snapshot", bytes.NewReader(b))
	if err != nil {
		return err
	}
	r.Header.Set("Content-Type", "application/json")
	c := h.HTTP
	if c == nil {
		c = &http.Client{Timeout: 2 * time.Minute}
	}
	resp, err := c.Do(r)
	if err != nil {
		return fmt.Errorf("snapshotter: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("snapshotter: %s: %s", resp.Status, bytes.TrimSpace(msg))
	}
	return nil
}

// Result is what one incident run produced.
type Result struct {
	IncidentID      string        `json:"incident_id"`
	T0UnixMs        int64         `json:"t0_unix_ms"`
	Baseline        health.Sample `json:"baseline"`
	Final           health.Sample `json:"final"`
	Recovered       bool          `json:"recovered"`
	RecoverySeconds float64       `json:"recovery_seconds"`
	FinishedUnixMs  int64         `json:"finished_unix_ms"`
}

// Runner executes incidents.
type Runner struct {
	Injector    *inject.Injector
	Probe       health.Probe
	Snapshotter Snapshotter
	Clock       Clock
	Protocol    Protocol
	LabelsDir   string
	Log         *slog.Logger
}

func (r *Runner) log() *slog.Logger {
	if r.Log == nil {
		return slog.New(slog.NewTextHandler(io.Discard, nil))
	}
	return r.Log
}

// Run executes the full protocol for one incident. warmup adds the
// first-run warm-up. The fault is always cleared before Run returns, even on
// error or cancellation.
func (r *Runner) Run(ctx context.Context, f catalog.Fault, replica int, warmup bool) (res Result, err error) {
	id := catalog.IncidentID(f.Name, replica)
	res.IncidentID = id
	p := r.Protocol
	lg := r.log().With("incident", id)

	if err := r.Injector.ClearAll(ctx); err != nil {
		return res, fmt.Errorf("pre-run reset: %w", err)
	}
	if warmup {
		lg.Info("warm-up", "for", p.Warmup)
		if err := r.Clock.Sleep(ctx, p.Warmup); err != nil {
			return res, err
		}
	}
	lg.Info("baseline", "for", p.Baseline)
	if err := r.Clock.Sleep(ctx, p.Baseline); err != nil {
		return res, err
	}
	if res.Baseline, err = r.Probe.Sample(ctx); err != nil {
		return res, fmt.Errorf("baseline sample: %w", err)
	}

	t0 := r.Clock.Now()
	res.T0UnixMs = t0.UnixMilli()
	if err := WriteLabel(r.LabelsDir, f.LabelFor(id)); err != nil {
		return res, err
	}
	lg.Info("inject", "fault", f.Name)
	if err := r.Injector.Inject(ctx, f); err != nil {
		return res, fmt.Errorf("inject: %w", err)
	}
	defer func() {
		// Clear with a fresh context so a cancelled run still cleans up.
		cctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if cerr := r.Injector.Clear(cctx, f); cerr != nil && err == nil {
			err = fmt.Errorf("clear: %w", cerr)
		}
	}()
	if err := r.Clock.Sleep(ctx, p.Fault); err != nil {
		return res, err
	}

	start := t0.Add(-p.WindowBefore)
	req := SnapshotRequest{
		IncidentID: id,
		T0UnixMs:   res.T0UnixMs,
		StartMs:    start.UnixMilli(),
		WindowMs:   (p.WindowBefore + p.WindowAfter).Milliseconds(),
	}
	lg.Info("snapshot", "window_ms", req.WindowMs)
	if err := r.Snapshotter.Snapshot(ctx, req); err != nil {
		return res, err
	}

	if err := r.Injector.Clear(ctx, f); err != nil {
		return res, fmt.Errorf("clear: %w", err)
	}
	lg.Info("cool-down", "for", p.Cooldown)
	if err := r.Clock.Sleep(ctx, p.Cooldown); err != nil {
		return res, err
	}

	cleared := r.Clock.Now()
	deadline := cleared.Add(p.RecoveryMax)
	for {
		s, err := r.Probe.Sample(ctx)
		if err != nil {
			return res, fmt.Errorf("recovery sample: %w", err)
		}
		res.Final = s
		if health.Recovered(res.Baseline, s) {
			res.Recovered = true
			break
		}
		if !r.Clock.Now().Before(deadline) {
			break
		}
		if err := r.Clock.Sleep(ctx, p.RecoveryPoll); err != nil {
			return res, err
		}
	}
	res.RecoverySeconds = r.Clock.Now().Sub(cleared).Seconds()
	res.FinishedUnixMs = r.Clock.Now().UnixMilli()
	lg.Info("done", "recovered", res.Recovered, "recovery_s", res.RecoverySeconds)
	return res, nil
}

// WriteLabel stores a ground-truth label atomically under dir. Labels live
// apart from snapshots so packers never see them.
func WriteLabel(dir string, l catalog.Label) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	b, err := catalog.MarshalLabel(l)
	if err != nil {
		return err
	}
	return WriteFileAtomic(filepath.Join(dir, l.IncidentID+".json"), b)
}

// WriteFileAtomic writes to a temp file in the same directory, then renames.
func WriteFileAtomic(path string, data []byte) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), "."+filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}
