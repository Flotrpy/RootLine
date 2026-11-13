"""Per-run scoring. Aggregate statistics live in analysis/."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from rootline_harness.schema import ModelOutput
from rootline_harness.scorers.accuracy import Label, false_alarm, top_k
from rootline_harness.scorers.calibration import brier, ece
from rootline_harness.scorers.evidence import evidence_validity
from rootline_harness.scorers.layer import layer_correct


@dataclass(frozen=True)
class RunScore:
    parsed_ok: bool
    abstain: bool
    top1: bool
    top3: bool
    layer_ok: bool
    evidence_validity: float | None
    false_alarm: bool | None
    confidence: float  # top hypothesis; 0 when there is none
    action_type: str | None
    action_target: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def score_run(
    out: ModelOutput | None,
    label: Label,
    index: Mapping[str, tuple[str, ...]],
    mapping: Mapping[str, str] | None = None,
) -> RunScore:
    """Score one parsed output. An unparsed output (None) scores as an
    abstention. mapping is the P1 real->svc-NN mapping, if any."""
    inverse = {v: k for k, v in mapping.items()} if mapping else None
    top = out.top() if out else None
    action_target = out.action.target if out else None
    if action_target and inverse:
        action_target = inverse.get(action_target, action_target)
    return RunScore(
        parsed_ok=out is not None,
        abstain=out is None or out.abstain,
        top1=top_k(out, label, 1, inverse),
        top3=top_k(out, label, 3, inverse),
        layer_ok=layer_correct(out, label),
        evidence_validity=evidence_validity(out, label, index, inverse),
        false_alarm=false_alarm(out, label),
        confidence=top.confidence if top else 0.0,
        action_type=out.action.type if out else None,
        action_target=action_target,
    )


__all__ = ["Label", "RunScore", "brier", "ece", "score_run"]
