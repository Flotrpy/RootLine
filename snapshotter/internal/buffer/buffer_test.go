package buffer

import (
	"testing"
	"time"

	"github.com/flotrpy/rootline/snapshotter/internal/rows"
)

func TestWindowAndRetention(t *testing.T) {
	now := time.UnixMilli(1_000_000)
	b := New(10 * time.Second)
	b.Now = func() time.Time { return now }

	b.AddLogs([]rows.Log{{Ts: 995_000, Body: "c"}, {Ts: 991_000, Body: "a"}, {Ts: 989_000, Body: "expired"}})
	b.AddMetrics([]rows.Metric{{Ts: 999_000}, {Ts: 1_000_500}})
	b.AddSpans([]rows.Span{{StartUnixNano: 992_000 * 1_000_000, SpanID: "s"}})

	_, m, l := b.Window(990_000, 1_000_000)
	if len(l) != 2 || l[0].Body != "a" || l[1].Body != "c" {
		t.Fatalf("logs window = %+v (want sorted a, c without the expired row)", l)
	}
	if len(m) != 1 {
		t.Fatalf("metrics window = %+v (end is exclusive)", m)
	}

	now = now.Add(5 * time.Second)
	b.Sweep()
	sp, mc, lc := b.Counts()
	if sp != 0 || lc != 1 || mc != 2 {
		t.Fatalf("after sweep spans=%d metrics=%d logs=%d", sp, mc, lc)
	}
}
