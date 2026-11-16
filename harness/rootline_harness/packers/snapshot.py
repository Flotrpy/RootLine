"""Load a frozen snapshot: spans, metrics, logs and manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

SPANS_SCHEMA: dict[str, Any] = {
    "trace_id": pl.String,
    "span_id": pl.String,
    "parent_span_id": pl.String,
    "service": pl.String,
    "operation": pl.String,
    "start_unix_nano": pl.Int64,
    "duration_ns": pl.Int64,
    "status_code": pl.String,
    "attributes": pl.String,
}
METRICS_SCHEMA: dict[str, Any] = {
    "ts": pl.Int64,
    "service": pl.String,
    "metric_name": pl.String,
    "value": pl.Float64,
    "labels": pl.String,
}
LOGS_SCHEMA: dict[str, Any] = {
    "ts": pl.Int64,
    "service": pl.String,
    "severity": pl.String,
    "body": pl.String,
    "trace_id": pl.String,
}


@dataclass(frozen=True)
class Snapshot:
    """One incident's telemetry window. Times are unix milliseconds."""

    incident_id: str
    t0_ms: int
    start_ms: int
    end_ms: int
    spans: pl.DataFrame
    metrics: pl.DataFrame
    logs: pl.DataFrame
    manifest: dict[str, Any] = field(default_factory=dict)


def _read(path: Path, schema: dict[str, Any]) -> pl.DataFrame:
    if not path.exists():
        return pl.DataFrame(schema=schema)
    df = pl.read_parquet(path)
    missing = set(schema) - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns {sorted(missing)}")
    return df.select([pl.col(c).cast(t) for c, t in schema.items()])


def load_snapshot(directory: str | Path) -> Snapshot:
    """Load a snapshot directory written by the snapshotter.

    The window is [t0 - window_ms/2, t0 + window_ms/2], matching the
    controller's [T0-5m, T0+5m]. Labels are never read here.
    """
    d = Path(directory)
    manifest = json.loads((d / "manifest.json").read_text())
    t0 = int(manifest["t0_unix_ms"])
    half = int(manifest["window_ms"]) // 2
    return Snapshot(
        incident_id=str(manifest["incident_id"]),
        t0_ms=t0,
        start_ms=t0 - half,
        end_ms=t0 + half,
        spans=_read(d / "spans.parquet", SPANS_SCHEMA),
        metrics=_read(d / "metrics.parquet", METRICS_SCHEMA),
        logs=_read(d / "logs.parquet", LOGS_SCHEMA),
        manifest=manifest,
    )
