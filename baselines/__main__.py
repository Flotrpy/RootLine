"""Run both baselines over every labelled snapshot.

    uv run --project harness python -m baselines \\
        --snapshots data/snapshots --labels data/labels --out paper/figures

Writes baselines.csv (summary) and baseline_predictions.parquet (one row per
snapshot and scheme, for paired tests against the LLMs).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from baselines import isolation_forest, lightgbm_lofo
from baselines.features import service_features
from rootline_harness.packers import load_snapshot
from rootline_harness.scorers import Label


def load(snapshots: Path, labels: Path) -> tuple[pl.DataFrame, dict[str, Label]]:
    feats, lbls = [], {}
    for d in sorted(p for p in snapshots.iterdir() if (p / "manifest.json").exists()):
        label_file = labels / f"{d.name}.json"
        if not label_file.exists():
            continue
        lbls[d.name] = Label.from_dict(json.loads(label_file.read_text()))
        feats.append(service_features(load_snapshot(d)))
    if not feats:
        raise SystemExit(f"no labelled snapshots in {snapshots}")
    return pl.concat(feats), lbls


def run(snapshots: Path, labels: Path, out: Path) -> pl.DataFrame:
    feats, lbls = load(snapshots, labels)
    rows, preds = [], []
    for scheme in lightgbm_lofo.SCHEMES:
        p = lightgbm_lofo.evaluate(feats, lbls, scheme)
        preds += [{"model": "lightgbm", **vars(x)} for x in p]
        n = len(p)
        rows.append(
            {
                "model": "lightgbm",
                "scheme": scheme,
                "n": n,
                "top1": sum(x.top1 for x in p) / n if n else None,
                "service_acc": sum(x.service_ok for x in p) / n if n else None,
            }
        )
    iso = isolation_forest.evaluate(feats, lbls)
    preds += [
        {
            "model": "isolation_forest",
            "scheme": "unsupervised",
            "category": None,
            "top1": None,
            **vars(x),
        }
        for x in iso
    ]
    rows.append(
        {
            "model": "isolation_forest",
            "scheme": "unsupervised",
            "n": len(iso),
            "top1": None,  # predicts no category
            "service_acc": sum(x.service_ok for x in iso) / len(iso) if iso else None,
        }
    )
    out.mkdir(parents=True, exist_ok=True)
    summary = pl.DataFrame(rows)
    summary.write_csv(out / "baselines.csv")
    pl.DataFrame(preds, infer_schema_length=None).write_parquet(
        out / "baseline_predictions.parquet"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m baselines")
    ap.add_argument("--snapshots", type=Path, default=Path("data/snapshots"))
    ap.add_argument("--labels", type=Path, default=Path("data/labels"))
    ap.add_argument("--out", type=Path, default=Path("paper/figures"))
    args = ap.parse_args(argv)
    print(run(args.snapshots, args.labels, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
