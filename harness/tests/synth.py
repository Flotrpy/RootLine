"""Synthetic snapshot for tests: a payment failure that starts at T0.

Shapes follow the data contract in docs/DATA.md. Values are made up and
only exist to exercise the packers; they are never reported as results.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import polars as pl

T0 = 1_800_000_000_000
WINDOW = 10 * 60_000
START, END = T0 - WINDOW // 2, T0 + WINDOW // 2
MS = 1_000_000  # ns per ms

SERVICES = ["frontend-proxy", "frontend", "checkout", "payment", "product-catalog"]


def _spans(rng: random.Random) -> pl.DataFrame:
    rows = []
    for i, ts in enumerate(range(START, END, 2_000)):
        after = ts >= T0
        fail = after and rng.random() < 0.5
        tid = f"{rng.getrandbits(128):032x}"
        ids = [f"{rng.getrandbits(64):016x}" for _ in range(5)]
        pay = (900 if fail else 40) + rng.randint(0, 20)
        cat = 15 + rng.randint(0, 5)
        chk = pay + 30
        fe = chk + cat + 20
        root = fe + 10
        start = ts * MS
        spec = [
            (ids[0], None, "frontend-proxy", "ingress", 0, root, False),
            (ids[1], ids[0], "frontend", "POST /api/checkout", 5, fe, False),
            (
                ids[2],
                ids[1],
                "product-catalog",
                "oteldemo.ProductCatalogService/GetProduct",
                8,
                cat,
                False,
            ),
            (
                ids[3],
                ids[1],
                "checkout",
                "oteldemo.CheckoutService/PlaceOrder",
                10 + cat,
                chk,
                fail,
            ),
            (ids[4], ids[3], "payment", "oteldemo.PaymentService/Charge", 20 + cat, pay, fail),
        ]
        for sid, parent, svc, op, off, dur, err in spec:
            rows.append(
                {
                    "trace_id": tid,
                    "span_id": sid,
                    "parent_span_id": parent,
                    "service": svc,
                    "operation": op,
                    "start_unix_nano": start + off * MS,
                    "duration_ns": dur * MS,
                    "status_code": "STATUS_CODE_ERROR" if err else "STATUS_CODE_UNSET",
                    "attributes": json.dumps({"i": i, "feature_flag.key": "paymentFailure"}),
                }
            )
    return pl.DataFrame(rows)


def _metrics(rng: random.Random) -> pl.DataFrame:
    rows = []
    totals = {(s, st): 0.0 for s in SERVICES for st in ("STATUS_CODE_UNSET", "STATUS_CODE_ERROR")}
    for ts in range(START, END, 15_000):
        after = ts >= T0
        for svc in SERVICES:
            ok = 7.5 + rng.random()
            err = 0.0
            if svc in ("payment", "checkout") and after:
                err, ok = ok * 0.5, ok * 0.5
            totals[(svc, "STATUS_CODE_UNSET")] += ok
            totals[(svc, "STATUS_CODE_ERROR")] += err
            for st in ("STATUS_CODE_UNSET", "STATUS_CODE_ERROR"):
                rows.append(
                    {
                        "ts": ts,
                        "service": svc,
                        "metric_name": "traces.span.metrics.calls",
                        "value": totals[(svc, st)],
                        "labels": json.dumps({"status.code": st, "span.kind": "SPAN_KIND_SERVER"}),
                    }
                )
            p99 = 900.0 if svc == "payment" and after else 50.0 + rng.random() * 5
            rows.append(
                {
                    "ts": ts,
                    "service": svc,
                    "metric_name": "traces.span.metrics.duration.p99",
                    "value": p99,
                    "labels": "{}",
                }
            )
            rows.append(
                {
                    "ts": ts,
                    "service": svc,
                    "metric_name": "process.memory.usage",
                    "value": 100e6 + rng.random() * 1e6,
                    "labels": "{}",
                }
            )
    return pl.DataFrame(rows)


def _logs(rng: random.Random) -> pl.DataFrame:
    rows = []
    for ts in range(START, END, 1_000):
        after = ts >= T0
        svc = SERVICES[(ts // 1_000) % len(SERVICES)]
        rows.append(
            {
                "ts": ts,
                "service": svc,
                "severity": "INFO",
                "body": f"handled request in {rng.randint(5, 50)} ms",
                "trace_id": None,
            }
        )
        if after and rng.random() < 0.5:
            rows.append(
                {
                    "ts": ts + 1,
                    "service": "payment",
                    "severity": "ERROR",
                    "body": f"Payment request failed. Invalid token. app.loyalty.level=gold "
                    f"txn={rng.randint(10_000, 99_999)}",
                    "trace_id": None,
                }
            )
        if after and ts % 30_000 == 0:
            rows.append(
                {
                    "ts": ts + 2,
                    "service": "flagd",
                    "severity": "INFO",
                    "body": "flag paymentFailure evaluated to variant 50%",
                    "trace_id": None,
                }
            )
    return pl.DataFrame(rows, schema_overrides={"trace_id": pl.String})


def write_snapshot(directory: Path, incident_id: str = "paymentFailure-r1", seed: int = 7) -> Path:
    rng = random.Random(seed)
    directory.mkdir(parents=True, exist_ok=True)
    _spans(rng).write_parquet(directory / "spans.parquet", compression="zstd")
    _metrics(rng).write_parquet(directory / "metrics.parquet", compression="zstd")
    _logs(rng).write_parquet(directory / "logs.parquet", compression="zstd")
    manifest = {
        "incident_id": incident_id,
        "demo_git_tag": "synthetic",
        "image_digests": {},
        "t0_unix_ms": T0,
        "window_ms": WINDOW,
        "collector_version": "synthetic",
        "snapshotter_git_sha": "synthetic",
        "host_ram_gb": 16,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return directory


LABEL = {
    "fault": "paymentFailure",
    "service": "payment",
    "category": "error",
    "layer": "application",
    "edge": None,
    "flag": "paymentFailure",
    "variant": "50%",
}
