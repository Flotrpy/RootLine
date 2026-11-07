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


# Tier C comes from the charter. TODO(flotrpy): add the Tier A (~3-4B) and
# Tier B (7-9B) models once chosen, with exact tags and quantisation, e.g.
#   Model("<name>-q4", "ollama/<tag>", "A", "ollama")
#   Model("<name>-awq", "hosted_vllm/<hf-repo>", "B", "vllm")
MODELS: dict[str, Model] = {
    m.id: m
    for m in (
        Model("gpt-oss-120b@cerebras", "cerebras/gpt-oss-120b", "C", "cerebras"),
        Model("gpt-oss-120b@groq", "groq/openai/gpt-oss-120b", "C", "groq"),
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
