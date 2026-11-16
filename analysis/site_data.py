"""Write the static site's data files into web/public/data/.

    uv run --project harness python -m analysis site-data [--include-labels]

Every number on the site comes from these files, which come from data/ on
disk. Labels are left out unless --include-labels is passed, which is only
for the release build (labels stay private until results are published).
Incident IDs name the fault, so the site itself is only deployed at
release.
"""

from __future__ import annotations

import json
import math
import shutil
from collections import Counter
from pathlib import Path

import polars as pl

from analysis.tables import best_model, hypotheses, summary
from rootline_harness.packers import CONDITIONS, Snapshot, load_snapshot
from rootline_harness.prompt import build_prompt
from rootline_harness.scorers import Label

PERTURBATIONS = ("p0", "p1")


def _clean(v: object) -> object:
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _rows(df: pl.DataFrame) -> list[dict[str, object]]:
    return [{k: _clean(v) for k, v in r.items()} for r in df.to_dicts()]


def _write(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def service_graph(snap: Snapshot) -> dict[str, object]:
    """Caller -> callee service edges from span parent links in the window."""
    s = snap.spans
    parents = s.select(
        pl.col("trace_id"),
        pl.col("span_id").alias("parent_span_id"),
        pl.col("service").alias("caller"),
    )
    joined = s.join(parents, on=["trace_id", "parent_span_id"], how="inner").filter(
        pl.col("caller") != pl.col("service")
    )
    edges = (
        joined.with_columns(err=pl.col("status_code").str.contains("ERROR"))
        .group_by("caller", "service")
        .agg(calls=pl.len(), errors=pl.col("err").sum())
        .sort("caller", "service")
    )
    spans = Counter(s["service"].to_list())
    errors = Counter(s.filter(pl.col("status_code").str.contains("ERROR"))["service"].to_list())
    return {
        "nodes": [{"id": svc, "spans": spans[svc], "errors": errors[svc]} for svc in sorted(spans)],
        "edges": [
            {
                "source": r["caller"],
                "target": r["service"],
                "calls": r["calls"],
                "errors": r["errors"],
            }
            for r in edges.iter_rows(named=True)
        ],
    }


def write_site_data(root: Path, out: Path, include_labels: bool = False) -> dict[str, object]:
    snapshots_dir = root / "data" / "snapshots"
    labels_dir = root / "data" / "labels"
    runs_path = root / "data" / "runs" / "runs.parquet"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    labels = (
        {
            p.stem: Label.from_dict(json.loads(p.read_text()))
            for p in sorted(labels_dir.glob("*.json"))
        }
        if labels_dir.exists()
        else {}
    )

    snaps = (
        sorted(p for p in snapshots_dir.iterdir() if (p / "manifest.json").exists())
        if snapshots_dir.exists()
        else []
    )
    incidents = []
    for d in snaps:
        snap = load_snapshot(d)
        inc_dir = out / "incidents" / snap.incident_id
        _write(inc_dir / "graph.json", service_graph(snap))
        for cond in CONDITIONS:
            for pert in PERTURBATIONS:
                p = build_prompt(snap, cond, pert)  # type: ignore[arg-type]
                _write(
                    inc_dir / f"{cond}-{pert}.json",
                    {"prompt_tokens": p.tokens, "pack": json.loads(p.pack.to_json())},
                )
        entry: dict[str, object] = {"id": snap.incident_id}
        if include_labels and snap.incident_id in labels:
            lbl = labels[snap.incident_id]
            entry["label"] = {
                "fault": lbl.fault,
                "service": lbl.service,
                "category": lbl.category,
                "layer": lbl.layer,
                "edge": lbl.edge,
            }
        incidents.append(entry)
    _write(out / "incidents.json", incidents)

    site: dict[str, object] = {
        "labels_included": include_labels,
        "n_snapshots": len(incidents),
        "has_runs": runs_path.exists(),
        "best_model": None,
        "label": f"pilot (n={len(incidents)} snapshots)",
    }
    if runs_path.exists():
        runs = pl.read_parquet(runs_path)
        shutil.copyfile(runs_path, out / "runs.parquet")
        site["best_model"] = best_model(runs)
        site["models"] = sorted(runs["model_id"].unique().to_list())
        known = {i: lbl for i, lbl in labels.items() if i in set(runs["incident_id"])}
        if len(known) == runs["incident_id"].n_unique():
            _write(out / "summary.json", _rows(summary(runs, known)))
            hyp, _ = hypotheses(runs, known, [], None)
            _write(out / "hypotheses.json", _rows(hyp))
    _write(out / "site.json", site)
    return site
