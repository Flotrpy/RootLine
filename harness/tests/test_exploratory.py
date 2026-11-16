import json

from analysis.exploratory import edge_ends, either_end_correct
from rootline_harness.schema import parse_output
from rootline_harness.scorers import Label

EDGE = Label(fault="toxiLatency", service="payment", category="network_latency",
             layer="network", edge="checkout->payment")  # fmt: skip
APP = Label(fault="paymentFailure", service="payment", category="error", layer="application")


def answer(service: str, category: str, layer: str = "network") -> str:
    hyp = {"rank": 1, "service": service, "category": category, "confidence": 0.9,
           "evidence": ["M-0001"]}  # fmt: skip
    return json.dumps({"abstain": False, "layer": layer, "hypotheses": [hyp],
                       "action": {"type": "no_action", "target": None}})  # fmt: skip


def test_caller_counts_only_for_edge_faults() -> None:
    caller, _ = parse_output(answer("checkout", "network_latency"))
    assert either_end_correct(caller, EDGE, 1)
    app_caller, _ = parse_output(answer("checkout", "error", "application"))
    assert not either_end_correct(app_caller, APP, 1)  # app faults keep one service


def test_category_still_has_to_match() -> None:
    wrong, _ = parse_output(answer("checkout", "latency"))
    assert not either_end_correct(wrong, EDGE, 1)


def test_edge_ends() -> None:
    assert edge_ends(EDGE) == {"checkout", "payment"}
    assert edge_ends(APP) is None
