"""Final release gate: is everything the v0.1 release needs actually there?

    make release-check

Prints one line per check (PASS, FAIL or WARN) and exits non-zero on any
FAIL. It reads only local files and git; it changes nothing.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from rootline_harness.catalog import FAULTS, HW_FAULTS

PILOT_REPLICAS = 2
HW_REPLICAS = 4
CONDITIONS = ("metrics", "traces", "logs", "combined")
REMEDIATION_TRIALS = len(FAULTS)
MAX_FILE_BYTES = 5 * 1024 * 1024


@dataclass
class Check:
    name: str
    status: str  # PASS, FAIL or WARN
    detail: str = ""


def _snapshots(root: Path) -> dict[str, Path]:
    d = root / "data" / "snapshots"
    if not d.exists():
        return {}
    return {p.name: p for p in sorted(d.iterdir()) if (p / "manifest.json").exists()}


def check_snapshots(root: Path) -> list[Check]:
    snaps = _snapshots(root)
    out = []
    for name, faults, replicas in (
        ("pilot snapshots", FAULTS, PILOT_REPLICAS),
        ("hardware snapshots", HW_FAULTS, HW_REPLICAS),
    ):
        want = {f"{f}-r{r}" for f in faults for r in range(1, replicas + 1)}
        missing = sorted(want - set(snaps))
        out.append(
            Check(
                name,
                "FAIL" if missing else "PASS",
                f"{len(want) - len(missing)}/{len(want)}"
                + (f"; missing e.g. {missing[:3]}" if missing else ""),
            )
        )
    broken = [
        n
        for n, p in snaps.items()
        if not all((p / f"{s}.parquet").exists() for s in ("spans", "metrics", "logs"))
    ]
    out.append(
        Check(
            "snapshot files complete",
            "FAIL" if broken else "PASS",
            f"incomplete: {broken[:3]}" if broken else f"{len(snaps)} checked",
        )
    )
    unpinned = []
    for n, p in snaps.items():
        m = json.loads((p / "manifest.json").read_text())
        if not m.get("demo_git_tag") or not m.get("image_digests"):
            unpinned.append(n)
    out.append(
        Check(
            "manifests pin demo tag and image digests",
            "FAIL" if unpinned else "PASS",
            f"unpinned: {unpinned[:3]}" if unpinned else "",
        )
    )
    labels = root / "data" / "labels"
    no_label = [n for n in snaps if not (labels / f"{n}.json").exists()]
    out.append(
        Check(
            "every snapshot has a label",
            "FAIL" if no_label else "PASS",
            f"missing: {no_label[:3]}" if no_label else "",
        )
    )
    return out


def check_runs(root: Path) -> list[Check]:
    path = root / "data" / "runs" / "runs.parquet"
    if not path.exists():
        return [Check("model runs exported", "FAIL", f"no {path.relative_to(root)}")]
    runs = pl.read_parquet(path)
    out = [
        Check(
            "model runs exported",
            "PASS",
            f"{runs.height} runs, {runs['model_id'].n_unique()} models",
        )
    ]
    snaps = set(_snapshots(root))
    gaps = []
    for model in sorted(runs["model_id"].unique().to_list()):
        have = set(
            runs.filter((pl.col("model_id") == model) & (pl.col("perturbation") == "p0"))
            .select(pl.concat_str("incident_id", pl.lit("|"), "condition"))
            .to_series()
            .to_list()
        )
        want = {f"{s}|{c}" for s in snaps for c in CONDITIONS}
        if want - have:
            gaps.append(f"{model}: {len(want - have)} missing")
    out.append(
        Check(
            "every model ran every snapshot x condition",
            "FAIL" if gaps else "PASS",
            "; ".join(gaps[:3]),
        )
    )
    p1 = runs.filter(pl.col("perturbation") == "p1")
    out.append(
        Check("P1 (anonymised) runs present", "PASS" if p1.height else "FAIL", f"{p1.height} runs")
    )
    tiers = sorted(runs["tier"].unique().to_list())
    out.append(
        Check(
            "all three cascade tiers ran",
            "PASS" if tiers == ["A", "B", "C"] else "FAIL",
            f"tiers: {tiers}",
        )
    )
    invalid = runs.filter(~pl.col("parsed_ok")).height / runs.height if runs.height else 0.0
    out.append(Check("invalid-output rate recorded", "PASS", f"{invalid:.1%}"))
    return out


def check_remediation(root: Path) -> list[Check]:
    path = root / "data" / "runs" / "remediation.jsonl"
    n = len(path.read_text().splitlines()) if path.exists() else 0
    # RQ5 is held for v0.2, so missing trials do not block v0.1.
    return [
        Check(
            "remediation trials (v0.2)",
            "PASS" if n >= REMEDIATION_TRIALS else "WARN",
            f"{n}/{REMEDIATION_TRIALS}" + ("" if n >= REMEDIATION_TRIALS else ", RQ5 is v0.2"),
        )
    ]


def check_results(root: Path) -> list[Check]:
    res = root / "paper" / "figures" / "results.json"
    runs = root / "data" / "runs" / "runs.parquet"
    if not res.exists():
        return [Check("results regenerated (make reproduce)", "FAIL", "no results.json")]
    stale = runs.exists() and runs.stat().st_mtime > res.stat().st_mtime
    out = [
        Check(
            "results regenerated (make reproduce)",
            "FAIL" if stale else "PASS",
            "older than runs.parquet" if stale else "",
        )
    ]
    data = json.loads(res.read_text())
    not_run = [
        h["rq"]
        for h in data.get("hypotheses", [])
        if h["status"] not in ("tested", "deferred to v0.2")
    ]
    out.append(
        Check(
            "in-scope hypotheses (RQ1, RQ2) tested",
            "WARN" if not_run else "PASS",
            f"not run: {not_run}" if not_run else "",
        )
    )
    return out


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True).stdout


def check_git(root: Path) -> list[Check]:
    tracked = _git(root, "ls-files").splitlines()
    big = [
        f for f in tracked if (root / f).is_file() and (root / f).stat().st_size > MAX_FILE_BYTES
    ]
    leaked = [
        f
        for f in tracked
        if re.match(r"data/(labels|runs|holdout)/.+", f) and not f.endswith(".gitkeep")
    ]
    authors = set(_git(root, "log", "--no-merges", "--format=%an").split("\n")) - {""}
    trailers = re.search(
        r"(?im)^(co-authored-by:|generated with)", _git(root, "log", "--format=%B")
    )
    return [
        Check("no tracked file over 5 MB", "FAIL" if big else "PASS", ", ".join(big[:3])),
        Check(
            "labels, runs and holdout not in git",
            "FAIL" if leaked else "PASS",
            ", ".join(leaked[:3]),
        ),
        Check(
            "all commits authored by flotrpy",
            "PASS" if authors == {"flotrpy"} else "FAIL",
            f"authors: {sorted(authors)}",
        ),
        Check("no attribution trailers", "FAIL" if trailers else "PASS"),
    ]


def check_todos(root: Path) -> list[Check]:
    hits = _git(root, "grep", "-c", "TODO(flotrpy)", "--", ".", ":!docs/BUILD_PROMPT.md")
    files = [line for line in hits.splitlines() if line]
    total = sum(int(line.rsplit(":", 1)[1]) for line in files)
    return [
        Check(
            "open TODO(flotrpy) decisions",
            "WARN" if total else "PASS",
            f"{total} in {len(files)} files" if total else "",
        )
    ]


def run_all(root: Path) -> list[Check]:
    checks: list[Check] = []
    for fn in (
        check_snapshots,
        check_runs,
        check_remediation,
        check_results,
        check_git,
        check_todos,
    ):
        checks += fn(root)
    return checks


def report(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = [f"{c.status:<4}  {c.name:<{width}}  {c.detail}".rstrip() for c in checks]
    fails = sum(c.status == "FAIL" for c in checks)
    warns = sum(c.status == "WARN" for c in checks)
    lines.append(f"\n{fails} failed, {warns} warnings, {len(checks) - fails - warns} passed")
    return "\n".join(lines)
