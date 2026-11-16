"""Inspect AI tasks: one per (condition, perturbation).

These reuse the same prompt, retry rule and scorer as the scheduler, so a
run here scores exactly like a queued run. Use them to browse trajectories
in Inspect's log viewer; use the scheduler for the rate-limited pilot runs.

    uv run inspect eval rootline_harness/tasks/rootline.py@rootline \\
        -T condition=combined -T perturbation=p0 --model groq/openai/gpt-oss-120b

Snapshots and labels come from ROOTLINE_SNAPSHOTS and ROOTLINE_LABELS
(defaults: data/snapshots and data/labels in the repository).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageUser, GenerateConfig
from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.solver import Generate, TaskState, solver

from rootline_harness.packers import CONDITIONS, load_snapshot
from rootline_harness.prompt import build_prompt, retry_text
from rootline_harness.runner import MAX_TOKENS, SEED, TEMPERATURE
from rootline_harness.schema import parse_output
from rootline_harness.scorers import Label, score_run

ROOT = Path(__file__).resolve().parents[3]


def _dirs() -> tuple[Path, Path]:
    snaps = Path(os.environ.get("ROOTLINE_SNAPSHOTS", ROOT / "data" / "snapshots"))
    labels = Path(os.environ.get("ROOTLINE_LABELS", ROOT / "data" / "labels"))
    return snaps, labels


def build_dataset(condition: str, perturbation: str) -> MemoryDataset:
    snaps, labels = _dirs()
    samples = []
    for d in sorted(p for p in snaps.iterdir() if (p / "manifest.json").exists()):
        prompt = build_prompt(load_snapshot(d), condition, perturbation)  # type: ignore[arg-type]
        label = json.loads((labels / f"{d.name}.json").read_text())
        samples.append(
            Sample(
                id=d.name,
                input=prompt.text,
                target=json.dumps(label, sort_keys=True),
                metadata={
                    "prompt_tokens": prompt.tokens,
                    "evidence_index": {k: list(v) for k, v in prompt.pack.evidence_index().items()},
                    "mapping": prompt.mapping,
                },
            )
        )
    return MemoryDataset(samples, name=f"rootline-{condition}-{perturbation}")


@solver
def diagnose():
    """Generate; on invalid output retry once with the error appended."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        original = state.input_text
        state = await generate(state)
        _, err = parse_output(state.output.completion)
        state.metadata["attempts"] = 1
        if err is not None:
            state.messages = [ChatMessageUser(content=retry_text(original, err))]
            state = await generate(state)
            state.metadata["attempts"] = 2
        return state

    return solve


@scorer(metrics={"top1": [mean()], "top3": [mean()], "layer_ok": [mean()], "parsed_ok": [mean()]})
def rootline_scorer():
    async def score(state: TaskState, target: Target) -> Score:
        out, err = parse_output(state.output.completion)
        label = Label.from_dict(json.loads(target.text))
        index = {k: tuple(v) for k, v in state.metadata["evidence_index"].items()}
        s = score_run(out, label, index, state.metadata.get("mapping"))
        return Score(
            value={
                "top1": s.top1,
                "top3": s.top3,
                "layer_ok": s.layer_ok,
                "parsed_ok": s.parsed_ok,
            },
            answer=state.output.completion,
            explanation=err,
            metadata=s.as_dict(),
        )

    return score


@task
def rootline(condition: str = "combined", perturbation: str = "p0") -> Task:
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {CONDITIONS}")
    if perturbation not in ("p0", "p1"):
        raise ValueError("perturbation must be p0 or p1")
    return Task(
        dataset=build_dataset(condition, perturbation),
        solver=diagnose(),
        scorer=rootline_scorer(),
        config=GenerateConfig(temperature=TEMPERATURE, seed=SEED, max_tokens=MAX_TOKENS),
    )
