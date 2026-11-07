"""LightGBM baseline with two cross-validation schemes (RQ6).

Two models, both trained only on the training folds:
  1. a service ranker: binary classifier over (snapshot, service) rows,
     target = "this service is the root cause";
  2. a category classifier over the root service's features, trained on
     fault snapshots only.
A snapshot is called healthy when the ranker gives no service a root-cause
probability of 0.5; otherwise the prediction is (top service, category).
Scored like the LLMs: healthy is right only when called healthy.

Schemes:
  unseen: leave-one-fault-type-out, so the held-out fault type was never
          seen in training (healthy controls form their own group);
  seen:   leave-one-replica-out, so every fault type appears in training.
RQ6 expects the best LLM to beat this on unseen faults but not on seen ones.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import polars as pl
from lightgbm import LGBMClassifier

from baselines.features import FEATURES
from rootline_harness.scorers import Label

SEED = 20261107
# A snapshot is called healthy when no service's root-cause probability
# reaches this.
HEALTHY_BELOW = 0.5
PARAMS = {
    "n_estimators": 100,
    "learning_rate": 0.1,
    "num_leaves": 7,
    "min_child_samples": 2,
    "random_state": SEED,
    "deterministic": True,
    "force_col_wise": True,
    "n_jobs": 1,
    "verbose": -1,
}


@dataclass(frozen=True)
class Prediction:
    incident_id: str
    scheme: str
    service: str | None  # None = predicted healthy
    category: str
    top1: bool
    service_ok: bool


def fault_type(incident_id: str) -> str:
    return incident_id.rsplit("-r", 1)[0]


def replica(incident_id: str) -> str:
    return incident_id.rsplit("-r", 1)[1]


SCHEMES: dict[str, Callable[[str], str]] = {"unseen": fault_type, "seen": replica}


def _xy(feats: pl.DataFrame) -> np.ndarray:
    return feats.select(FEATURES).to_numpy().astype(np.float64)


def _fit_predict_fold(
    train: pl.DataFrame, test: pl.DataFrame, labels: dict[str, Label]
) -> list[tuple[str, str | None, str]]:
    """Return (incident, predicted service or None, predicted category)."""
    y_rank = np.array(
        [
            labels[i].service == s
            for i, s in zip(train["incident_id"], train["service"], strict=True)
        ],
        dtype=int,
    )
    ranker = None
    if 0 < y_rank.sum() < len(y_rank):
        ranker = LGBMClassifier(**PARAMS).fit(_xy(train), y_rank)

    def top_rows(df: pl.DataFrame) -> pl.DataFrame:
        score = (
            np.asarray(ranker.predict_proba(_xy(df)))[:, 1]
            if ranker is not None
            else np.zeros(df.height)
        )
        return (
            df.with_columns(score=pl.Series(score))
            .sort(["incident_id", "score", "service"], descending=[False, True, False])
            .group_by("incident_id", maintain_order=True)
            .first()
        )

    # Category model: fault snapshots only, trained on the true root
    # service's row, so it learns what each failure looks like. Healthy is
    # decided by the ranker instead: with two healthy runs in the pilot, a
    # "none" class would have one training example per fold.
    cat_rows, cat_y = [], []
    for inc in sorted(set(train["incident_id"])):
        lbl = labels[inc]
        if lbl.healthy:
            continue
        r = train.filter((pl.col("incident_id") == inc) & (pl.col("service") == lbl.service))
        if r.height:
            cat_rows.append(r.select(FEATURES))
            cat_y.append(lbl.category)
    classes = sorted(set(cat_y)) or ["none"]
    cat_model = None
    if len(classes) > 1:
        cat_model = LGBMClassifier(**PARAMS).fit(
            pl.concat(cat_rows).to_numpy(), np.array([classes.index(c) for c in cat_y])
        )

    out = []
    for r in top_rows(test).iter_rows(named=True):
        if ranker is None or r["score"] < HEALTHY_BELOW:
            # No service looks like a root cause: call it healthy.
            out.append((r["incident_id"], None, "none"))
            continue
        x = np.array([[r[f] for f in FEATURES]], dtype=np.float64)
        category = classes[int(np.asarray(cat_model.predict(x))[0])] if cat_model else classes[0]
        out.append((r["incident_id"], r["service"], category))
    return out


def evaluate(feats: pl.DataFrame, labels: dict[str, Label], scheme: str) -> list[Prediction]:
    group_of = SCHEMES[scheme]
    incidents = sorted(set(feats["incident_id"]))
    groups = sorted({group_of(i) for i in incidents})
    preds: list[Prediction] = []
    for g in groups:
        test_ids = [i for i in incidents if group_of(i) == g]
        train = feats.filter(~pl.col("incident_id").is_in(test_ids))
        test = feats.filter(pl.col("incident_id").is_in(test_ids))
        if train.is_empty():
            continue
        for inc, svc, cat in _fit_predict_fold(train, test, labels):
            lbl = labels[inc]
            if lbl.healthy:
                top1 = svc is None
                service_ok = svc is None
            else:
                top1 = svc == lbl.service and cat == lbl.category
                service_ok = svc == lbl.service
            preds.append(Prediction(inc, scheme, svc, cat, top1, service_ok))
    return preds
