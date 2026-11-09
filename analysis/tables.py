"""Summary tables and the hypothesis tests.

Every number here is computed from run records, labels, remediation trials
and baseline predictions on disk; nothing is entered by hand. Hypotheses
whose inputs do not exist yet are reported as "not run", never guessed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import polars as pl

from analysis.stats import bootstrap_diff, bootstrap_mean, fisher_exact, holm, mcnemar
from cascade.sweep import decisions, rq4, select, single_tiers, sweep
from rootline_harness.catalog import HW_EMULATES
from rootline_harness.schema import parse_output
from rootline_harness.scorers import Label, brier, ece
from rootline_harness.scorers.accuracy import claims_fault

SINGLE_CONDITIONS = ("metrics", "traces", "logs")
# TODO(flotrpy): pre-register the theta used for the RQ4 significance test
# before the runs; the full sweep is reported either way.
RQ4_THETA = 0.7
ALPHA = 0.05
# v0.1 tests RQ1 and RQ2 only; the other four are held for v0.2 and
# reported as deferred, outside the Holm family.
V01_SCOPE = ("RQ1", "RQ2")


def _claims_fault(record: dict[str, object]) -> bool:
    """Re-read the stored answer: an abstention is wrong on a healthy
    snapshot but is not a false alarm."""
    out, _ = parse_output(str(record["raw_output"])) if record["parsed_ok"] else (None, None)
    return claims_fault(out)


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else math.nan


def summary(runs: pl.DataFrame, labels: dict[str, Label]) -> pl.DataFrame:
    """One row per (model, condition, perturbation)."""
    rows = []
    keys = ["model_id", "tier", "condition", "perturbation"]
    for key, g in runs.sort(keys).group_by(keys, maintain_order=True):
        model, tier, cond, pert = key
        top1 = [float(x) for x in g["top1"]]
        ci = bootstrap_mean(top1)
        healthy = [r for r in g.iter_rows(named=True) if labels[r["incident_id"]].healthy]
        faults = [r for r in g.iter_rows(named=True) if not labels[r["incident_id"]].healthy]
        ev = [r["evidence_validity"] for r in faults if r["evidence_validity"] is not None]
        conf = [float(c) for c in g["confidence"]]
        correct = [bool(x) for x in g["top1"]]
        rows.append(
            {
                "model_id": model,
                "tier": tier,
                "condition": cond,
                "perturbation": pert,
                "n": g.height,
                "top1": ci.estimate,
                "top1_ci_low": ci.low,
                "top1_ci_high": ci.high,
                "top3": _mean([float(x) for x in g["top3"]]),
                "layer_acc": _mean([float(x) for x in g["layer_ok"]]),
                "evidence_validity": _mean(ev),
                "uncited_share": 1 - len(ev) / len(faults) if faults else math.nan,
                "invalid_output_rate": 1 - _mean([float(x) for x in g["parsed_ok"]]),
                "healthy_false_alarm_rate": _mean([float(_claims_fault(r)) for r in healthy])
                if healthy
                else math.nan,
                "brier": brier(conf, correct),
                "ece": ece(conf, correct),
                "prompt_tokens": int(g["prompt_tokens"].sum()),
                "completion_tokens": int(g["completion_tokens"].sum()),
            }
        )
    return pl.DataFrame(rows)


def best_model(runs: pl.DataFrame) -> str | None:
    """Highest top-1 on the combined condition without perturbation."""
    df = runs.filter((pl.col("condition") == "combined") & (pl.col("perturbation") == "p0"))
    if df.is_empty():
        return None
    acc = (
        df.group_by("model_id")
        .agg(pl.col("top1").cast(pl.Float64).mean().alias("acc"))
        .sort(["acc", "model_id"], descending=[True, False])
    )
    return acc["model_id"][0]


def _outcomes(runs: pl.DataFrame, model: str, condition: str, pert: str, field: str = "top1"):
    df = runs.filter(
        (pl.col("model_id") == model)
        & (pl.col("condition") == condition)
        & (pl.col("perturbation") == pert)
    )
    return dict(zip(df["incident_id"], (bool(x) for x in df[field]), strict=True))


def _paired(a: dict[str, bool], b: dict[str, bool]) -> tuple[list[bool], list[bool]]:
    common = sorted(set(a) & set(b))
    return [a[i] for i in common], [b[i] for i in common]


@dataclass
class Hypothesis:
    rq: str
    statement: str
    status: str  # "tested", "not run: <reason>" or DEFERRED
    n: int = 0
    effect: float = math.nan
    effect_ci_low: float = math.nan
    effect_ci_high: float = math.nan
    threshold_met: bool | None = None
    test: str = ""
    p_value: float = math.nan
    p_holm: float = math.nan
    significant: bool | None = None
    detail: str = ""


STATEMENTS = {
    "RQ1": "Combined signals beat the best single signal by >= 10 pp top-1",
    "RQ2": "Layer accuracy is >= 15 pts lower on network faults than application faults",
    "RQ3": "Anonymising service names drops top-1 by >= 20% relative",
    "RQ4": "A cascade keeps >= 90% of the strongest model's accuracy with <= 50% of its tokens",
    "RQ5": "Remediation success is >= 20 pts below diagnosis accuracy",
    "RQ6": "The best LLM beats LightGBM on unseen fault types but not on seen ones",
}


DEFERRED = "deferred to v0.2"


def _not_run(rq: str, why: str) -> Hypothesis:
    return Hypothesis(rq, STATEMENTS[rq], f"not run: {why}")


def rq1(runs: pl.DataFrame, model: str) -> Hypothesis:
    combined = _outcomes(runs, model, "combined", "p0")
    singles = {c: _outcomes(runs, model, c, "p0") for c in SINGLE_CONDITIONS}
    singles = {c: o for c, o in singles.items() if o}
    if not combined or not singles:
        return _not_run("RQ1", "needs combined and single-signal runs")
    best = max(sorted(singles), key=lambda c: _mean([float(v) for v in singles[c].values()]))
    a, b = _paired(combined, singles[best])
    d = bootstrap_diff([float(x) for x in a], [float(x) for x in b])
    return Hypothesis(
        "RQ1",
        STATEMENTS["RQ1"],
        "tested",
        len(a),
        d.estimate,
        d.low,
        d.high,
        d.estimate >= 0.10,
        "McNemar exact",
        mcnemar(a, b).p_value,
        detail=f"model={model}; best single={best}",
    )


def rq2(runs: pl.DataFrame, labels: dict[str, Label], model: str) -> Hypothesis:
    layer = _outcomes(runs, model, "combined", "p0", "layer_ok")
    app = [v for i, v in layer.items() if labels[i].layer == "application"]
    net = [v for i, v in layer.items() if labels[i].layer == "network"]
    if not app or not net:
        return _not_run("RQ2", "needs application and network fault runs")
    effect = _mean([float(x) for x in app]) - _mean([float(x) for x in net])
    p = fisher_exact(sum(app), len(app), sum(net), len(net))
    return Hypothesis(
        "RQ2",
        STATEMENTS["RQ2"],
        "tested",
        len(app) + len(net),
        effect,
        threshold_met=effect >= 0.15,
        test="Fisher exact",
        p_value=p,
        detail=f"model={model}; app n={len(app)}, network n={len(net)}",
    )


def rq3(runs: pl.DataFrame, model: str) -> Hypothesis:
    p0 = _outcomes(runs, model, "combined", "p0")
    p1 = _outcomes(runs, model, "combined", "p1")
    a, b = _paired(p0, p1)
    if not a:
        return _not_run("RQ3", "needs p0 and p1 runs on the same snapshots")
    acc0 = _mean([float(x) for x in a])
    rel = (acc0 - _mean([float(x) for x in b])) / acc0 if acc0 else math.nan
    return Hypothesis(
        "RQ3",
        STATEMENTS["RQ3"],
        "tested",
        len(a),
        rel,
        threshold_met=rel >= 0.20 if not math.isnan(rel) else None,
        test="McNemar exact",
        p_value=mcnemar(a, b).p_value,
        detail=f"model={model}; effect is relative drop",
    )


def rq4_hypothesis(runs: pl.DataFrame) -> tuple[Hypothesis, pl.DataFrame | None]:
    try:
        answers = select(runs)
    except ValueError as e:
        return _not_run("RQ4", str(e)), None
    if not answers:
        return _not_run("RQ4", "no snapshot was run by all three tiers"), None
    table = rq4(sweep(answers), single_tiers(answers))
    row = table.filter(pl.col("theta") == RQ4_THETA).row(0, named=True)
    cascade = decisions(answers, RQ4_THETA)
    tier_c = {i: a["C"].correct for i, a in answers.items()}
    a, b = _paired(cascade, tier_c)
    return (
        Hypothesis(
            "RQ4",
            STATEMENTS["RQ4"],
            "tested",
            len(a),
            row["accuracy_kept"],
            threshold_met=bool(row["hypothesis_holds"]),
            test="McNemar exact vs Tier C",
            p_value=mcnemar(a, b).p_value,
            detail=f"theta={RQ4_THETA}; effect is accuracy kept; tokens used="
            f"{row['tokens_used']:.3f}",
        ),
        table,
    )


def rq5(runs: pl.DataFrame, model: str, trials: list[dict[str, object]]) -> Hypothesis:
    if not trials:
        return _not_run("RQ5", "no remediation trials recorded")
    diag = _outcomes(runs, model, "combined", "p0")
    recovered = {str(t["incident_id"]): bool(t["recovered"]) for t in trials}
    a, b = _paired(diag, recovered)
    if not a:
        return _not_run("RQ5", "trials do not match the model's runs")
    d = bootstrap_diff([float(x) for x in a], [float(x) for x in b])
    harmful = _mean([float(bool(t["harmful"])) for t in trials])
    return Hypothesis(
        "RQ5",
        STATEMENTS["RQ5"],
        "tested",
        len(a),
        d.estimate,
        d.low,
        d.high,
        d.estimate >= 0.20,
        "McNemar exact",
        mcnemar(a, b).p_value,
        detail=f"model={model}; harmful-action rate={harmful:.3f}",
    )


def rq6(runs: pl.DataFrame, model: str, baseline_preds: pl.DataFrame | None) -> Hypothesis:
    if baseline_preds is None or baseline_preds.is_empty():
        return _not_run("RQ6", "no baseline predictions")
    llm = _outcomes(runs, model, "combined", "p0")
    lgbm = baseline_preds.filter(pl.col("model") == "lightgbm")
    effects, p_unseen, n = {}, math.nan, 0
    for scheme in ("unseen", "seen"):
        s = lgbm.filter(pl.col("scheme") == scheme)
        base = dict(zip(s["incident_id"], (bool(x) for x in s["top1"]), strict=True))
        a, b = _paired(llm, base)
        if not a:
            return _not_run("RQ6", f"no overlap with {scheme} baseline predictions")
        effects[scheme] = _mean([float(x) for x in a]) - _mean([float(x) for x in b])
        if scheme == "unseen":
            p_unseen, n = mcnemar(a, b).p_value, len(a)
    return Hypothesis(
        "RQ6",
        STATEMENTS["RQ6"],
        "tested",
        n,
        effects["unseen"],
        threshold_met=effects["unseen"] > 0 and effects["seen"] <= 0,
        test="McNemar exact (unseen)",
        p_value=p_unseen,
        detail=f"model={model}; effect is LLM minus LightGBM on unseen; "
        f"seen effect={effects['seen']:.3f}",
    )


def hypotheses(
    runs: pl.DataFrame,
    labels: dict[str, Label],
    trials: list[dict[str, object]],
    baseline_preds: pl.DataFrame | None,
) -> tuple[pl.DataFrame, pl.DataFrame | None]:
    """All six hypotheses, with Holm-adjusted p-values across those tested.

    Only V01_SCOPE is tested; the rest are reported as deferred to v0.2.
    """
    model = best_model(runs)
    cascade_table = None
    if model is None:
        rows = [_not_run(rq, "no combined p0 runs") for rq in V01_SCOPE]
    else:
        tests = {
            "RQ1": lambda: rq1(runs, model),
            "RQ2": lambda: rq2(runs, labels, model),
            "RQ3": lambda: rq3(runs, model),
            "RQ5": lambda: rq5(runs, model, trials),
            "RQ6": lambda: rq6(runs, model, baseline_preds),
        }
        rows = []
        for rq in V01_SCOPE:
            if rq == "RQ4":
                h4, cascade_table = rq4_hypothesis(runs)
                rows.append(h4)
            else:
                rows.append(tests[rq]())
    rows += [Hypothesis(rq, STATEMENTS[rq], DEFERRED) for rq in STATEMENTS if rq not in V01_SCOPE]
    rows.sort(key=lambda h: h.rq)
    tested = [h for h in rows if h.status == "tested" and not math.isnan(h.p_value)]
    for h, p in zip(tested, holm([h.p_value for h in tested]), strict=True):
        h.p_holm = p
        h.significant = p < ALPHA
    return pl.DataFrame([asdict(h) for h in rows]), cascade_table


def emulation_validity(runs: pl.DataFrame, labels: dict[str, Label]) -> pl.DataFrame:
    """Accuracy on each real Wi-Fi fault next to its emulated counterpart,
    per model, on the combined unperturbed condition.

    A large gap means emulated network faults are not a fair stand-in for
    real ones, which is a finding in itself. Not one of the six RQs, so it
    is outside the Holm family.
    """
    df = runs.filter((pl.col("condition") == "combined") & (pl.col("perturbation") == "p0"))
    df = df.with_columns(
        fault=pl.col("incident_id").replace_strict(
            {i: lbl.fault for i, lbl in labels.items()}, default=None
        )
    )
    rows = []
    for model in sorted(df["model_id"].unique().to_list()):
        m = df.filter(pl.col("model_id") == model)
        for hw, emu in HW_EMULATES.items():
            real = m.filter(pl.col("fault") == hw)
            sim = m.filter(pl.col("fault") == emu)
            if real.is_empty() or sim.is_empty():
                continue
            r_top1 = [bool(x) for x in real["top1"]]
            s_top1 = [bool(x) for x in sim["top1"]]
            r_layer = [bool(x) for x in real["layer_ok"]]
            s_layer = [bool(x) for x in sim["layer_ok"]]
            rows.append(
                {
                    "model_id": model,
                    "hardware_fault": hw,
                    "emulated_fault": emu,
                    "n_hardware": len(r_top1),
                    "n_emulated": len(s_top1),
                    "top1_hardware": _mean([float(x) for x in r_top1]),
                    "top1_emulated": _mean([float(x) for x in s_top1]),
                    "top1_gap": _mean([float(x) for x in r_top1])
                    - _mean([float(x) for x in s_top1]),
                    "top1_p_fisher": fisher_exact(
                        sum(r_top1), len(r_top1), sum(s_top1), len(s_top1)
                    ),
                    "layer_hardware": _mean([float(x) for x in r_layer]),
                    "layer_emulated": _mean([float(x) for x in s_layer]),
                }
            )
    return pl.DataFrame(rows)
