"""Model registry and provider limits.

Every model the pilot runs is listed here with its LiteLLM model string,
cascade tier and provider, so switching provider is a one-line change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

Tier = Literal["A", "B", "C"]
RATELIMITS = Path(__file__).with_name("ratelimits.yaml")


@dataclass(frozen=True)
class Model:
    id: str  # stable name used in run records and job keys
    litellm: str  # model string passed to LiteLLM
    tier: Tier
    provider: str
    # Extra LiteLLM arguments, as (name, value) pairs so the model stays hashable.
    options: tuple[tuple[str, object], ...] = ()
    # Answer budget. A prompt is at most 6,000 tokens; prompt + answer must
    # fit the provider's per-minute token cap.
    max_tokens: int = 2048


# The v0.1 models: one per size, all open-weight and free to run.
# Tier A and B run locally in Ollama at its default 4-bit quantisation
# (Q4_K_M); `ollama pull` the exact tags below. Ollama's default context
# (2-4k) would silently cut a 6,000-token pack, so num_ctx is set with room
# for tokenizers that count more tokens than cl100k_base. Qwen3 answers
# without its thinking mode, so it returns the JSON directly.
_LOCAL_CTX = ("num_ctx", 12288)
MODELS: dict[str, Model] = {
    m.id: m
    for m in (
        Model("gpt-oss-120b@cerebras", "cerebras/gpt-oss-120b", "C", "cerebras"),
        # Groq's free tier allows 8,000 tokens a minute, so a full 6,000-token
        # pack leaves about 1,500 for the answer; low reasoning effort keeps
        # gpt-oss's reasoning inside that budget.
        Model(
            "gpt-oss-120b@groq",
            "groq/openai/gpt-oss-120b",
            "C",
            "groq",
            (("reasoning_effort", "low"),),
            max_tokens=1536,
        ),
        Model(
            "qwen3-8b-q4@ollama",
            "ollama_chat/qwen3:8b",
            "B",
            "ollama",
            (_LOCAL_CTX, ("reasoning_effort", "none")),
        ),
        Model("gemma3-4b-q4@ollama", "ollama_chat/gemma3:4b", "A", "ollama", (_LOCAL_CTX,)),
    )
}


@dataclass(frozen=True)
class Limits:
    rpm: int | None
    rpd: int | None
    tpm: int | None
    tpd: int | None
    api_base: str | None = None


def load_limits(path: Path = RATELIMITS) -> dict[str, Limits]:
    raw = yaml.safe_load(path.read_text())
    out: dict[str, Limits] = {}
    for name, cfg in raw["providers"].items():
        unknown = set(cfg) - {"rpm", "rpd", "tpm", "tpd", "api_base"}
        if unknown:
            raise ValueError(f"{path}: provider {name} has unknown keys {sorted(unknown)}")
        out[name] = Limits(
            rpm=cfg.get("rpm"),
            rpd=cfg.get("rpd"),
            tpm=cfg.get("tpm"),
            tpd=cfg.get("tpd"),
            api_base=cfg.get("api_base"),
        )
    return out


def get_model(model_id: str) -> Model:
    try:
        return MODELS[model_id]
    except KeyError:
        raise KeyError(f"unknown model {model_id!r}; known: {sorted(MODELS)}") from None
