"""Write every evidence pack and prompt to JSON for the Rust replay CLI and
the static site.

    uv run --project harness python -m rootline_harness.export_packs

Writes data/packs/<incident_id>/<condition>-<perturbation>.json. Files hold
the prompt and the pack exactly as a model sees them: never labels, never
the P1 name mapping.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rootline_harness.packers import CONDITIONS, load_snapshot
from rootline_harness.prompt import Perturbation, Prompt, build_prompt

ROOT = Path(__file__).resolve().parents[2]
PERTURBATIONS: tuple[Perturbation, ...] = ("p0", "p1")
FORMAT_VERSION = 1


def pack_document(prompt: Prompt) -> dict[str, object]:
    pack = json.loads(prompt.pack.to_json())
    return {
        "format": FORMAT_VERSION,
        "incident_id": prompt.pack.incident_id,
        "condition": prompt.pack.condition,
        "perturbation": prompt.pack.perturbation,
        "prompt_tokens": prompt.tokens,
        "prompt": prompt.text,
        "rendered": prompt.pack.render(),
        "pack": pack,
    }


def dumps(doc: dict[str, object]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def export(snapshots: Path, out: Path) -> int:
    n = 0
    for d in sorted(p for p in snapshots.iterdir() if (p / "manifest.json").exists()):
        snap = load_snapshot(d)
        target = out / snap.incident_id
        target.mkdir(parents=True, exist_ok=True)
        for cond in CONDITIONS:
            for pert in PERTURBATIONS:
                doc = pack_document(build_prompt(snap, cond, pert))
                (target / f"{cond}-{pert}.json").write_text(dumps(doc))
                n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rootline_harness.export_packs")
    ap.add_argument("--snapshots", type=Path, default=ROOT / "data" / "snapshots")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "packs")
    args = ap.parse_args(argv)
    print(f"wrote {export(args.snapshots, args.out)} packs to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
