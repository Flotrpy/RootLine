"""Pack export, and the fixture the Rust replay CLI's golden test reads.

The fixture is generated from the synthetic snapshot. This test fails if
the Python packer's output changes without the fixture being regenerated:

    ROOTLINE_UPDATE_FIXTURES=1 uv run pytest tests/test_export_packs.py
"""

import json
import os
from pathlib import Path

from rootline_harness.catalog import forbidden_strings
from rootline_harness.export_packs import dumps, export, main, pack_document
from rootline_harness.packers import Snapshot
from rootline_harness.prompt import build_prompt

FIXTURES = Path(__file__).parents[2] / "replay" / "tests" / "fixtures"
CASES = [("combined", "p0"), ("logs", "p1")]


def test_export_writes_every_condition(snapshot_dir, tmp_path) -> None:
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    (snaps / "paymentFailure-r1").symlink_to(snapshot_dir)
    assert export(snaps, tmp_path / "packs") == 8
    doc = json.loads((tmp_path / "packs" / "paymentFailure-r1" / "traces-p1.json").read_text())
    assert doc["perturbation"] == "p1" and doc["format"] == 1
    assert "mapping" not in doc
    # The incident ID names the fault, so it may sit in file metadata but
    # must never reach what the model reads.
    seen_by_model = (doc["prompt"] + doc["rendered"]).lower()
    assert "paymentfailure-r1" not in seen_by_model
    for s in forbidden_strings():
        assert s.lower() not in seen_by_model


def test_cli(snapshot_dir, tmp_path, capsys) -> None:
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    (snaps / "x-r1").symlink_to(snapshot_dir)
    assert main(["--snapshots", str(snaps), "--out", str(tmp_path / "out")]) == 0
    assert "wrote 8 packs" in capsys.readouterr().out


def test_rust_fixture_is_current(snapshot: Snapshot) -> None:
    update = os.environ.get("ROOTLINE_UPDATE_FIXTURES") == "1"
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for cond, pert in CASES:
        doc = pack_document(build_prompt(snapshot, cond, pert))  # type: ignore[arg-type]
        files = {
            f"{cond}-{pert}.json": dumps(doc),
            f"{cond}-{pert}.expected.txt": str(doc["rendered"]) + "\n",
        }
        for name, content in files.items():
            path = FIXTURES / name
            if update:
                path.write_text(content)
            assert path.exists(), f"missing {path}; run with ROOTLINE_UPDATE_FIXTURES=1"
            assert path.read_text() == content, f"{name} is stale; regenerate the fixture"
