import math

import pytest

from rootline_harness.perturb import mapping_for
from rootline_harness.schema import ModelOutput
from rootline_harness.scorers import Label, brier, ece, score_run

PAYMENT = Label("paymentFailure", "payment", "error", "application", None, "paymentFailure", "50%")
HEALTHY = Label("healthy", "none", "none", "none")
RESET = Label("toxiReset", "payment", "network_reset", "network", "checkout->payment")

INDEX = {
    "M-0001": ("payment",),
    "T-0001": ("checkout", "frontend", "payment"),
    "L-0001": ("checkout",),
}


def out(
    layer="application",
    hyps=(("payment", "error", 0.8, ["M-0001"]),),
    action=("disable_feature", "payment"),
    abstain=False,
) -> ModelOutput:
    return ModelOutput.model_validate(
        {
            "abstain": abstain,
            "layer": layer,
            "hypotheses": [
                {"rank": i, "service": s, "category": c, "confidence": p, "evidence": e}
                for i, (s, c, p, e) in enumerate(hyps, start=1)
            ],
            "action": {"type": action[0], "target": action[1]},
        }
    )


def test_correct_diagnosis() -> None:
    s = score_run(out(), PAYMENT, INDEX)
    assert s.top1 and s.top3 and s.layer_ok
    assert s.evidence_validity == 1.0
    assert s.false_alarm is None
    assert s.confidence == 0.8


def test_top3_but_not_top1() -> None:
    o = out(
        hyps=(
            ("checkout", "error", 0.5, ["L-0001"]),
            ("Payment", "Error", 0.3, ["M-0001"]),
        )
    )
    s = score_run(o, PAYMENT, INDEX)
    assert not s.top1 and s.top3
    assert s.evidence_validity == 0.0  # top hypothesis cites only checkout


def test_name_normalisation() -> None:
    o = out(hyps=(("  Product_Catalog ", "Lock Contention", 0.9, []),))
    lbl = Label("productCatalogLockContention", "product-catalog", "lock_contention", "application")
    s = score_run(o, lbl, INDEX)
    assert s.top1
    assert s.evidence_validity is None  # nothing cited


def test_evidence_validity_counts_hallucinated_ids() -> None:
    o = out(hyps=(("payment", "error", 0.9, ["M-0001", "T-0001", "L-0001", "M-9999"]),))
    s = score_run(o, PAYMENT, INDEX)
    assert s.evidence_validity == pytest.approx(2 / 4)


def test_layer_confusion() -> None:
    o = out(hyps=(("payment", "dependency_unavailable", 0.7, ["T-0001"]),))
    s = score_run(o, RESET, INDEX)
    assert not s.top1 and not s.layer_ok


@pytest.mark.parametrize(
    ("o", "top1", "false_alarm"),
    [
        (out(layer="none", hyps=(), action=("no_action", None)), True, False),
        (out(), False, True),
        (out(layer="none", hyps=(), action=("no_action", None), abstain=True), False, False),
        (None, False, False),
    ],
)
def test_healthy_control(o, top1, false_alarm) -> None:
    s = score_run(o, HEALTHY, INDEX)
    assert s.top1 == top1
    assert s.false_alarm == false_alarm
    assert s.evidence_validity is None


def test_unparsed_output_scores_as_abstain() -> None:
    s = score_run(None, PAYMENT, INDEX)
    assert not s.parsed_ok and s.abstain
    assert not (s.top1 or s.top3 or s.layer_ok)
    assert s.confidence == 0.0


def test_p1_maps_names_back() -> None:
    m = mapping_for("paymentFailure-r1")
    anon_index = {k: tuple(m[s] for s in v) for k, v in INDEX.items()}
    o = out(
        hyps=((m["payment"], "error", 0.8, ["M-0001"]),),
        action=("disable_feature", m["payment"]),
    )
    s = score_run(o, PAYMENT, anon_index, m)
    assert s.top1 and s.evidence_validity == 1.0
    assert s.action_target == "payment"


def test_brier() -> None:
    assert brier([1.0, 0.0], [True, False]) == 0.0
    assert brier([0.5, 0.5], [True, False]) == 0.25
    assert math.isnan(brier([], []))
    with pytest.raises(ValueError):
        brier([1.2], [True])


def test_ece() -> None:
    # Perfectly calibrated within each bin.
    conf = [0.25] * 4 + [0.75] * 4
    correct = [True, False, False, False, True, True, True, False]
    assert ece(conf, correct) == pytest.approx(0.0)
    # Always 90% confident, always wrong.
    assert ece([0.9] * 5, [False] * 5) == pytest.approx(0.9)
    # 1.0 lands in the last bin.
    assert ece([1.0], [True]) == pytest.approx(0.0)
