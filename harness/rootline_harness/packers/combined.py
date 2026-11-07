"""Build the evidence pack for one evidence condition.

Every condition gets the same token budget, so conditions differ in signal,
not size. The combined condition gives a third of the budget to each signal.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, get_args

from rootline_harness.packers.budget import fit_pack
from rootline_harness.packers.evidence import Pack, Section
from rootline_harness.packers.logs import pack_logs
from rootline_harness.packers.metrics import pack_metrics
from rootline_harness.packers.snapshot import Snapshot
from rootline_harness.packers.traces import pack_traces

Condition = Literal["metrics", "traces", "logs", "combined"]
CONDITIONS: tuple[Condition, ...] = get_args(Condition)

_PACKERS: dict[str, Callable[[Snapshot], Section]] = {
    "metrics": pack_metrics,
    "traces": pack_traces,
    "logs": pack_logs,
}


def build_pack(snap: Snapshot, condition: Condition, budget: int) -> Pack:
    """Pack a snapshot for a condition within budget tokens."""
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}")
    signals = ["metrics", "traces", "logs"] if condition == "combined" else [condition]
    sections = tuple(_PACKERS[s](snap) for s in signals)
    return fit_pack(Pack(snap.incident_id, condition, "p0", sections), budget)
