"""Release dataset packaging and the release gate."""

import json
import shutil
import subprocess

import polars as pl

from analysis.dataset import package, verify_sums, write_sums
from analysis.release_check import report, run_all
from rootline_harness.catalog import FAULTS, HW_FAULTS
from rootline_harness.runner import RUN_COLUMNS
from tests.synth import write_snapshot


def test_package_and_verify(tmp_path, snapshot_dir) -> None:
    data = tmp_path / "data"
    shutil.copytree(snapshot_dir, data / "snapshots" / "paymentFailure-r1")
    (data / "labels").mkdir()
    (data / "labels" / "paymentFailure-r1.json").write_text("{}")
    (data / "holdout").mkdir()
    (data / "holdout" / "secret.json").write_text("{}")
    out = tmp_path / "dist"
    counts = package(data, out)
    assert counts == {"snapshots": 1, "labels": 1}
    assert (out / "README.md").read_text().startswith("---\nlicense: cc-by-4.0")
    assert not (out / "holdout").exists()
    assert verify_sums(out) == []
    (out / "labels" / "paymentFailure-r1.json").write_text('{"tampered": true}')
    assert verify_sums(out) == ["labels/paymentFailure-r1.json"]


def test_sums_skip_themselves(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x")
    sums = write_sums(tmp_path).read_text()
    assert "a.txt" in sums and "SHA256SUMS" not in sums


def _git_repo(root) -> None:
    def git(*a: str) -> None:
        subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.name", "flotrpy")
    git("config", "user.email", "flotrpy@users.noreply.github.com")
    git("config", "commit.gpgsign", "false")
    (root / "README.md").write_text("x")
    git("add", "README.md")
    git("commit", "-q", "-m", "chore(ci): start")


def test_release_check_on_empty_repo_fails_clearly(tmp_path) -> None:
    _git_repo(tmp_path)
    checks = {c.name: c for c in run_all(tmp_path)}
    assert checks["pilot snapshots"].status == "FAIL"
    assert checks["model runs exported"].status == "FAIL"
    assert checks["all commits authored by flotrpy"].status == "PASS"
    assert "failed" in report(list(checks.values()))


def test_release_check_passes_on_complete_data(tmp_path, snapshot_dir) -> None:
    _git_repo(tmp_path)
    data = tmp_path / "data"
    ids = [f"{f}-r{r}" for f in FAULTS for r in (1, 2)] + [
        f"{f}-r{r}" for f in HW_FAULTS for r in (1, 2, 3, 4)
    ]
    (data / "labels").mkdir(parents=True)
    for i in ids:
        d = data / "snapshots" / i
        shutil.copytree(snapshot_dir, d)
        m = json.loads((d / "manifest.json").read_text())
        m.update(incident_id=i, demo_git_tag="2.1.3", image_digests={"img": "sha256:x"})
        (d / "manifest.json").write_text(json.dumps(m))
        (data / "labels" / f"{i}.json").write_text("{}")
    rows = []
    for tier in ("A", "B", "C"):
        for i in ids:
            for cond in ("metrics", "traces", "logs", "combined"):
                for pert in ("p0", "p1") if cond == "combined" else ("p0",):
                    r: dict[str, object] = {c: None for c in RUN_COLUMNS}
                    r.update(
                        incident_id=i,
                        condition=cond,
                        perturbation=pert,
                        model_id=f"m{tier}",
                        tier=tier,
                        parsed_ok=True,
                    )
                    rows.append(r)
    (data / "runs").mkdir()
    pl.DataFrame(rows, infer_schema_length=None).write_parquet(data / "runs" / "runs.parquet")
    (data / "runs" / "remediation.jsonl").write_text("{}\n" * 15)
    figs = tmp_path / "paper" / "figures"
    figs.mkdir(parents=True)
    (figs / "results.json").write_text(
        json.dumps({"hypotheses": [{"rq": "RQ1", "status": "tested"}]})
    )
    checks = run_all(tmp_path)
    fails = [c for c in checks if c.status == "FAIL"]
    assert not fails, report(checks)


def test_release_check_flags_unpinned_manifest(tmp_path) -> None:
    _git_repo(tmp_path)
    write_snapshot(tmp_path / "data" / "snapshots" / "paymentFailure-r1")
    checks = {c.name: c for c in run_all(tmp_path)}
    assert checks["manifests pin demo tag and image digests"].status == "FAIL"
    assert checks["every snapshot has a label"].status == "FAIL"
