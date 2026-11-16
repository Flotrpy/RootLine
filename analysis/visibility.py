"""Does each injected fault show in its own snapshot?

A manipulation check, computed from the frozen telemetry only (no model):
for every snapshot, the spans that should carry the fault, in the five
minutes before fault onset against the five minutes after.

- Faults on an edge (network faults, the hardware arm, paymentUnreachable)
  are measured on the caller's client spans to the callee, which is where
  lost, slow or reset calls show.
- Other faults are measured on the root-cause service's own spans.
- The healthy control is measured on checkout -> payment, as a reference.

    uv run --project harness python -m analysis fault-visibility

A fault that barely moves these numbers is reported as such: models are
then scored on a fault that left little trace in the evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

# The RPC name a caller's client span carries for each callee.
RPC = {
    "payment": "PaymentService/",
    "product-catalog": "ProductCatalogService/",
    "shipping": "ShippingService/",
    "cart": "CartService/",
    "currency": "CurrencyService/",
    "recommendation": "RecommendationService/",
    "ad": "AdService/",
}
HEALTHY_EDGE = "checkout->payment"
COLUMNS = ["service", "operation", "start_unix_nano", "duration_ns", "status_code"]


def _target(label: dict[str, object]) -> tuple[str, str | None, str]:
    """(service whose spans are measured, RPC filter or None, what it is)."""
    edge = label.get("edge") or (HEALTHY_EDGE if label.get("service") == "none" else None)
    if isinstance(edge, str) and "->" in edge:
        caller, callee = (s.strip() for s in edge.split("->"))
        return caller, RPC.get(callee), f"{caller} calls to {callee}"
    svc = str(label["service"])
    return svc, None, f"{svc} spans"


def _half(spans: pl.DataFrame) -> dict[str, float]:
    n = spans.height
    if n == 0:
        return {"n": 0, "errors": 0, "p50_ms": float("nan"), "p95_ms": float("nan")}
    ms = spans["duration_ns"] / 1e6
    return {
        "n": n,
        "errors": spans.filter(pl.col("status_code").str.contains("ERROR")).height,
        "p50_ms": float(ms.median()),  # type: ignore[arg-type]
        "p95_ms": float(ms.quantile(0.95)),  # type: ignore[arg-type]
    }


def snapshot_visibility(snap: Path, label: dict[str, object]) -> dict[str, object]:
    t0 = json.loads((snap / "manifest.json").read_text())["t0_unix_ms"] * 1_000_000
    service, rpc, what = _target(label)
    spans = pl.read_parquet(snap / "spans.parquet", columns=COLUMNS).filter(
        pl.col("service") == service
    )
    if rpc is not None:
        client = spans.filter(pl.col("operation").str.contains(rpc, literal=True))
        if client.height:
            spans = client
    before = _half(spans.filter(pl.col("start_unix_nano") < t0))
    after = _half(spans.filter(pl.col("start_unix_nano") >= t0))
    row: dict[str, object] = {
        "incident_id": snap.name,
        "fault": label["fault"],
        "layer": label["layer"],
        "measured": what,
    }
    for k, v in before.items():
        row[f"before_{k}"] = v
    for k, v in after.items():
        row[f"after_{k}"] = v
    row["error_rate_before"] = before["errors"] / before["n"] if before["n"] else float("nan")
    row["error_rate_after"] = after["errors"] / after["n"] if after["n"] else float("nan")
    row["p95_ratio"] = (
        after["p95_ms"] / before["p95_ms"] if before["p95_ms"] and before["n"] else float("nan")
    )
    row["calls_ratio"] = after["n"] / before["n"] if before["n"] else float("nan")
    return row


def visibility(data: Path) -> pl.DataFrame:
    rows = []
    snaps = data / "snapshots"
    for snap in sorted(p for p in snaps.iterdir() if p.is_dir()) if snaps.exists() else []:
        lp = data / "labels" / f"{snap.name}.json"
        if (snap / "manifest.json").exists() and lp.exists():
            rows.append(snapshot_visibility(snap, json.loads(lp.read_text())))
    return pl.DataFrame(rows)


def write(data: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "fault_visibility.csv"
    visibility(data).write_csv(path)
    return path
