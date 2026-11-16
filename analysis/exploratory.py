"""Exploratory, not pre-registered: score faults on a link at either end.

The pre-registered scoring names one root-cause service per fault: for a
fault on an edge (network faults, paymentUnreachable, the hardware arm) it
is the downstream service, e.g. payment for checkout -> payment. Models
often name the caller instead. This module re-scores the same answers with
one change: for an edge fault, a hypothesis naming either end of the edge
(with the right category) counts as correct. Everything else, including the
hypothesis tests, is untouched; this only shows how much the rule matters.
"""

from __future__ import annotations

import polars as pl

from rootline_harness.schema import ModelOutput, parse_output
from rootline_harness.scorers import Label
from rootline_harness.scorers.accuracy import norm, norm_category, top_k


def edge_ends(label: Label) -> set[str] | None:
    if not label.edge or label.healthy or "->" not in label.edge:
        return None
    return {norm(s) for s in label.edge.split("->")}


def either_end_correct(out: ModelOutput | None, label: Label, k: int) -> bool:
    """top-k with the rule relaxed to either end of a broken edge."""
    ends = edge_ends(label)
    if ends is None or out is None or out.abstain:
        return top_k(out, label, k)
    return any(
        norm(h.service) in ends and norm_category(h.category) == label.category
        for h in out.ranked()[:k]
    )


def edge_scoring(runs: pl.DataFrame, labels: dict[str, Label]) -> pl.DataFrame:
    """Per model, combined evidence, unperturbed: official vs either-end."""
    df = runs.filter((pl.col("condition") == "combined") & (pl.col("perturbation") == "p0"))
    rows = []
    for model in sorted(df["model_id"].unique().to_list()):
        recs = df.filter(pl.col("model_id") == model).to_dicts()
        official1 = either1 = official3 = either3 = 0
        e_n = e_official = e_either = 0
        for r in recs:
            label = labels[str(r["incident_id"])]
            out, _ = parse_output(str(r["raw_output"]))
            o1, x1 = bool(r["top1"]), either_end_correct(out, label, 1)
            official1 += o1
            either1 += x1
            official3 += bool(r["top3"])
            either3 += either_end_correct(out, label, 3)
            if edge_ends(label) is not None:
                e_n += 1
                e_official += o1
                e_either += x1
        n = len(recs)
        rows.append(
            {
                "model_id": model,
                "n": n,
                "top1_official": official1 / n if n else None,
                "top1_either_end": either1 / n if n else None,
                "top3_official": official3 / n if n else None,
                "top3_either_end": either3 / n if n else None,
                "n_edge_faults": e_n,
                "edge_top1_official": e_official / e_n if e_n else None,
                "edge_top1_either_end": e_either / e_n if e_n else None,
            }
        )
    return pl.DataFrame(rows)
