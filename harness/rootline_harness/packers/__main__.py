"""Print the evidence pack or full prompt for a snapshot directory.

    uv run python -m rootline_harness.packers data/snapshots/paymentFailure-r1 \\
        --condition combined [--perturb p1] [--prompt] [--json]
"""

from __future__ import annotations

import argparse
import sys

from rootline_harness.packers import CONDITIONS, load_snapshot
from rootline_harness.prompt import build_prompt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rootline_harness.packers")
    ap.add_argument("snapshot", help="snapshot directory")
    ap.add_argument("--condition", choices=CONDITIONS, default="combined")
    ap.add_argument("--perturb", choices=["p0", "p1"], default="p0")
    ap.add_argument("--prompt", action="store_true", help="print the full prompt, not the pack")
    ap.add_argument("--json", action="store_true", help="print the pack as JSON")
    args = ap.parse_args(argv)

    p = build_prompt(load_snapshot(args.snapshot), args.condition, args.perturb)
    if args.json:
        print(p.pack.to_json())
    else:
        print(p.text if args.prompt else p.pack.render())
    print(
        f"[{p.tokens} prompt tokens, {len(p.pack.evidence_index())} evidence lines]",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
