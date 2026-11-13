import json

import polars as pl
import pytest

from cascade.sweep import THETAS, decisions, rq4, select, single_tiers, sweep
from rootline_harness.runner import RUN_COLUMNS


def raw(conf: float | None, layer: str = "application", abstain: bool = False) -> str:
    hyps = (
        []
        if conf is None
        else [{"rank": 1, "service": "x", "category": "error", "confidence": conf, "evidence": []}]
    )
    action = (
        {"type": "no_action", "target": None}
        if layer == "none"
        else {"type": "restart", "target": "x"}
    )
    return json.dumps({"abstain": abstain, "layer": layer, "hypotheses": hyps, "action": action})


def rec(incident, tier, *, top1, conf, tokens, layer="application", parsed=True, abstain=False):
    r: dict[str, object] = {c: None for c in RUN_COLUMNS}
    r.update(
        run_id=f"{incident}-{tier}",
        incident_id=incident,
        condition="combined",
        perturbation="p0",
        model_id=f"model-{tier}",
        tier=tier,
        provider="p",
        prompt_tokens=tokens,
        completion_tokens=0,
        latency_ms=1,
        raw_output=raw(conf if layer != "none" else None, layer, abstain) if parsed else "junk",
        parsed_ok=parsed,
        top1=top1,
        top3=top1,
        layer_ok=top1,
        confidence=conf if conf is not None else 0.0,
    )
    return r


def frame(records) -> pl.DataFrame:
    return pl.DataFrame(records, infer_schema_length=None)


RUNS = frame(
    [
        # i1: A confident and right -> stops at A for theta <= 0.8
        rec("i1", "A", top1=True, conf=0.8, tokens=100),
        rec("i1", "B", top1=True, conf=0.9, tokens=300),
        rec("i1", "C", top1=True, conf=0.9, tokens=1000),
        # i2: A unsure and wrong, B sure and right
        rec("i2", "A", top1=False, conf=0.4, tokens=100),
        rec("i2", "B", top1=True, conf=0.7, tokens=300),
        rec("i2", "C", top1=True, conf=0.9, tokens=1000),
        # i3: healthy; A says no fault -> always accepted
        rec("i3", "A", top1=True, conf=None, tokens=100, layer="none"),
        rec("i3", "B", top1=True, conf=None, tokens=300, layer="none"),
        rec("i3", "C", top1=True, conf=None, tokens=1000, layer="none"),
        # i4: A and B invalid -> C
        rec("i4", "A", top1=False, conf=None, tokens=100, parsed=False),
        rec("i4", "B", top1=False, conf=0.95, tokens=300, abstain=True),
        rec("i4", "C", top1=False, conf=0.6, tokens=1000),
        # i5: only two tiers ran -> excluded
        rec("i5", "A", top1=True, conf=0.9, tokens=100),
        rec("i5", "B", top1=True, conf=0.9, tokens=300),
    ]
)


def test_select_keeps_complete_incidents() -> None:
    answers = select(RUNS)
    assert sorted(answers) == ["i1", "i2", "i3", "i4"]


def test_sweep_at_two_thetas() -> None:
    table = sweep(select(RUNS), thetas=(0.3, 0.75))
    low, high = table.row(0, named=True), table.row(1, named=True)
    # theta 0.3: i1 A, i2 A (wrong), i3 A, i4 C (wrong) -> 2/4
    assert low["accuracy"] == pytest.approx(0.5)
    assert low["total_tokens"] == 100 + 100 + 100 + (100 + 300 + 1000)
    # theta 0.75: i1 A, i2 B (0.7 < 0.75) -> C, i3 A, i4 C -> 3/4 right
    assert high["accuracy"] == pytest.approx(0.75)
    assert high["escalation_rate_b"] == pytest.approx(0.5)
    assert high["escalation_rate_c"] == pytest.approx(0.5)


def test_default_thetas() -> None:
    assert THETAS[0] == 0.3 and THETAS[-1] == 0.9 and len(THETAS) == 13


def test_rq4_flags() -> None:
    answers = select(RUNS)
    table = rq4(sweep(answers), single_tiers(answers))
    tiers = single_tiers(answers)
    assert tiers.filter(pl.col("tier") == "C")["accuracy"][0] == pytest.approx(0.75)
    row = table.filter(pl.col("theta") == 0.3).row(0, named=True)
    assert row["tokens_used"] == pytest.approx(1700 / 4000)
    assert row["accuracy_kept"] == pytest.approx(0.5 / 0.75)
    assert row["hypothesis_holds"] is False


def test_ambiguous_tier_needs_explicit_models() -> None:
    extra = frame([rec("i1", "A", top1=True, conf=0.9, tokens=1) | {"model_id": "other-A"}])
    with pytest.raises(ValueError, match="tier A has several models"):
        select(pl.concat([RUNS, extra]))
    picked = select(pl.concat([RUNS, extra]), {"A": "model-A", "B": "model-B", "C": "model-C"})
    assert len(picked) == 4


def test_decisions_match_sweep() -> None:
    answers = select(RUNS)
    for theta in (0.3, 0.75):
        acc = sweep(answers, thetas=(theta,))["accuracy"][0]
        d = decisions(answers, theta)
        assert sum(d.values()) / len(d) == pytest.approx(acc)
