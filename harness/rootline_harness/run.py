"""Queue, run and export model runs.

    uv run python -m rootline_harness.run enqueue --models gpt-oss-120b@cerebras
    uv run python -m rootline_harness.run work
    uv run python -m rootline_harness.run status
    uv run python -m rootline_harness.run export
    uv run python -m rootline_harness.run gate2 --incident paymentFailure-r1 \\
        --model gpt-oss-120b@cerebras

Paths are relative to the repository root by default.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from functools import cache
from pathlib import Path

import polars as pl

from rootline_harness.packers import CONDITIONS, load_snapshot
from rootline_harness.prompt import Perturbation, Prompt, build_prompt
from rootline_harness.runner import (
    RUN_COLUMNS,
    LiteLLMClient,
    ModelClient,
    ModelError,
    load_label,
    run_one,
)
from rootline_harness.scheduler import Queue, get_model, load_limits

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "queue.sqlite"
DEFAULT_SNAPSHOTS = ROOT / "data" / "snapshots"
DEFAULT_LABELS = ROOT / "data" / "labels"
DEFAULT_RUNS = ROOT / "data" / "runs" / "runs.parquet"
GATE2_FIELDS = ("top1", "top3", "layer_ok")


def snapshot_ids(snapshots: Path) -> list[str]:
    return sorted(
        p.name for p in snapshots.iterdir() if p.is_dir() and (p / "manifest.json").exists()
    )


class Worker:
    """Drains the queue, waiting for rate limits instead of hitting them."""

    def __init__(
        self,
        queue: Queue,
        client: ModelClient,
        snapshots: Path,
        labels: Path,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = lambda m: print(m, file=sys.stderr),
    ) -> None:
        self.queue = queue
        self.client = client
        self.snapshots = snapshots
        self.labels = labels
        self.sleep = sleep
        self.log = log

    @cache  # noqa: B019 - one worker per process; prompts are pure functions of these args
    def prompt(self, incident_id: str, condition: str, perturbation: str) -> Prompt:
        snap = load_snapshot(self.snapshots / incident_id)
        return build_prompt(snap, condition, perturbation)  # type: ignore[arg-type]

    def _gate(self, provider: str) -> Callable[[int], None]:
        def before_call(tokens: int) -> None:
            while (wait := self.queue.wait_for(provider, tokens)) > 0:
                self.log(f"rate limit: {provider} waits {wait:.0f}s")
                self.sleep(wait)
            # Record the estimate up front: it over-counts slightly, which
            # keeps every cap safe even if the process dies mid-request.
            self.queue.record_usage(provider, tokens)

        return before_call

    def run_job_once(self) -> bool:
        """Run one eligible job. Returns False when none is eligible now."""
        job = self.queue.claim()
        if job is None:
            return False
        try:
            model = get_model(job.model_id)
            prompt = self.prompt(job.incident_id, job.condition, job.perturbation)
            label = load_label(self.labels, job.incident_id)
            record = run_one(
                run_id=job.key,
                prompt=prompt,
                label=label,
                model=model,
                client=self.client,
                condition=job.condition,
                perturbation=job.perturbation,
                before_call=self._gate(model.provider),
            )
        except ModelError as e:
            self.queue.fail(job, str(e), e.retryable)
            self.log(f"{job.key}: {'retry later' if e.retryable else 'failed'}: {e}")
            return True
        except Exception as e:  # recorded, never silently dropped
            self.queue.fail(job, f"{type(e).__name__}: {e}", retryable=False)
            self.log(f"{job.key}: failed: {type(e).__name__}: {e}")
            return True
        self.queue.done(job, record)
        self.log(f"{job.key}: top1={record['top1']} parsed={record['parsed_ok']}")
        return True

    def drain(self) -> dict[str, int]:
        while True:
            if self.run_job_once():
                continue
            wait = self.queue.next_eligible_in()
            if wait is None:
                return self.queue.counts()
            self.sleep(max(wait, 0.5))


def export(queue: Queue, out: Path) -> int:
    records = queue.records()
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = {
        "run_id": pl.String,
        "incident_id": pl.String,
        "condition": pl.String,
        "perturbation": pl.String,
        "model_id": pl.String,
        "tier": pl.String,
        "provider": pl.String,
        "prompt_tokens": pl.Int64,
        "completion_tokens": pl.Int64,
        "latency_ms": pl.Int64,
        "raw_output": pl.String,
        "parsed_ok": pl.Boolean,
        "top1": pl.Boolean,
        "top3": pl.Boolean,
        "layer_ok": pl.Boolean,
        "evidence_validity": pl.Float64,
        "confidence": pl.Float64,
        "action_type": pl.String,
        "action_target": pl.String,
        "started_at": pl.String,
    }
    assert tuple(schema) == RUN_COLUMNS
    df = pl.DataFrame(records, schema=schema).sort("run_id")
    df.write_parquet(out, compression="zstd")
    return df.height


def gate2(
    worker: Worker, incident_id: str, condition: str, perturbation: str, model_id: str
) -> tuple[bool, list[dict[str, object]]]:
    """Gate 2: score the same snapshot twice at temperature 0; the scored
    fields must match."""
    model = get_model(model_id)
    prompt = worker.prompt(incident_id, condition, perturbation)
    label = load_label(worker.labels, incident_id)
    runs = [
        run_one(
            run_id=f"gate2-{i}",
            prompt=prompt,
            label=label,
            model=model,
            client=worker.client,
            condition=condition,
            perturbation=perturbation,
            before_call=worker._gate(model.provider),
        )
        for i in (1, 2)
    ]
    same = all(runs[0][f] == runs[1][f] for f in GATE2_FIELDS)
    return same, runs


def main(argv: list[str] | None = None, client: ModelClient | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rootline_harness.run")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS)
    ap.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    enq = sub.add_parser("enqueue", help="queue every snapshot x condition x model")
    enq.add_argument("--models", nargs="+", required=True)
    enq.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=list(CONDITIONS))
    enq.add_argument("--perturb", choices=["p0", "p1"], default="p0")
    enq.add_argument("--incidents", nargs="*", help="default: every snapshot")

    sub.add_parser("work", help="run queued jobs until none are left")
    sub.add_parser("status", help="job counts and failures")
    exp = sub.add_parser("export", help="write done runs to Parquet")
    exp.add_argument("--out", type=Path, default=DEFAULT_RUNS)

    g2 = sub.add_parser("gate2", help="same snapshot, same score, twice")
    g2.add_argument("--incident", required=True)
    g2.add_argument("--model", required=True)
    g2.add_argument("--condition", choices=CONDITIONS, default="combined")
    g2.add_argument("--perturb", choices=["p0", "p1"], default="p0")

    args = ap.parse_args(argv)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    limits = load_limits()
    queue = Queue(args.db, limits)

    if args.cmd == "enqueue":
        ids = args.incidents or snapshot_ids(args.snapshots)
        added = 0
        for model_id in args.models:
            model = get_model(model_id)
            for inc in ids:
                for cond in args.conditions:
                    added += queue.enqueue(inc, cond, args.perturb, model.id, model.provider)
        print(f"queued {added} new jobs ({len(ids)} snapshots)")
        return 0
    if args.cmd == "status":
        print(queue.counts())
        for key, err in queue.failures():
            print(f"failed {key}: {err}")
        return 0
    if args.cmd == "export":
        n = export(queue, args.out)
        print(f"wrote {n} runs to {args.out}")
        return 0

    worker = Worker(queue, client or LiteLLMClient(limits), args.snapshots, args.labels)
    if args.cmd == "work":
        print(worker.drain())
        return 0
    if args.cmd == "gate2":
        perturbation: Perturbation = args.perturb
        same, runs = gate2(worker, args.incident, args.condition, perturbation, args.model)
        for r in runs:
            print({f: r[f] for f in ("run_id", *GATE2_FIELDS, "parsed_ok", "confidence")})
        print("GATE 2 PASS" if same else "GATE 2 FAIL: scores differ between identical runs")
        return 0 if same else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
