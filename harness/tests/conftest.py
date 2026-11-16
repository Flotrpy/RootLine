from pathlib import Path

import pytest

from rootline_harness.packers import Snapshot, load_snapshot
from tests.synth import write_snapshot


@pytest.fixture(scope="session")
def snapshot_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_snapshot(tmp_path_factory.mktemp("snap") / "paymentFailure-r1")


@pytest.fixture(scope="session")
def snapshot(snapshot_dir: Path) -> Snapshot:
    return load_snapshot(snapshot_dir)
