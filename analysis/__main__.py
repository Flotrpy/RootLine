"""Regenerate every table and figure from data on disk, with no network.

    make reproduce
    # or: uv run --project harness python -m analysis reproduce

Reads data/runs/runs.parquet, data/labels/, data/runs/remediation.jsonl
(optional) and data/snapshots/ (for the baselines), and writes CSVs, SVGs
and results.json into paper/figures/.

    uv run --project harness python -m analysis plan-remediation --model <id>

prints the rootlinectl commands for the live remediation trials, using the
model's own chosen actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import polars as pl

from analysis import figures
from analysis.stats import BOOTSTRAP_RESAMPLES, SEED
from analysis.tables import RQ4_THETA, best_model, emulation_validity, hypotheses, summary
from cascade.sweep import single_tiers
from rootline_harness.scorers import Label

ROOT = Path(__file__).resolve().parents[1]


def load_labels(d: Path) -> dict[str, Label]:
    return {p.stem: Label.from_dict(json.loads(p.read_text())) for p in sorted(d.glob("*.json"))}


def load_trials(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _clean(v: object) -> object:
    return None if isinstance(v, float) and math.isnan(v) else v


def reproduce(root: Path, out: Path) -> dict[str, object]:
    runs_path = root / "data" / "runs" / "runs.parquet"
    if not runs_path.exists():
        raise SystemExit(f"no runs at {runs_path}; run the harness and export first")
    runs = pl.read_parquet(runs_path)
    labels = load_labels(root / "data" / "labels")
    missing = sorted(set(runs["incident_id"]) - set(labels))
    if missing:
        raise SystemExit(f"runs without labels: {missing[:5]}")
    trials_path = root / "data" / "runs" / "remediation.jsonl"
    trials = load_trials(trials_path)
    out.mkdir(parents=True, exist_ok=True)

    baseline_preds = None
    snaps = root / "data" / "snapshots"
    if snaps.exists() and any(snaps.iterdir()):
        from baselines.__main__ import run as run_baselines

        run_baselines(snaps, root / "data" / "labels", out)
    if (out / "baseline_predictions.parquet").exists():
        baseline_preds = pl.read_parquet(out / "baseline_predictions.parquet")

    table = summary(runs, labels)
    table.write_csv(out / "summary.csv")
    hyp, cascade_table = hypotheses(runs, labels, trials, baseline_preds)
    hyp.write_csv(out / "hypotheses.csv")
    emu = emulation_validity(runs, labels)
    if not emu.is_empty():
        emu.write_csv(out / "emulation_validity.csv")

    figures.save_svg(figures.rq1_conditions(table), out / "rq1_conditions.svg")
    figures.save_svg(figures.rq2_layers(runs, labels), out / "rq2_layers.svg")
    if cascade_table is not None:
        cascade_table.write_csv(out / "cascade_sweep.csv")
        from cascade.sweep import select

        tiers = single_tiers(select(runs))
        tiers.write_csv(out / "cascade_tiers.csv")
        figures.save_svg(figures.rq4_cascade(cascade_table, tiers), out / "rq4_cascade.svg")

    leaderboard = table.filter(
        (pl.col("condition") == "combined") & (pl.col("perturbation") == "p0")
    ).sort(["top1", "model_id"], descending=[True, False])
    baselines_csv = out / "baselines.csv"
    results = {
        "label": f"pilot (n={runs['incident_id'].n_unique()} snapshots)",
        "n_snapshots": runs["incident_id"].n_unique(),
        "leaderboard": [{k: _clean(v) for k, v in r.items()} for r in leaderboard.to_dicts()],
        "baselines": [
            {k: _clean(v) for k, v in r.items()} for r in pl.read_csv(baselines_csv).to_dicts()
        ]
        if baselines_csv.exists()
        else [],
        "figures": sorted(p.name for p in out.glob("*.svg")),
        "best_model": best_model(runs),
        "seeds": {"bootstrap": SEED, "bootstrap_resamples": BOOTSTRAP_RESAMPLES},
        "rq4_theta": RQ4_THETA,
        "inputs": {
            "runs_sha256": _sha256(runs_path),
            "remediation_sha256": _sha256(trials_path),
            "runs": runs.height,
            "remediation_trials": len(trials),
        },
        "hypotheses": [{k: _clean(v) for k, v in r.items()} for r in hyp.to_dicts()],
        "emulation_validity": [{k: _clean(v) for k, v in r.items()} for r in emu.to_dicts()],
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    return results


def plan_remediation(runs: pl.DataFrame, model: str, replica: int = 1) -> list[str]:
    """One rootlinectl command per incident type, replica r<replica>, using
    the model's action on the combined, unperturbed condition."""
    df = runs.filter(
        (pl.col("model_id") == model)
        & (pl.col("condition") == "combined")
        & (pl.col("perturbation") == "p0")
        & pl.col("incident_id").str.ends_with(f"-r{replica}")
    ).sort("incident_id")
    cmds = []
    for r in df.iter_rows(named=True):
        action = r["action_type"] or "no_action"  # unparsed output acts as no_action
        target = r["action_target"] or ""
        if action == "no_action":
            target = ""
        cmds.append(
            f"./bin/rootlinectl remediate --action {action} --target '{target}' "
            f"--incident {r['incident_id']} --jsonl data/runs/remediation.jsonl"
        )
    return cmds


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m analysis")
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("reproduce")
    rp.add_argument("--out", type=Path, default=None)
    sd = sub.add_parser("site-data", help="write web/public/data for the static site")
    sd.add_argument("--out", type=Path, default=None)
    sd.add_argument(
        "--include-labels", action="store_true", help="release builds only: reveal the answers"
    )
    pk = sub.add_parser("package-dataset", help="build the Hugging Face dataset folder")
    pk.add_argument("--out", type=Path, default=None)
    sub.add_parser("fetch-data", help="download the published dataset into data/ (make data)")
    sub.add_parser("release-check", help="check everything the release needs")
    pr = sub.add_parser("plan-remediation")
    pr.add_argument("--model", default=None, help="default: best model on combined p0")
    pr.add_argument("--replica", type=int, default=1)
    args = ap.parse_args(argv)

    if args.cmd == "reproduce":
        res = reproduce(args.root, args.out or args.root / "paper" / "figures")
        for h in res["hypotheses"]:  # type: ignore[union-attr]
            print(f"{h['rq']}: {h['status']} effect={h['effect']} p_holm={h['p_holm']}")
        return 0
    if args.cmd == "package-dataset":
        from analysis.dataset import DATASET_REPO, package

        out = args.out or args.root / "dist" / "rootline-v0.1-data"
        counts = package(args.root / "data", out)
        print(f"built {out}: {counts['snapshots']} snapshots, {counts['labels']} labels")
        print(f"publish (flotrpy): huggingface-cli upload {DATASET_REPO} {out} --repo-type dataset")
        return 0
    if args.cmd == "fetch-data":
        from analysis.dataset import DATASET_REPO, fetch

        fetch(args.root / "data")
        print(f"fetched {DATASET_REPO} into {args.root / 'data'}")
        return 0
    if args.cmd == "release-check":
        from analysis.release_check import report, run_all

        checks = run_all(args.root)
        print(report(checks))
        return 1 if any(c.status == "FAIL" for c in checks) else 0
    if args.cmd == "site-data":
        from analysis.site_data import write_site_data

        out = args.out or args.root / "web" / "public" / "data"
        site = write_site_data(args.root, out, args.include_labels)
        print(
            f"wrote site data to {out}: {site['label']}, labels included: {site['labels_included']}"
        )
        return 0
    runs = pl.read_parquet(args.root / "data" / "runs" / "runs.parquet")
    model = args.model or best_model(runs)
    if model is None:
        raise SystemExit("no combined p0 runs to plan from")
    print(f"# remediation trials for {model}")
    print("\n".join(plan_remediation(runs, model, args.replica)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
