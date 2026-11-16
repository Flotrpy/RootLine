"""Metrics packer: per-service RED and resource metrics in 30 s buckets,
shown as deltas from the pre-fault baseline.

Counters (names ending in _total, .count or calls) become per-second rates;
gauges (including the .p50/.p95/.p99 quantiles the snapshotter derives from
histograms) are taken as the bucket maximum. For span-metric call counters
the packer also derives request_rate and error_ratio per service.
"""

from __future__ import annotations

import math

import polars as pl

from rootline_harness.packers.evidence import Section, make_lines
from rootline_harness.packers.snapshot import Snapshot

BUCKET_MS = 30_000
CALLS_METRICS = frozenset({"calls", "traces.span.metrics.calls", "traces_span_metrics_calls_total"})
MAX_SCORE = 1000.0  # caps "appeared from zero" so ranking stays finite


def _bucket_series(snap: Snapshot) -> pl.DataFrame:
    """Return (service, metric, bucket, value) with one value per bucket."""
    m = snap.metrics.filter((pl.col("ts") >= snap.start_ms) & (pl.col("ts") < snap.end_ms))
    if m.is_empty():
        return pl.DataFrame(
            schema={
                "service": pl.String,
                "metric": pl.String,
                "bucket": pl.Int64,
                "value": pl.Float64,
            }
        )
    m = m.with_columns(
        bucket=((pl.col("ts") - snap.t0_ms) // BUCKET_MS).cast(pl.Int64),
        is_counter=pl.col("metric_name").str.contains(r"(_total|\.count)$")
        | pl.col("metric_name").is_in(list(CALLS_METRICS)),
        is_error=pl.col("labels").str.contains(r"(?i)status[._]code\"?\s*:\s*\"[A-Z_]*ERROR"),
    ).sort(["service", "metric_name", "labels", "ts"])

    key = ["service", "metric_name", "labels"]
    counters = (
        m.filter(pl.col("is_counter"))
        .with_columns(
            # Cumulative counters: per-series increments; a drop is a reset.
            inc=pl.col("value").diff().over(key).fill_null(0.0).clip(lower_bound=0.0)
        )
        .group_by(["service", "metric_name", "is_error", "bucket"])
        .agg((pl.col("inc").sum() / (BUCKET_MS / 1000)).alias("value"))
    )
    rates = counters.group_by(["service", "metric_name", "bucket"]).agg(pl.col("value").sum())
    rates = rates.with_columns(
        metric=pl.when(pl.col("metric_name").is_in(list(CALLS_METRICS)))
        .then(pl.lit("request_rate"))
        .otherwise(pl.col("metric_name") + pl.lit(".rate"))
    ).select("service", "metric", "bucket", "value")

    calls = counters.filter(pl.col("metric_name").is_in(list(CALLS_METRICS)))
    errors = (
        calls.group_by(["service", "bucket"])
        .agg(
            total=pl.col("value").sum(),
            err=pl.col("value").filter(pl.col("is_error")).sum(),
        )
        .with_columns(
            value=pl.when(pl.col("total") > 0).then(pl.col("err") / pl.col("total")).otherwise(0.0),
            metric=pl.lit("error_ratio"),
        )
        .select("service", "metric", "bucket", "value")
    )

    gauges = (
        m.filter(~pl.col("is_counter"))
        .group_by(["service", "metric_name", "bucket"])
        .agg(pl.col("value").max())
        .rename({"metric_name": "metric"})
        .select("service", "metric", "bucket", "value")
    )
    return pl.concat([rates, errors, gauges]).sort(["service", "metric", "bucket"])


def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    if abs(v) >= 1000 or abs(v) < 0.01:
        return f"{v:.3g}"
    return f"{v:.3g}" if abs(v) < 10 else f"{v:.1f}"


def _delta(v: float | None, base: float) -> tuple[str, float]:
    if v is None:
        return "na", 0.0
    if base == 0:
        if v == 0:
            return "+0%", 0.0
        return f"new:{_fmt(v)}", MAX_SCORE
    pct = (v - base) / abs(base) * 100
    return f"{pct:+.0f}%", min(abs(pct) / 100, MAX_SCORE)


def pack_metrics(snap: Snapshot) -> Section:
    series = _bucket_series(snap)
    n_buckets = math.ceil((snap.end_ms - snap.t0_ms) / BUCKET_MS)
    ranked: list[tuple[float, str, str, tuple[tuple[str, ...], str]]] = []
    for (service, metric), grp in series.group_by(["service", "metric"], maintain_order=True):
        values = dict(zip(grp["bucket"].to_list(), grp["value"].to_list(), strict=True))
        base_vals = [v for b, v in values.items() if b < 0]
        if not base_vals:
            continue
        base = sum(base_vals) / len(base_vals)
        cells, score = [], 0.0
        for b in range(n_buckets):
            text, s = _delta(values.get(b), base)
            cells.append(text)
            score = max(score, s)
        line = f"svc={service} metric={metric} base={_fmt(base)} delta/30s=[{','.join(cells)}]"
        ranked.append((score, str(service), str(metric), ((str(service),), line)))
    ranked.sort(key=lambda r: (-r[0], r[1], r[2]))
    return Section(
        signal="metrics",
        header="per-service metrics, 30 s buckets from fault onset, % change vs pre-onset mean",
        lines=make_lines("metrics", [r[3] for r in ranked]),
    )
