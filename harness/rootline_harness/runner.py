"""Run one model on one prompt and turn the reply into a run record.

Invalid output gets exactly one retry with the validation error appended;
a second failure is scored as an abstention (parsed_ok = false, counted as
invalid_output). Token counts cover both attempts.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from rootline_harness.packers.budget import count_tokens
from rootline_harness.prompt import Prompt, retry_text
from rootline_harness.scheduler.providers import Limits, Model
from rootline_harness.schema import parse_output
from rootline_harness.scorers import Label, score_run

TEMPERATURE = 0.0
SEED = 0
# Reasoning models spend completion tokens before answering.
# TODO(flotrpy): tune per model after the first Tier C runs.
MAX_TOKENS = 2048

RUN_COLUMNS = (
    "run_id",
    "incident_id",
    "condition",
    "perturbation",
    "model_id",
    "tier",
    "provider",
    "prompt_tokens",
    "completion_tokens",
    "latency_ms",
    "raw_output",
    "parsed_ok",
    "top1",
    "top3",
    "layer_ok",
    "evidence_validity",
    "confidence",
    "action_type",
    "action_target",
    "started_at",
)
"""Run record columns, exactly as in the data contract."""


@dataclass(frozen=True)
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class ModelError(Exception):
    """A failed model call. retryable is True for rate limits, timeouts and
    server errors, False for bad requests and auth failures."""

    def __init__(self, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class ModelClient(Protocol):
    def complete(self, model: Model, prompt: str) -> Completion: ...


class LiteLLMClient:
    """Calls any provider through LiteLLM at temperature 0 with a fixed seed."""

    def __init__(self, limits: dict[str, Limits], max_tokens: int = MAX_TOKENS) -> None:
        self.limits = limits
        self.max_tokens = max_tokens

    def complete(self, model: Model, prompt: str) -> Completion:
        import litellm
        from litellm import exceptions as llm_errors

        lim = self.limits.get(model.provider)
        kwargs: dict[str, object] = dict(model.options)
        if lim and lim.api_base:
            kwargs["api_base"] = lim.api_base
        start = time.perf_counter()
        try:
            resp = litellm.completion(
                model=model.litellm,
                messages=[{"role": "user", "content": prompt}],
                temperature=TEMPERATURE,
                seed=SEED,
                max_tokens=min(self.max_tokens, model.max_tokens),
                num_retries=0,  # the scheduler owns retries and backoff
                **kwargs,
            )
        except (
            llm_errors.RateLimitError,
            llm_errors.Timeout,
            llm_errors.APIConnectionError,
            llm_errors.ServiceUnavailableError,
            llm_errors.InternalServerError,
        ) as e:
            raise ModelError(f"{type(e).__name__}: {e}", retryable=True) from e
        except Exception as e:
            # Bad requests, auth and unknown-model errors: retrying will not
            # help. (Not every LiteLLM error subclasses APIError.)
            raise ModelError(f"{type(e).__name__}: {e}", retryable=False) from e
        latency = int((time.perf_counter() - start) * 1000)
        text = resp.choices[0].message.content or ""  # type: ignore[union-attr]
        usage = getattr(resp, "usage", None)
        return Completion(
            text=text,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or count_tokens(prompt)),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or count_tokens(text)),
            latency_ms=latency,
        )


def load_label(labels_dir: str | Path, incident_id: str) -> Label:
    raw = json.loads((Path(labels_dir) / f"{incident_id}.json").read_text())
    return Label.from_dict(raw)


def run_one(
    *,
    run_id: str,
    prompt: Prompt,
    label: Label,
    model: Model,
    client: ModelClient,
    condition: str,
    perturbation: str,
    before_call: Callable[[int], None] = lambda _tokens: None,
    max_tokens: int | None = None,
) -> dict[str, object]:
    """Call the model (twice at most) and return a run record.

    before_call(estimated_tokens) runs before every request; the worker uses
    it to wait for rate limits and record usage.
    """
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    max_tokens = min(max_tokens or MAX_TOKENS, model.max_tokens)
    before_call(prompt.tokens + max_tokens)
    first = client.complete(model, prompt.text)
    out, err = parse_output(first.text)
    attempts = [first]
    if out is None:
        again = retry_text(prompt.text, err or "invalid output")
        before_call(count_tokens(again) + max_tokens)
        second = client.complete(model, again)
        attempts.append(second)
        out, _ = parse_output(second.text)

    score = score_run(out, label, prompt.pack.evidence_index(), prompt.mapping)
    record: dict[str, object] = {
        "run_id": run_id,
        "incident_id": prompt.pack.incident_id,
        "condition": condition,
        "perturbation": perturbation,
        "model_id": model.id,
        "tier": model.tier,
        "provider": model.provider,
        "prompt_tokens": sum(a.prompt_tokens for a in attempts),
        "completion_tokens": sum(a.completion_tokens for a in attempts),
        "latency_ms": sum(a.latency_ms for a in attempts),
        "raw_output": attempts[-1].text,
        "parsed_ok": score.parsed_ok,
        "top1": score.top1,
        "top3": score.top3,
        "layer_ok": score.layer_ok,
        "evidence_validity": score.evidence_validity,
        "confidence": score.confidence,
        "action_type": score.action_type,
        "action_target": score.action_target,
        "started_at": started_at,
    }
    assert tuple(record) == RUN_COLUMNS
    return record
