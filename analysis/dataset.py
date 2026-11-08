"""Package the release dataset for Hugging Face, and fetch it back.

    uv run --project harness python -m analysis package-dataset
    uv run --project harness python -m analysis fetch-data      # = make data

package-dataset only builds dist/rootline-v0.1-data/ with a dataset card and
SHA256SUMS; publishing it is flotrpy's step (see docs/RELEASE.md). The
private holdout never goes in.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

DATASET_REPO = os.environ.get("ROOTLINE_HF_DATASET", "flotrpy/rootline")
# TODO(flotrpy): confirm the Hugging Face dataset id before publishing.

CARD = """---
license: cc-by-4.0
pretty_name: Rootline v0.1 pilot
tags:
  - observability
  - opentelemetry
  - root-cause-analysis
  - llm-evaluation
size_categories:
  - n<1K
---

# Rootline v0.1 pilot dataset

Frozen telemetry from the OpenTelemetry Demo around injected faults, with
ground-truth labels, every model run, and live remediation trials.
Code: https://github.com/Flotrpy/RootLine (Apache-2.0). Data: CC BY 4.0.

| Path | Contents |
|------|----------|
| `snapshots/<incident>/` | `spans.parquet`, `metrics.parquet`, `logs.parquet`, `manifest.json` |
| `labels/<incident>.json` | ground truth: fault, service, category, layer, edge |
| `runs/runs.parquet` | one row per model run (prompt, raw output, scores) |
| `runs/remediation.jsonl` | live remediation trials |
| `hw/` | hardware arm: operator log and Wi-Fi logs |

Schemas are in `docs/DATA.md` in the code repository. Results are a pilot:
two replicas per incident type give wide confidence intervals.

Reproduce every table and figure: clone the code, run `make data`, then
`make reproduce`. Integrity: `SHA256SUMS`.
"""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_sums(root: Path) -> Path:
    lines = [
        f"{_sha256(p)}  {p.relative_to(root).as_posix()}"
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "SHA256SUMS"
    ]
    out = root / "SHA256SUMS"
    out.write_text("\n".join(lines) + "\n")
    return out


def verify_sums(root: Path) -> list[str]:
    """Return the files whose checksum is missing or wrong (empty = all good)."""
    bad = []
    for line in (root / "SHA256SUMS").read_text().splitlines():
        digest, rel = line.split("  ", 1)
        p = root / rel
        if not p.is_file() or _sha256(p) != digest:
            bad.append(rel)
    return bad


def package(data: Path, out: Path) -> dict[str, int]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    counts = {"snapshots": 0, "labels": 0}
    for d in sorted((data / "snapshots").iterdir()) if (data / "snapshots").exists() else []:
        if (d / "manifest.json").exists():
            shutil.copytree(d, out / "snapshots" / d.name)
            counts["snapshots"] += 1
    for p in sorted((data / "labels").glob("*.json")) if (data / "labels").exists() else []:
        (out / "labels").mkdir(exist_ok=True)
        shutil.copy(p, out / "labels" / p.name)
        counts["labels"] += 1
    for name in ("runs.parquet", "remediation.jsonl"):
        src = data / "runs" / name
        if src.exists():
            (out / "runs").mkdir(exist_ok=True)
            shutil.copy(src, out / "runs" / name)
    if (data / "hw").exists():
        shutil.copytree(data / "hw", out / "hw")
    (out / "README.md").write_text(CARD)
    write_sums(out)
    return counts


def fetch(data: Path, repo: str = DATASET_REPO) -> None:
    """Download the published dataset into data/ and verify it."""
    from huggingface_hub import snapshot_download

    target = data / "_download"
    snapshot_download(repo_id=repo, repo_type="dataset", local_dir=target)
    bad = verify_sums(target)
    if bad:
        raise SystemExit(f"checksum mismatch for {len(bad)} files, e.g. {bad[:3]}")
    for sub in ("snapshots", "labels", "runs", "hw"):
        src = target / sub
        if src.exists():
            shutil.copytree(src, data / sub, dirs_exist_ok=True)
    shutil.rmtree(target)
