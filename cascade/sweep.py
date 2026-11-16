"""Offline cheap-first cascade (RQ4).

Every tier runs on every snapshot anyway, so any confidence threshold can be
simulated from the logged runs at no extra cost. For each snapshot the
cascade asks Tier A, then B, then C, and stops at the first answer it
accepts. Tier C's answer is always accepted.

An answer is escalated when it is unparsed, an abstention, or a fault claim
whose top confidence is below theta. A "no fault" answer (layer none) has no
confidence to compare and is accepted.
The cascade is v0.2 (RQ4): confirm this rule before then; the alternative
escalates every healthy claim, which would push all healthy controls to Tier C.

    uv run --project harness python -m cascade.sweep --runs data/runs/runs.parquet
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from rootline_harness.schema import parse_output

TIERS = ("A", "B", "C")
THETAS = tuple(round(0.30 + 0.05 * i, 2) for i in range(13))  # 0.30 .. 0.90


@dataclass(frozen=True)
class Answer:
    correct: bool
    tokens: int
    accept_at: float  # accepted for every theta <= this; inf = always, -1 = never


def _answer(row: dict[str, object]) -> Answer:
    tokens = int(row["prompt_tokens"]) + int(row["completion_tokens"])  # type: ignore[arg-type]
    correct = bool(row["top1"])
    if not row["parsed_ok"]:
        return Answer(correct, tokens, -1.0)
    out, _ = parse_output(str(row["raw_output"]))
    if out is None or out.abstain:
        return Answer(correct, tokens, -1.0)
    if out.layer == "none":
        return Answer(correct, tokens, float("inf"))
    return Answer(correct, tokens, float(row["confidence"]))  # type: ignore[arg-type]


def select(
    runs: pl.DataFrame,
    tier_models: dict[str, str] | None = None,
    condition: str = "combined",
    perturbation: str = "p0",
) -> dict[str, dict[str, Answer]]:
    """Return {incident: {tier: answer}} for incidents that every tier ran.

    tier_models picks one model per tier; by default each tier must have
    exactly one model in the runs.
    """
    df = runs.filter((pl.col("condition") == condition) & (pl.col("perturbation") == perturbation))
    if tier_models is None:
        tier_models = {}
        for tier in TIERS:
            models = sorted(df.filter(pl.col("tier") == tier)["model_id"].unique().to_list())
            if not models:
                raise ValueError(f"needs one model per tier (A, B, C); tier {tier} has none")
            if len(models) > 1:
                raise ValueError(f"tier {tier} has several models {models}; pick one per tier")
            tier_models[tier] = models[0]
    answers: dict[str, dict[str, Answer]] = {}
    for tier, model in tier_models.items():
        for row in df.filter(pl.col("model_id") == model).iter_rows(named=True):
            answers.setdefault(row["incident_id"], {})[tier] = _answer(row)
    return {i: a for i, a in sorted(answers.items()) if set(a) == set(TIERS)}


def sweep(answers: dict[str, dict[str, Answer]], thetas=THETAS) -> pl.DataFrame:
    rows = []
    n = len(answers)
    for theta in thetas:
        correct = tokens = to_b = to_c = 0
        for per_tier in answers.values():
            for i, tier in enumerate(TIERS):
                a = per_tier[tier]
                tokens += a.tokens
                if tier == "C" or a.accept_at >= theta:
                    correct += a.correct
                    break
                to_b += i == 0
                to_c += i == 1
        rows.append(
            {
                "theta": theta,
                "n": n,
                "accuracy": correct / n if n else float("nan"),
                "total_tokens": tokens,
                "accuracy_per_1k_tokens": correct / (tokens / 1000) if tokens else float("nan"),
                "escalation_rate_b": to_b / n if n else float("nan"),
                "escalation_rate_c": to_c / n if n else float("nan"),
            }
        )
    return pl.DataFrame(rows)


def decisions(answers: dict[str, dict[str, Answer]], theta: float) -> dict[str, bool]:
    """Per snapshot: is the cascade's accepted answer correct at theta?"""
    out = {}
    for inc, per_tier in answers.items():
        for tier in TIERS:
            a = per_tier[tier]
            if tier == "C" or a.accept_at >= theta:
                out[inc] = a.correct
                break
    return out


def single_tiers(answers: dict[str, dict[str, Answer]]) -> pl.DataFrame:
    """Each tier alone, as the reference for the cascade."""
    n = len(answers)
    rows = []
    for tier in TIERS:
        correct = sum(a[tier].correct for a in answers.values())
        tokens = sum(a[tier].tokens for a in answers.values())
        rows.append(
            {
                "tier": tier,
                "n": n,
                "accuracy": correct / n if n else float("nan"),
                "total_tokens": tokens,
            }
        )
    return pl.DataFrame(rows)


def rq4(sweep_df: pl.DataFrame, tiers_df: pl.DataFrame) -> pl.DataFrame:
    """Per theta: share of Tier C's accuracy kept and of its tokens used.
    The hypothesis holds at a theta where kept >= 0.9 and used <= 0.5."""
    c = tiers_df.filter(pl.col("tier") == "C").row(0, named=True)
    return sweep_df.with_columns(
        accuracy_kept=pl.col("accuracy") / c["accuracy"] if c["accuracy"] else None,
        tokens_used=pl.col("total_tokens") / c["total_tokens"] if c["total_tokens"] else None,
    ).with_columns(
        hypothesis_holds=(pl.col("accuracy_kept") >= 0.9) & (pl.col("tokens_used") <= 0.5)
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m cascade.sweep")
    ap.add_argument("--runs", type=Path, default=Path("data/runs/runs.parquet"))
    ap.add_argument("--out", type=Path, default=Path("paper/figures"))
    ap.add_argument("--condition", default="combined")
    ap.add_argument("--perturb", default="p0")
    ap.add_argument("--tier", action="append", default=[], help="TIER=MODEL_ID, e.g. A=tiny-q4")
    args = ap.parse_args(argv)
    tier_models = dict(t.split("=", 1) for t in args.tier) or None
    answers = select(pl.read_parquet(args.runs), tier_models, args.condition, args.perturb)
    args.out.mkdir(parents=True, exist_ok=True)
    table = rq4(sweep(answers), single_tiers(answers))
    table.write_csv(args.out / "cascade_sweep.csv")
    single_tiers(answers).write_csv(args.out / "cascade_tiers.csv")
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
