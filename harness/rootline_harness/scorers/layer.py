"""Layer-attribution accuracy (RQ2): network vs application vs none."""

from __future__ import annotations

from rootline_harness.schema import ModelOutput
from rootline_harness.scorers.accuracy import Label


def layer_correct(out: ModelOutput | None, label: Label) -> bool:
    if out is None or out.abstain:
        return False
    return out.layer == label.layer
