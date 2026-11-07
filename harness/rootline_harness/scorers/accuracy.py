"""Top-1 / top-3 accuracy and healthy false alarms.

A hypothesis is correct when its (service, category) pair matches the label.
For a healthy snapshot the correct answer is "no fault": layer "none"
without abstaining. Abstaining is never correct, but it is not a false alarm.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from rootline_harness.schema import Hypothesis, ModelOutput


@dataclass(frozen=True)
class Label:
    fault: str
    service: str
    category: str
    layer: str
    edge: str | None = None
    flag: str | None = None
    variant: str | None = None

    @property
    def healthy(self) -> bool:
        return self.layer == "none"

    @staticmethod
    def from_dict(d: Mapping[str, object]) -> Label:
        def opt(key: str) -> str | None:
            v = d.get(key)
            return None if v is None else str(v)

        return Label(
            fault=str(d["fault"]),
            service=str(d["service"]),
            category=str(d["category"]),
            layer=str(d["layer"]),
            edge=opt("edge"),
            flag=opt("flag"),
            variant=opt("variant"),
        )


def norm(s: str) -> str:
    """Normalise a model-written name: case, spaces and underscores."""
    return "-".join(s.strip().lower().replace("_", "-").split())


def norm_category(s: str) -> str:
    return "_".join(s.strip().lower().replace("-", " ").split())


def real_service(name: str, inverse: Mapping[str, str] | None) -> str:
    """Map an anonymised svc-NN back to the real service name under P1."""
    n = norm(name)
    if inverse:
        return inverse.get(n, n)
    return n


def hypothesis_correct(h: Hypothesis, label: Label, inverse: Mapping[str, str] | None) -> bool:
    return (
        real_service(h.service, inverse) == label.service
        and norm_category(h.category) == label.category
    )


def claims_fault(out: ModelOutput | None) -> bool:
    return out is not None and not out.abstain and out.layer != "none"


def top_k(
    out: ModelOutput | None, label: Label, k: int, inverse: Mapping[str, str] | None = None
) -> bool:
    if out is None or out.abstain:
        return False
    if label.healthy:
        return not claims_fault(out)
    return any(hypothesis_correct(h, label, inverse) for h in out.ranked()[:k])


def false_alarm(out: ModelOutput | None, label: Label) -> bool | None:
    """True if the model claims a fault in a healthy snapshot; None for
    fault snapshots, where the metric does not apply."""
    if not label.healthy:
        return None
    return claims_fault(out)
