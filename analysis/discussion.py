"""Descriptive tables behind the report's discussion.

Nothing here is a hypothesis test: these break the same runs down by
evidence condition, by the true layer of the fault, by confidence, and by
what models blamed on healthy snapshots, so the report can discuss them with
numbers that come from the runs rather than from prose.
"""

from __future__ import annotations

from collections import Counter

import polars as pl

from rootline_harness.schema import parse_output
from rootline_harness.scorers import Label


def by_condition(runs: pl.DataFrame) -> pl.DataFrame:
    """Top-1, layer accuracy and invalid output per model and condition (P0)."""
    return (
        runs.filter(pl.col("perturbation") == "p0")
        .group_by("model_id", "condition")
        .agg(
            n=pl.len(),
            top1=pl.col("top1").mean(),
            layer_acc=pl.col("layer_ok").mean(),
            invalid_rate=(~pl.col("parsed_ok")).mean(),
        )
        .sort("model_id", "condition")
    )


def _with_labels(runs: pl.DataFrame, labels: dict[str, Label]) -> pl.DataFrame:
    ids = runs["incident_id"].unique().to_list()
    return runs.with_columns(
        true_layer=pl.col("incident_id").replace_strict({i: labels[i].layer for i in ids}),
        hardware=pl.col("incident_id").str.starts_with("hw"),
    )


def by_layer(runs: pl.DataFrame, labels: dict[str, Label]) -> pl.DataFrame:
    """Combined evidence: accuracy by the true layer, hardware kept apart."""
    df = _with_labels(
        runs.filter((pl.col("condition") == "combined") & (pl.col("perturbation") == "p0")),
        labels,
    )
    df = df.with_columns(
        group=pl.when(pl.col("hardware"))
        .then(pl.lit("hardware (network)"))
        .otherwise(pl.col("true_layer"))
    )
    return (
        df.group_by("model_id", "group")
        .agg(n=pl.len(), top1=pl.col("top1").mean(), layer_acc=pl.col("layer_ok").mean())
        .sort("model_id", "group")
    )


def calibration(runs: pl.DataFrame) -> pl.DataFrame:
    """Combined evidence: mean stated confidence of the top hypothesis
    against how often it was right."""
    df = runs.filter(
        (pl.col("condition") == "combined")
        & (pl.col("perturbation") == "p0")
        & pl.col("confidence").is_not_null()
    )
    return (
        df.group_by("model_id")
        .agg(n=pl.len(), mean_confidence=pl.col("confidence").mean(), top1=pl.col("top1").mean())
        .sort("model_id")
    )


def false_alarm_targets(runs: pl.DataFrame, labels: dict[str, Label]) -> pl.DataFrame:
    """On healthy snapshots (all conditions, P0): which service each model's
    top hypothesis blamed, and how many answers claimed a fault at all."""
    healthy = [i for i in runs["incident_id"].unique().to_list() if labels[i].healthy]
    df = runs.filter(pl.col("incident_id").is_in(healthy) & (pl.col("perturbation") == "p0"))
    rows = []
    for model in sorted(df["model_id"].unique().to_list()):
        recs = df.filter(pl.col("model_id") == model)["raw_output"].to_list()
        blamed: Counter[str] = Counter()
        claims = 0
        for raw in recs:
            out, _ = parse_output(str(raw))
            if out is None or out.abstain or out.layer == "none":
                continue
            claims += 1
            ranked = out.ranked()
            if ranked:
                blamed[ranked[0].service] += 1
        top, count = blamed.most_common(1)[0] if blamed else (None, 0)
        rows.append(
            {
                "model_id": model,
                "answers": len(recs),
                "fault_claims": claims,
                "most_blamed": top,
                "most_blamed_count": count,
            }
        )
    return pl.DataFrame(rows)


def layer_answers(runs: pl.DataFrame) -> pl.DataFrame:
    """Combined evidence: how often each model answered each layer."""
    df = runs.filter((pl.col("condition") == "combined") & (pl.col("perturbation") == "p0"))
    rows = []
    for model in sorted(df["model_id"].unique().to_list()):
        seen: Counter[str] = Counter()
        for raw in df.filter(pl.col("model_id") == model)["raw_output"].to_list():
            out, _ = parse_output(str(raw))
            seen["unparsed" if out is None else out.layer] += 1
        rows.append(
            {
                "model_id": model,
                "application": seen["application"],
                "network": seen["network"],
                "none": seen["none"],
                "unparsed": seen["unparsed"],
            }
        )
    return pl.DataFrame(rows)
