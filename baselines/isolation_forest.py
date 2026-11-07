"""Isolation Forest baseline (RQ6): unsupervised, service only.

For each fault snapshot, a forest fit on every service row of the *other*
snapshots scores this snapshot's services; the most anomalous one is the
predicted root cause. It predicts no category and does not decide whether a
snapshot is healthy, so it is reported as service accuracy on fault
snapshots only, never as top-1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl
from sklearn.ensemble import IsolationForest

from baselines.features import FEATURES
from rootline_harness.scorers import Label

SEED = 20261107


@dataclass(frozen=True)
class ServicePrediction:
    incident_id: str
    service: str
    service_ok: bool


def evaluate(feats: pl.DataFrame, labels: dict[str, Label]) -> list[ServicePrediction]:
    out = []
    for inc in sorted(set(feats["incident_id"])):
        if labels[inc].healthy:
            continue
        train = feats.filter(pl.col("incident_id") != inc)
        test = feats.filter(pl.col("incident_id") == inc)
        if train.height < 2 or test.is_empty():
            continue
        forest = IsolationForest(n_estimators=200, random_state=SEED).fit(
            train.select(FEATURES).to_numpy().astype(np.float64)
        )
        # score_samples: lower = more anomalous.
        scores = forest.score_samples(test.select(FEATURES).to_numpy().astype(np.float64))
        ranked = test.with_columns(score=pl.Series(scores)).sort(["score", "service"])
        svc = ranked["service"][0]
        out.append(ServicePrediction(inc, svc, svc == labels[inc].service))
    return out
