"""The technical report must compile from reproduce's output alone."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from analysis.__main__ import reproduce
from tests.test_analysis import LABELS, RUNS

PAPER = Path(__file__).parents[2] / "paper" / "main.typ"


@pytest.mark.skipif(shutil.which("typst") is None, reason="typst is not installed")
def test_report_compiles_from_results(tmp_path) -> None:
    (tmp_path / "data" / "runs").mkdir(parents=True)
    (tmp_path / "data" / "labels").mkdir()
    RUNS.write_parquet(tmp_path / "data" / "runs" / "runs.parquet")
    for inc, lbl in LABELS.items():
        (tmp_path / "data" / "labels" / f"{inc}.json").write_text(
            json.dumps(
                {
                    "fault": lbl.fault,
                    "service": lbl.service,
                    "category": lbl.category,
                    "layer": lbl.layer,
                    "edge": lbl.edge,
                    "flag": None,
                    "variant": None,
                }
            )
        )
    paper = tmp_path / "paper"
    reproduce(tmp_path, paper / "figures")
    shutil.copy(PAPER, paper / "main.typ")
    out = subprocess.run(
        ["typst", "compile", "main.typ", "report.pdf"], cwd=paper, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert (paper / "report.pdf").stat().st_size > 10_000


def test_report_types_no_numbers_by_hand() -> None:
    """Results in the report must come from results.json, not the source."""
    src = PAPER.read_text()
    body = src.split("= Results", 1)[1].split("= Limitations", 1)[0]
    import re

    # Layout widths ("width: 90%") and the confidence level ("95% CI") are
    # settings, not results.
    typed = re.findall(
        r"(?<!width: )(?<![\d.])\d+(?:\.\d+)?%(?!\s*(?:CI|bootstrap|confidence))", body
    )
    assert not typed, f"percentages typed into the results: {typed}"
