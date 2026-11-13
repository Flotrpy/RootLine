import json
from pathlib import Path

import polars as pl
import pytest

from baselines import isolation_forest, lightgbm_lofo
from baselines.__main__ import load, run
from baselines.features import FEATURES, service_features
from rootline_harness.packers import load_snapshot
from tests.synth import write_snapshot

# Synthetic campaign: three fault types x 2 replicas + healthy x 2.
FAULTS = {
    "paymentFailure": ("payment", "error"),
    "productCatalogFailure": ("product-catalog", "error"),
    "checkoutBroken": ("checkout", "error"),
}


@pytest.fixture(scope="module")
def campaign(tmp_path_factory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("campaign")
    snaps, labels = root / "snapshots", root / "labels"
    labels.mkdir()
    seed = 0
    for fault, (svc, cat) in FAULTS.items():
        for r in (1, 2):
            seed += 1
            inc = f"{fault}-r{r}"
            write_snapshot(snaps / inc, inc, seed=seed, faulty=svc)
            (labels / f"{inc}.json").write_text(
                json.dumps(
                    {
                        "fault": fault,
                        "service": svc,
                        "category": cat,
                        "layer": "application",
                        "edge": None,
                        "flag": None,
                        "variant": None,
                    }
                )
            )
    for r in (1, 2):
        inc = f"healthy-r{r}"
        write_snapshot(snaps / inc, inc, seed=100 + r, faulty=None)
        (labels / f"{inc}.json").write_text(
            json.dumps(
                {
                    "fault": "healthy",
                    "service": "none",
                    "category": "none",
                    "layer": "none",
                    "edge": None,
                    "flag": None,
                    "variant": None,
                }
            )
        )
    return snaps, labels


def test_features_single_out_the_faulty_service(campaign) -> None:
    snaps, _ = campaign
    df = service_features(load_snapshot(snaps / "paymentFailure-r1"))
    assert set(FEATURES) <= set(df.columns)
    pay = df.filter(pl.col("service") == "payment").row(0, named=True)
    cat = df.filter(pl.col("service") == "product-catalog").row(0, named=True)
    assert pay["error_ratio_delta"] > 0.3 > abs(cat["error_ratio_delta"])
    assert pay["span_duration_log_ratio"] > 1
    assert pay["log_error_rate_log_ratio"] > 1


def test_healthy_features_are_flat(campaign) -> None:
    snaps, _ = campaign
    df = service_features(load_snapshot(snaps / "healthy-r1"))
    assert df["error_ratio_delta"].abs().max() < 0.05  # type: ignore[operator]


def test_lightgbm_seen_scheme_learns_the_pattern(campaign) -> None:
    feats, labels = load(*campaign)
    preds = lightgbm_lofo.evaluate(feats, labels, "seen")
    assert len(preds) == 8
    # Every fault type is in training; the synthetic signal is strong.
    assert sum(p.service_ok for p in preds) >= 6
    healthy = [p for p in preds if p.incident_id.startswith("healthy")]
    assert all(p.service is None and p.top1 for p in healthy)


def test_lightgbm_unseen_scheme_holds_out_fault_types(campaign) -> None:
    feats, labels = load(*campaign)
    preds = lightgbm_lofo.evaluate(feats, labels, "unseen")
    assert {lightgbm_lofo.fault_type(p.incident_id) for p in preds} == set(FAULTS) | {"healthy"}
    # Deterministic: same input, same predictions.
    assert preds == lightgbm_lofo.evaluate(feats, labels, "unseen")


def test_isolation_forest_service_only(campaign) -> None:
    feats, labels = load(*campaign)
    preds = isolation_forest.evaluate(feats, labels)
    assert len(preds) == 6  # fault snapshots only
    assert sum(p.service_ok for p in preds) >= 4


def test_cli_writes_summary(campaign, tmp_path) -> None:
    snaps, labels = campaign
    summary = run(snaps, labels, tmp_path)
    assert (tmp_path / "baselines.csv").exists()
    preds = pl.read_parquet(tmp_path / "baseline_predictions.parquet")
    assert set(preds["model"]) == {"lightgbm", "isolation_forest"}
    iso = summary.filter(pl.col("model") == "isolation_forest").row(0, named=True)
    assert iso["top1"] is None and iso["n"] == 6
