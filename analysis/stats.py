"""Statistics for the paper: McNemar's exact test for paired comparisons on
the same snapshots, percentile bootstrap confidence intervals, and Holm's
correction across the research questions.

Seeds are fixed and recorded with every result so reruns are identical.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

BOOTSTRAP_RESAMPLES = 10_000
SEED = 20261107


@dataclass(frozen=True)
class McNemar:
    b: int  # A right, B wrong
    c: int  # A wrong, B right
    p_value: float


def mcnemar(a: Sequence[bool], b: Sequence[bool]) -> McNemar:
    """Exact two-sided McNemar test on paired outcomes.

    Uses the binomial distribution on the discordant pairs, which is right
    for the small pilot (n=30) where the chi-square approximation is not.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    n01 = sum(1 for x, y in zip(a, b, strict=True) if x and not y)
    n10 = sum(1 for x, y in zip(a, b, strict=True) if y and not x)
    n = n01 + n10
    if n == 0:
        return McNemar(n01, n10, 1.0)
    k = min(n01, n10)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return McNemar(n01, n10, min(1.0, 2 * tail))


@dataclass(frozen=True)
class Interval:
    estimate: float
    low: float
    high: float
    resamples: int
    seed: int


def bootstrap_mean(
    values: Sequence[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = SEED,
    level: float = 0.95,
) -> Interval:
    """Percentile bootstrap CI for a mean (e.g. accuracy over snapshots)."""
    if not values:
        return Interval(math.nan, math.nan, math.nan, resamples, seed)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    alpha = (1 - level) / 2
    lo = means[math.floor(alpha * (resamples - 1))]
    hi = means[math.ceil((1 - alpha) * (resamples - 1))]
    return Interval(sum(values) / n, lo, hi, resamples, seed)


def bootstrap_diff(
    a: Sequence[float],
    b: Sequence[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = SEED,
    level: float = 0.95,
) -> Interval:
    """Paired bootstrap CI for mean(a) - mean(b), resampling snapshots."""
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    if not a:
        return Interval(math.nan, math.nan, math.nan, resamples, seed)
    rng = random.Random(seed)
    n = len(a)
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    alpha = (1 - level) / 2
    lo = means[math.floor(alpha * (resamples - 1))]
    hi = means[math.ceil((1 - alpha) * (resamples - 1))]
    return Interval(sum(diffs) / n, lo, hi, resamples, seed)


def holm(p_values: Sequence[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, in the input order."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p_values[i])
        adjusted[i] = min(1.0, running)
    return adjusted
