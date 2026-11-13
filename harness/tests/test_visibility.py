import json

import polars as pl

from analysis.visibility import snapshot_visibility, visibility
from tests.synth import LABEL, write_snapshot


def test_app_fault_shows_on_its_service(tmp_path) -> None:
    snap = write_snapshot(tmp_path / "snapshots" / "paymentFailure-r1")
    row = snapshot_visibility(snap, LABEL)
    assert row["measured"] == "payment spans"
    assert row["error_rate_before"] == 0
    assert float(row["error_rate_after"]) > 0.3  # type: ignore[arg-type]  # about half fail


def test_healthy_control_is_measured_on_checkout_to_payment(tmp_path) -> None:
    snap = write_snapshot(tmp_path / "snapshots" / "healthy-r1", "healthy-r1", faulty=None)
    label = {**LABEL, "fault": "healthy", "service": "none", "layer": "none", "edge": None}
    row = snapshot_visibility(snap, label)
    assert row["measured"] == "checkout calls to payment"
    assert row["error_rate_after"] == 0


def test_visibility_table_covers_labelled_snapshots(tmp_path) -> None:
    write_snapshot(tmp_path / "snapshots" / "paymentFailure-r1")
    write_snapshot(tmp_path / "snapshots" / "unlabelled-r1", "unlabelled-r1")
    (tmp_path / "labels").mkdir()
    (tmp_path / "labels" / "paymentFailure-r1.json").write_text(json.dumps(LABEL))
    df = visibility(tmp_path)
    assert isinstance(df, pl.DataFrame) and df["incident_id"].to_list() == ["paymentFailure-r1"]
