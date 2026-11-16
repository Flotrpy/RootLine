"""Evidence validity: cited IDs that exist and belong to the root-cause
service, divided by all cited IDs.

Only the top-ranked hypothesis is scored: lower-ranked hypotheses are
expected to cite other services. A trace line belongs to every service on
its critical path or with an error span; metric and log lines belong to one.
"""

from __future__ import annotations

from collections.abc import Mapping

from rootline_harness.schema import ModelOutput
from rootline_harness.scorers.accuracy import Label


def evidence_validity(
    out: ModelOutput | None,
    label: Label,
    index: Mapping[str, tuple[str, ...]],
    inverse: Mapping[str, str] | None = None,
) -> float | None:
    """Return the share of valid citations, or None when it is undefined:
    unparsed output, a healthy snapshot, or a top hypothesis citing nothing."""
    if out is None or label.healthy:
        return None
    top = out.top()
    if top is None or not top.evidence:
        return None
    valid = 0
    for cited in top.evidence:
        services = index.get(cited.strip().upper())
        if services is None:
            continue  # hallucinated or truncated-away ID
        real = {inverse.get(s, s) for s in services} if inverse else set(services)
        if label.service in real:
            valid += 1
    return valid / len(top.evidence)
