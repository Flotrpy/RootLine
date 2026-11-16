"""Per-service features for the classical baselines (RQ6).

Each service in a snapshot gets one row comparing the fault window
(t >= T0) with the baseline (t < T0) across all three signals. The same
features feed both the Isolation Forest and LightGBM baselines.
"""

from __future__ import annotations

import math

import polars as pl

from rootline_harness.packers.metrics import _bucket_series
from rootline_harness.packers.snapshot import Snapshot

FEATURES = (
    "error_ratio_delta",
    "request_rate_log_ratio",
    "p99_log_ratio",
    "memory_log_ratio",
    "cpu_log_ratio",
    "span_error_frac_delta",
    "span_duration_log_ratio",
    "log_error_rate_log_ratio",
    "log_rate_log_ratio",
)
EPS = 1e-6
ERROR_LOG = r"(?i)error|fail|exception|panic|timeout|refused"


def _log_ratio(after: float, before: float) -> float:
    return math.log((after + EPS) / (before + EPS)) if after > 0 or before > 0 else 0.0


def _split_means(df: pl.DataFrame, group: str, value: str, is_after: pl.Expr) -> dict[str, tuple]:
    agg = (
        df.with_columns(after=is_after)
        .group_by(group, "after")
        .agg(pl.col(value).mean().alias("v"))
        .iter_rows(named=True)
    )
    out: dict[str, list[float]] = {}
    for r in agg:
        pair = out.setdefault(r[group], [0.0, 0.0])
        pair[1 if r["after"] else 0] = float(r["v"] or 0.0)
    return {k: (v[0], v[1]) for k, v in out.items()}


def service_features(snap: Snapshot) -> pl.DataFrame:
    """One row per service: incident_id, service, then FEATURES."""
    rows: dict[str, dict[str, float]] = {}

    def row(svc: str) -> dict[str, float]:
        return rows.setdefault(svc, dict.fromkeys(FEATURES, 0.0))

    # Metrics, through the same bucketing as the metrics packer.
    series = _bucket_series(snap)
    if not series.is_empty():
        after = pl.col("bucket") >= 0
        picks = {
            "error_ratio": pl.col("metric") == "error_ratio",
            "request_rate": pl.col("metric") == "request_rate",
            "p99": pl.col("metric").str.ends_with(".p99"),
            "memory": pl.col("metric").str.contains("memory"),
            "cpu": pl.col("metric").str.contains("cpu"),
        }
        for name, cond in picks.items():
            for svc, (b, a) in _split_means(series.filter(cond), "service", "value", after).items():
                if name == "error_ratio":
                    row(svc)["error_ratio_delta"] = a - b
                else:
                    row(svc)[f"{name}_log_ratio"] = _log_ratio(a, b)

    # Traces: span error fraction and mean duration per service.
    spans = snap.spans.filter(
        pl.col("start_unix_nano").is_between(snap.start_ms * 1_000_000, snap.end_ms * 1_000_000)
    ).with_columns(err=pl.col("status_code").str.contains("ERROR").cast(pl.Float64))
    span_after = pl.col("start_unix_nano") >= snap.t0_ms * 1_000_000
    for svc, (b, a) in _split_means(spans, "service", "err", span_after).items():
        row(svc)["span_error_frac_delta"] = a - b
    for svc, (b, a) in _split_means(spans, "service", "duration_ns", span_after).items():
        row(svc)["span_duration_log_ratio"] = _log_ratio(a, b)

    # Logs: overall and error-looking log rates per minute.
    logs = snap.logs.filter(pl.col("ts").is_between(snap.start_ms, snap.end_ms - 1))
    base_min = (snap.t0_ms - snap.start_ms) / 60_000
    fault_min = (snap.end_ms - snap.t0_ms) / 60_000
    flagged = logs.with_columns(
        after=pl.col("ts") >= snap.t0_ms,
        is_err=pl.col("severity").str.contains("(?i)err|warn|fatal")
        | pl.col("body").str.contains(ERROR_LOG),
    )
    counts = flagged.group_by("service", "after").agg(n=pl.len(), n_err=pl.col("is_err").sum())
    per: dict[str, dict[str, float]] = {}
    for r in counts.iter_rows(named=True):
        d = per.setdefault(r["service"], {"b": 0.0, "a": 0.0, "be": 0.0, "ae": 0.0})
        span = fault_min if r["after"] else base_min
        d["a" if r["after"] else "b"] = r["n"] / span
        d["ae" if r["after"] else "be"] = r["n_err"] / span
    for svc, d in per.items():
        row(svc)["log_rate_log_ratio"] = _log_ratio(d["a"], d["b"])
        row(svc)["log_error_rate_log_ratio"] = _log_ratio(d["ae"], d["be"])

    return pl.DataFrame(
        [{"incident_id": snap.incident_id, "service": s, **f} for s, f in sorted(rows.items())],
        schema={
            "incident_id": pl.String,
            "service": pl.String,
            **dict.fromkeys(FEATURES, pl.Float64),
        },
    )


def anomaly_score(df: pl.DataFrame) -> pl.Series:
    """Sum of absolute feature values: a crude 'how changed is this service'."""
    return df.select(pl.sum_horizontal([pl.col(f).abs() for f in FEATURES])).to_series()
