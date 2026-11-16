"""Traces packer: the 20 slowest and 20 errored traces after fault onset,
each collapsed to its critical path.

The critical path starts at the root span and repeatedly follows the child
that finishes last. Consecutive hops in the same service are merged.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import polars as pl

from rootline_harness.packers.evidence import Section, clip, make_lines
from rootline_harness.packers.snapshot import Snapshot

N_SLOWEST = 20
N_ERRORED = 20
MAX_OPERATION = 48


@dataclass(frozen=True)
class _Span:
    span_id: str
    parent: str | None
    service: str
    operation: str
    start: int
    duration: int
    error: bool

    @property
    def end(self) -> int:
        return self.start + self.duration


def _is_error(col: pl.Expr) -> pl.Expr:
    return col.str.to_uppercase().str.contains("ERROR")


def _select_traces(snap: Snapshot) -> list[tuple[str, bool]]:
    """Pick trace IDs: errored and slowest, interleaved so truncation keeps
    a mix. Returns (trace_id, errored) in rank order."""
    s = snap.spans
    if s.is_empty():
        return []
    t0_ns, end_ns = snap.t0_ms * 1_000_000, snap.end_ms * 1_000_000
    per_trace = (
        s.group_by("trace_id")
        .agg(
            start=pl.col("start_unix_nano").min(),
            end=(pl.col("start_unix_nano") + pl.col("duration_ns")).max(),
            errored=_is_error(pl.col("status_code")).any(),
        )
        .filter((pl.col("start") >= t0_ns) & (pl.col("start") < end_ns))
        .with_columns(dur=pl.col("end") - pl.col("start"))
        .sort(["dur", "trace_id"], descending=[True, False])
    )
    errored = per_trace.filter(pl.col("errored"))["trace_id"].head(N_ERRORED).to_list()
    chosen = set(errored)
    slowest = [t for t in per_trace["trace_id"].to_list() if t not in chosen][:N_SLOWEST]
    out: list[tuple[str, bool]] = []
    for i in range(max(len(errored), len(slowest))):
        if i < len(errored):
            out.append((errored[i], True))
        if i < len(slowest):
            out.append((slowest[i], False))
    return out


def _critical_path(spans: list[_Span]) -> list[_Span]:
    by_id = {sp.span_id: sp for sp in spans}
    children: dict[str, list[_Span]] = defaultdict(list)
    roots = []
    for sp in spans:
        if sp.parent and sp.parent in by_id:
            children[sp.parent].append(sp)
        else:
            roots.append(sp)
    node = min(roots, key=lambda r: (r.start, -r.duration, r.span_id))
    path = [node]
    while children[node.span_id]:
        node = max(children[node.span_id], key=lambda c: (c.end, -c.start, c.span_id))
        path.append(node)
    return path


def _render_path(path: list[_Span]) -> str:
    hops: list[str] = []
    prev = None
    for sp in path:
        if sp.service == prev:
            if sp.error and not hops[-1].endswith("!"):
                hops[-1] += "!"
            continue
        op = clip(sp.operation, MAX_OPERATION)
        hops.append(f"{sp.service}:{op} {sp.duration // 1_000_000}ms" + ("!" if sp.error else ""))
        prev = sp.service
    return " > ".join(hops)


def pack_traces(snap: Snapshot) -> Section:
    picked = _select_traces(snap)
    ids = [t for t, _ in picked]
    rows = (
        snap.spans.filter(pl.col("trace_id").is_in(ids))
        .with_columns(error=_is_error(pl.col("status_code")))
        .sort(["trace_id", "start_unix_nano", "span_id"])
    )
    spans_by_trace: dict[str, list[_Span]] = defaultdict(list)
    for r in rows.iter_rows(named=True):
        spans_by_trace[r["trace_id"]].append(
            _Span(
                span_id=r["span_id"],
                parent=r["parent_span_id"],
                service=r["service"],
                operation=r["operation"],
                start=r["start_unix_nano"],
                duration=r["duration_ns"],
                error=bool(r["error"]),
            )
        )
    ranked: list[tuple[tuple[str, ...], str]] = []
    for tid, _ in picked:
        spans = spans_by_trace[tid]
        errored = any(sp.error for sp in spans)
        path = _critical_path(spans)
        dur_ms = (max(sp.end for sp in spans) - min(sp.start for sp in spans)) // 1_000_000
        on_path = {sp.service for sp in path}
        err_elsewhere = sorted(
            {f"{sp.service}:{clip(sp.operation, MAX_OPERATION)}" for sp in spans if sp.error}
            - {f"{sp.service}:{clip(sp.operation, MAX_OPERATION)}" for sp in path if sp.error}
        )[:3]
        services = on_path | {sp.service for sp in spans if sp.error}
        text = f"trace={tid[:8]} dur={dur_ms}ms {'ERROR' if errored else 'ok'} path: "
        text += _render_path(path)
        if err_elsewhere:
            text += f" | errors off path: {', '.join(err_elsewhere)}"
        ranked.append((tuple(sorted(services)), text))
    return Section(
        signal="traces",
        header="slowest and errored traces after fault onset, critical path (! = error span)",
        lines=make_lines("traces", ranked),
    )
