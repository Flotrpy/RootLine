import json
import shutil

from analysis.site_data import service_graph, write_site_data
from rootline_harness.packers import load_snapshot
from tests.synth import LABEL
from tests.test_analysis import RUNS


def test_service_graph(snapshot_dir) -> None:
    g = service_graph(load_snapshot(snapshot_dir))
    edges = {(e["source"], e["target"]): e for e in g["edges"]}  # type: ignore[union-attr]
    assert ("checkout", "payment") in edges
    assert ("frontend", "product-catalog") in edges
    assert edges[("checkout", "payment")]["errors"] > 0
    assert edges[("frontend", "product-catalog")]["errors"] == 0
    ids = {n["id"] for n in g["nodes"]}  # type: ignore[union-attr]
    assert {"frontend-proxy", "payment"} <= ids


def _repo(tmp_path, snapshot_dir, with_runs: bool):
    (tmp_path / "data" / "snapshots").mkdir(parents=True)
    shutil.copytree(snapshot_dir, tmp_path / "data" / "snapshots" / "paymentFailure-r1")
    (tmp_path / "data" / "labels").mkdir()
    (tmp_path / "data" / "labels" / "paymentFailure-r1.json").write_text(json.dumps(LABEL))
    if with_runs:
        (tmp_path / "data" / "runs").mkdir()
        RUNS.write_parquet(tmp_path / "data" / "runs" / "runs.parquet")
    return tmp_path


def test_site_data_without_labels_or_runs(tmp_path, snapshot_dir) -> None:
    root = _repo(tmp_path, snapshot_dir, with_runs=False)
    out = root / "web" / "public" / "data"
    site = write_site_data(root, out)
    assert site == {
        "labels_included": False,
        "n_snapshots": 1,
        "has_runs": False,
        "best_model": None,
        "label": "pilot (n=1 snapshots)",
    }
    incidents = json.loads((out / "incidents.json").read_text())
    assert incidents == [{"id": "paymentFailure-r1"}]
    assert (out / "incidents" / "paymentFailure-r1" / "combined-p0.json").exists()
    assert not (out / "summary.json").exists()
    # Nothing written for the site may carry the label's category or flag.
    blob = "".join(p.read_text() for p in out.rglob("*.json"))
    assert '"category": "error"' not in blob and '"flag"' not in blob


def test_site_data_with_labels(tmp_path, snapshot_dir) -> None:
    root = _repo(tmp_path, snapshot_dir, with_runs=False)
    out = root / "site"
    write_site_data(root, out, include_labels=True)
    incidents = json.loads((out / "incidents.json").read_text())
    assert incidents[0]["label"]["service"] == "payment"


def test_site_data_skips_summary_when_runs_lack_labels(tmp_path, snapshot_dir) -> None:
    root = _repo(tmp_path, snapshot_dir, with_runs=True)
    site = write_site_data(root, root / "site")
    assert site["has_runs"] and site["best_model"] == "big"
    assert (root / "site" / "runs.parquet").exists()
    # RUNS' incidents have no label files here, so no summary is computed.
    assert not (root / "site" / "summary.json").exists()
