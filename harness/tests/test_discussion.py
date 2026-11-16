import json

import polars as pl

from analysis import discussion
from rootline_harness.scorers import Label

HEALTHY = Label(fault="healthy", service="none", category="none", layer="none")
APP = Label(fault="paymentFailure", service="payment", category="error", layer="application")


def answer(layer: str, service: str | None) -> str:
    hyps = [] if service is None else [
        {"rank": 1, "service": service, "category": "error", "confidence": 0.8, "evidence": []}
    ]  # fmt: skip
    return json.dumps({"abstain": False, "layer": layer, "hypotheses": hyps,
                       "action": {"type": "no_action", "target": None}})  # fmt: skip


def runs(rows: list[tuple[str, str, str, bool, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"model_id": m, "incident_id": i, "condition": c, "perturbation": "p0",
             "top1": t, "layer_ok": t, "parsed_ok": True, "confidence": 0.8, "raw_output": raw}
            for m, i, c, t, raw in rows
        ]
    )  # fmt: skip


def test_false_alarm_targets_counts_claims_and_blame() -> None:
    df = runs([
        ("m", "healthy-r1", "combined", False, answer("application", "flagd")),
        ("m", "healthy-r1", "logs", False, answer("application", "flagd")),
        ("m", "healthy-r2", "combined", True, answer("none", None)),
    ])  # fmt: skip
    out = discussion.false_alarm_targets(df, {"healthy-r1": HEALTHY, "healthy-r2": HEALTHY})
    row = out.row(0, named=True)
    assert (row["answers"], row["fault_claims"], row["most_blamed"]) == (3, 2, "flagd")


def test_by_layer_keeps_hardware_apart() -> None:
    hw = Label(fault="hwWifiOutage", service="payment", category="network_reset",
               layer="network", edge="checkout->payment")  # fmt: skip
    df = runs([
        ("m", "paymentFailure-r1", "combined", True, "{}"),
        ("m", "hwWifiOutage-r1", "combined", False, "{}"),
    ])  # fmt: skip
    out = discussion.by_layer(df, {"paymentFailure-r1": APP, "hwWifiOutage-r1": hw})
    assert set(out["group"]) == {"application", "hardware (network)"}
