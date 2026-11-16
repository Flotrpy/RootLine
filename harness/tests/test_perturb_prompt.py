import re

import pytest

from rootline_harness.catalog import SERVICES
from rootline_harness.packers import CONDITIONS, PROMPT_BUDGET, Snapshot, count_tokens
from rootline_harness.perturb import anonymise_text, invert, mapping_for
from rootline_harness.prompt import build_prompt, retry_text


def test_mapping_is_deterministic_and_complete() -> None:
    a = mapping_for("paymentFailure-r1")
    assert a == mapping_for("paymentFailure-r1")
    assert set(a) == set(SERVICES)
    assert len(set(a.values())) == len(SERVICES)
    assert a != mapping_for("paymentFailure-r2")
    assert invert(a)[a["payment"]] == "payment"


@pytest.mark.parametrize(
    ("text", "expect_gone", "expect_kept"),
    [
        ("svc=payment metric=error_ratio", ["payment"], ["metric=error_ratio"]),
        ("oteldemo.PaymentService/Charge", ["Payment"], ["Service/Charge"]),
        ("product-catalog:GetProduct > productcatalog", ["product", "catalog"], ["GetProduct"]),
        ("frontend-proxy:ingress > frontend:GET /", ["frontend"], ["ingress"]),
        ("handled request in 5 ms, read cart", ["cart"], ["handled", "read"]),
        ("oteldemo.AdService/GetAds", ["AdService"], ["GetAds"]),
        ("FRAUD_DETECTION_ADDR=fraud-detection:8080", ["FRAUD", "fraud"], ["_ADDR="]),
        ("trace=7b9757ad AD_SERVICE", ["AD_"], ["7b9757ad"]),
    ],
)
def test_anonymise_text(text: str, expect_gone: list[str], expect_kept: list[str]) -> None:
    m = mapping_for("x-r1")
    out = anonymise_text(text, m)
    for g in expect_gone:
        assert g not in out, out
    for k in expect_kept:
        assert k in out, out
    assert re.search(r"svc-\d\d", out)


def test_payments_plural_and_load_are_untouched() -> None:
    m = mapping_for("x-r1")
    assert anonymise_text("payments loading", m) == "payments loading"


@pytest.mark.parametrize("condition", CONDITIONS)
@pytest.mark.parametrize("perturbation", ["p0", "p1"])
def test_full_prompt_fits_budget(snapshot: Snapshot, condition, perturbation) -> None:
    p = build_prompt(snapshot, condition, perturbation)
    assert p.tokens == count_tokens(p.text) <= PROMPT_BUDGET
    assert p.pack.perturbation == perturbation
    # The budget should be used, not wasted.
    assert p.tokens > PROMPT_BUDGET * 0.5 or condition != "combined"


def test_p1_prompt_has_no_service_names(snapshot: Snapshot) -> None:
    p = build_prompt(snapshot, "combined", "p1")
    assert p.mapping is not None
    for svc in SERVICES:
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(svc) + r"(?![a-z0-9])")
        assert not pat.search(p.text), f"{svc} leaked into the P1 prompt"
    assert "Payment" not in p.text
    for ids in p.pack.evidence_index().values():
        assert all(s.startswith("svc-") for s in ids)


def test_prompt_lists_services_and_schema(snapshot: Snapshot) -> None:
    p = build_prompt(snapshot, "metrics")
    assert "payment" in p.text and "checkout->payment" in p.text
    assert '"abstain": bool' in p.text
    assert p.mapping is None


@pytest.mark.parametrize("condition", CONDITIONS)
def test_retry_prompt_still_fits(snapshot: Snapshot, condition) -> None:
    p = build_prompt(snapshot, condition, "p1")
    worst_error = "schema violation: " + "x" * 5000
    assert count_tokens(retry_text(p.text, worst_error)) <= PROMPT_BUDGET
