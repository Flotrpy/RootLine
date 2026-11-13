"""Model output contract (docs/BUILD_PROMPT.md section 4).

Strict Pydantic v2 models: unknown keys, wrong types and out-of-range values
are all validation errors. Change only with flotrpy's sign-off.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Layer = Literal["application", "network", "none"]
ActionType = Literal["restart", "disable_feature", "clear_network_fault", "no_action"]


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Hypothesis(_Strict):
    rank: Annotated[int, Field(ge=1)]
    service: Annotated[str, Field(min_length=1, max_length=64)]
    category: Annotated[str, Field(min_length=1, max_length=64)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    evidence: list[str]


class Action(_Strict):
    type: ActionType
    target: str | None

    @model_validator(mode="after")
    def _target_matches_type(self) -> Action:
        if self.type == "no_action" and self.target not in (None, ""):
            raise ValueError("no_action takes no target")
        if self.type != "no_action" and not self.target:
            raise ValueError(f"{self.type} needs a target")
        return self


class ModelOutput(_Strict):
    abstain: bool
    layer: Layer
    hypotheses: list[Hypothesis]
    action: Action

    @model_validator(mode="after")
    def _ranks_are_unique(self) -> ModelOutput:
        ranks = [h.rank for h in self.hypotheses]
        if len(ranks) != len(set(ranks)):
            raise ValueError("hypothesis ranks must be unique")
        return self

    def ranked(self) -> list[Hypothesis]:
        """Hypotheses sorted by rank, best first."""
        return sorted(self.hypotheses, key=lambda h: h.rank)

    def top(self) -> Hypothesis | None:
        r = self.ranked()
        return r[0] if r else None


_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


def parse_output(raw: str) -> tuple[ModelOutput | None, str | None]:
    """Parse a model's raw reply.

    Returns (output, None) on success or (None, error) on failure. One
    surrounding Markdown code fence is tolerated because many models add it
    even when told not to; any other text around the JSON is an error.
    """
    m = _FENCE.match(raw)
    text = m.group(1) if m else raw.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e.msg} at line {e.lineno} column {e.colno}"
    try:
        return ModelOutput.model_validate(data), None
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in e.errors()
        )
        return None, f"schema violation: {problems}"


def json_schema() -> str:
    """The contract as compact JSON Schema, for prompts and docs."""
    return json.dumps(ModelOutput.model_json_schema(), separators=(",", ":"))
