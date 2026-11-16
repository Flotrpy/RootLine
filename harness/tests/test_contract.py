"""The Python harness must read what the Go snapshotter writes."""

from pathlib import Path

from rootline_harness.packers import CONDITIONS, build_pack, load_snapshot

FIXTURE = Path(__file__).parents[2] / "snapshotter" / "testdata" / "fixture-snapshot"


def test_loads_go_snapshot() -> None:
    snap = load_snapshot(FIXTURE)
    assert snap.incident_id == "paymentFailure-r1"
    assert snap.end_ms - snap.start_ms == 600_000
    assert snap.spans.height == 2
    assert snap.spans["parent_span_id"].null_count() == 1
    assert snap.logs.height == 2
    names = set(snap.metrics["metric_name"].to_list())
    assert {"traces.span.metrics.duration.p99", "traces.span.metrics.calls"} <= names


def test_packs_go_snapshot() -> None:
    snap = load_snapshot(FIXTURE)
    for condition in CONDITIONS:
        pack = build_pack(snap, condition, 2000)
        assert pack.render()
    metrics = build_pack(snap, "metrics", 2000).render()
    assert "svc=payment metric=error_ratio" in metrics
    traces = build_pack(snap, "traces", 2000).render()
    assert "checkout:oteldemo.CheckoutService/PlaceOrder 900ms! > payment:" in traces
