"""Figures for the technical report, rendered to SVG offline with
vl-convert. Every figure is labelled as a pilot with its sample size."""

from __future__ import annotations

import math
from pathlib import Path

import altair as alt
import polars as pl
import vl_convert

from rootline_harness.scorers import Label


def save_svg(chart: alt.TopLevelMixin, path: Path) -> None:
    path.write_text(vl_convert.vegalite_to_svg(chart.to_json()))


def _data(df: pl.DataFrame) -> alt.Data:
    # NaN is not valid JSON; Vega-Lite treats null as missing.
    rows = [
        {k: None if isinstance(v, float) and math.isnan(v) else v for k, v in r.items()}
        for r in df.to_dicts()
    ]
    return alt.Data(values=rows)


def rq1_conditions(summary: pl.DataFrame) -> alt.TopLevelMixin:
    df = summary.filter(pl.col("perturbation") == "p0")
    n = int(df["n"].max() or 0)  # type: ignore[arg-type]
    # One panel per condition with models on the x axis: CI rules centre on
    # a plain band scale, but not inside xOffset sub-bands.
    base = alt.Chart().encode(
        x=alt.X("model_id:N", title=None, axis=alt.Axis(labels=False, ticks=False)),
        color=alt.Color("model_id:N", title="Model"),
    )
    bars = base.mark_bar().encode(
        y=alt.Y("top1:Q", title="Top-1 accuracy", scale=alt.Scale(domain=[0, 1]))
    )
    errs = base.mark_rule(color="black", strokeWidth=1.5).encode(
        y="top1_ci_low:Q", y2="top1_ci_high:Q", color=alt.value("black")
    )
    return (
        alt.layer(bars, errs, data=_data(df))
        .properties(width=100, height=260)
        .facet(
            column=alt.Column(
                "condition:N", sort=["metrics", "traces", "logs", "combined"], title=None
            )
        )
        .properties(title=f"RQ1: accuracy by evidence condition (pilot, n={n} per bar, 95% CI)")
    )


def rq2_layers(runs: pl.DataFrame, labels: dict[str, Label]) -> alt.TopLevelMixin:
    df = (
        runs.filter((pl.col("condition") == "combined") & (pl.col("perturbation") == "p0"))
        .with_columns(
            true_layer=pl.col("incident_id").replace_strict(
                {i: lbl.layer for i, lbl in labels.items()}, default="unknown"
            )
        )
        .group_by("model_id", "true_layer")
        .agg(acc=pl.col("layer_ok").cast(pl.Float64).mean(), n=pl.len())
        .sort("model_id", "true_layer")
    )
    return (
        alt.Chart(_data(df))
        .mark_bar()
        .encode(
            x=alt.X("true_layer:N", title="True layer"),
            xOffset="model_id:N",
            y=alt.Y("acc:Q", title="Layer-attribution accuracy", scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("model_id:N", title="Model"),
            tooltip=["model_id:N", "true_layer:N", "acc:Q", "n:Q"],
        )
        .properties(title="RQ2: layer attribution by true layer (pilot)", width=360, height=240)
    )


def rq4_cascade(table: pl.DataFrame, tiers: pl.DataFrame) -> alt.TopLevelMixin:
    n = int(table["n"][0])
    line = (
        alt.Chart(_data(table))
        .mark_line(point=True)
        .encode(
            x=alt.X("total_tokens:Q", title="Total tokens"),
            y=alt.Y("accuracy:Q", title="Top-1 accuracy", scale=alt.Scale(domain=[0, 1])),
            tooltip=[
                "theta:Q",
                "accuracy:Q",
                "total_tokens:Q",
                "escalation_rate_b:Q",
                "escalation_rate_c:Q",
            ],
        )
    )
    points = (
        alt.Chart(_data(tiers))
        .mark_point(shape="diamond", size=120, filled=True)
        .encode(x="total_tokens:Q", y="accuracy:Q", color=alt.Color("tier:N", title="Tier alone"))
    )
    return alt.layer(
        line,
        points,
        title=f"RQ4: cascade accuracy vs tokens over theta (pilot, n={n})",
        width=420,
        height=260,
    )
