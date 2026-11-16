// Package buffer keeps the last few minutes of rows in memory so a window
// can be frozen after the fact.
package buffer

import (
	"sync"
	"time"

	"github.com/flotrpy/rootline/snapshotter/internal/rows"
)

// Buffer holds rows for Retention, keyed by their own timestamps.
type Buffer struct {
	Retention time.Duration
	Now       func() time.Time

	mu      sync.Mutex
	spans   []rows.Span
	metrics []rows.Metric
	logs    []rows.Log
}

// New returns a Buffer that keeps rows for retention.
func New(retention time.Duration) *Buffer {
	return &Buffer{Retention: retention, Now: time.Now}
}

func (b *Buffer) cutoffMs() int64 { return b.Now().Add(-b.Retention).UnixMilli() }

// prune drops expired rows from the front of the slice. It runs on every add
// and only copies when something expires. Rows that arrive out of order can
// leave expired rows further back; Sweep removes those.
func prune[T any](xs []T, keep func(T) bool) []T {
	i := 0
	for i < len(xs) && !keep(xs[i]) {
		i++
	}
	if i == 0 {
		return xs
	}
	return append(xs[:0:0], xs[i:]...)
}

func filter[T any](xs []T, keep func(T) bool) []T {
	out := xs[:0:0]
	for _, x := range xs {
		if keep(x) {
			out = append(out, x)
		}
	}
	return out
}

// AddSpans stores spans.
func (b *Buffer) AddSpans(s []rows.Span) {
	b.mu.Lock()
	defer b.mu.Unlock()
	cut := b.cutoffMs() * 1_000_000
	b.spans = prune(append(b.spans, s...), func(x rows.Span) bool { return x.StartUnixNano >= cut })
}

// AddMetrics stores metric rows.
func (b *Buffer) AddMetrics(m []rows.Metric) {
	b.mu.Lock()
	defer b.mu.Unlock()
	cut := b.cutoffMs()
	b.metrics = prune(append(b.metrics, m...), func(x rows.Metric) bool { return x.Ts >= cut })
}

// AddLogs stores log rows.
func (b *Buffer) AddLogs(l []rows.Log) {
	b.mu.Lock()
	defer b.mu.Unlock()
	cut := b.cutoffMs()
	b.logs = prune(append(b.logs, l...), func(x rows.Log) bool { return x.Ts >= cut })
}

// Sweep removes every expired row, wherever it sits. Call it periodically.
func (b *Buffer) Sweep() {
	b.mu.Lock()
	defer b.mu.Unlock()
	cut := b.cutoffMs()
	b.spans = filter(b.spans, func(x rows.Span) bool { return x.StartUnixNano >= cut*1_000_000 })
	b.metrics = filter(b.metrics, func(x rows.Metric) bool { return x.Ts >= cut })
	b.logs = filter(b.logs, func(x rows.Log) bool { return x.Ts >= cut })
}

// Window returns sorted copies of all rows with timestamps in
// [startMs, endMs).
func (b *Buffer) Window(startMs, endMs int64) ([]rows.Span, []rows.Metric, []rows.Log) {
	b.mu.Lock()
	s := filter(b.spans, func(x rows.Span) bool {
		t := x.StartUnixNano / 1_000_000
		return t >= startMs && t < endMs
	})
	m := filter(b.metrics, func(x rows.Metric) bool { return x.Ts >= startMs && x.Ts < endMs })
	l := filter(b.logs, func(x rows.Log) bool { return x.Ts >= startMs && x.Ts < endMs })
	b.mu.Unlock()
	rows.SortSpans(s)
	rows.SortMetrics(m)
	rows.SortLogs(l)
	return s, m, l
}

// Counts reports how many rows are buffered.
func (b *Buffer) Counts() (spans, metrics, logs int) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.spans), len(b.metrics), len(b.logs)
}
