"""Calibration of stated confidence: Brier score and expected calibration
error over 10 equal-width bins."""

from __future__ import annotations

from collections.abc import Sequence

N_BINS = 10


def _check(conf: Sequence[float], correct: Sequence[bool]) -> None:
    if len(conf) != len(correct):
        raise ValueError("confidence and correctness lengths differ")
    if any(not 0.0 <= c <= 1.0 for c in conf):
        raise ValueError("confidence must be in [0, 1]")


def brier(conf: Sequence[float], correct: Sequence[bool]) -> float:
    _check(conf, correct)
    if not conf:
        return float("nan")
    return sum((c - float(y)) ** 2 for c, y in zip(conf, correct, strict=True)) / len(conf)


def ece(conf: Sequence[float], correct: Sequence[bool], n_bins: int = N_BINS) -> float:
    """Expected calibration error. Bin i holds [i/n, (i+1)/n); a confidence
    of exactly 1.0 goes in the last bin."""
    _check(conf, correct)
    if not conf:
        return float("nan")
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for c, y in zip(conf, correct, strict=True):
        bins[min(int(c * n_bins), n_bins - 1)].append((c, y))
    total = len(conf)
    err = 0.0
    for b in bins:
        if b:
            mean_conf = sum(c for c, _ in b) / len(b)
            acc = sum(1 for _, y in b if y) / len(b)
            err += len(b) / total * abs(acc - mean_conf)
    return err
