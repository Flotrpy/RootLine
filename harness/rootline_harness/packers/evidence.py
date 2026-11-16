"""Evidence lines, sections and packs.

Every line carries a stable ID (M-0001, T-0001, L-0001) and the services it
is about, so cited evidence can be checked automatically.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Literal

from rootline_harness.catalog import forbidden_strings

Signal = Literal["metrics", "traces", "logs"]
PREFIX: dict[Signal, str] = {"metrics": "M", "traces": "T", "logs": "L"}

_FORBIDDEN = re.compile(
    "|".join(re.escape(s) for s in sorted(forbidden_strings(), key=len, reverse=True)),
    re.IGNORECASE,
)
REDACTED = "<redacted>"


def redact(text: str) -> str:
    """Remove every fault and flag name, whatever the incident."""
    return _FORBIDDEN.sub(REDACTED, text)


def clip(text: str, limit: int) -> str:
    """Shorten text to at most limit characters, marking the cut."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(frozen=True)
class Line:
    id: str
    services: tuple[str, ...]
    text: str

    def render(self) -> str:
        return f"{self.id} {self.text}"


@dataclass(frozen=True)
class Section:
    signal: Signal
    header: str
    lines: tuple[Line, ...]
    omitted: int = 0

    def render(self) -> str:
        out = [f"## {self.signal.upper()}: {self.header}"]
        out += [ln.render() for ln in self.lines]
        if not self.lines:
            out.append("(no evidence lines)")
        if self.omitted:
            out.append(f"({self.omitted} lower-ranked lines omitted for length)")
        return "\n".join(out)

    def keep(self, n: int) -> Section:
        """Keep the n highest-ranked lines."""
        n = max(0, min(n, len(self.lines)))
        return replace(self, lines=self.lines[:n], omitted=self.omitted + len(self.lines) - n)


def make_lines(signal: Signal, ranked: list[tuple[tuple[str, ...], str]]) -> tuple[Line, ...]:
    """Assign IDs in rank order. IDs are fixed before any truncation, so the
    same evidence keeps the same ID in every condition."""
    p = PREFIX[signal]
    return tuple(
        Line(id=f"{p}-{i:04d}", services=svcs, text=redact(text))
        for i, (svcs, text) in enumerate(ranked, start=1)
    )


@dataclass(frozen=True)
class Pack:
    incident_id: str
    condition: str
    perturbation: str
    sections: tuple[Section, ...]

    def render(self) -> str:
        return "\n\n".join(s.render() for s in self.sections)

    def evidence_index(self) -> dict[str, tuple[str, ...]]:
        """Map every shown evidence ID to the services it concerns."""
        return {ln.id: ln.services for s in self.sections for ln in s.lines}

    def to_json(self) -> str:
        return json.dumps(
            {
                "incident_id": self.incident_id,
                "condition": self.condition,
                "perturbation": self.perturbation,
                "sections": [
                    {
                        "signal": s.signal,
                        "header": s.header,
                        "omitted": s.omitted,
                        "lines": [
                            {"id": ln.id, "services": list(ln.services), "text": ln.text}
                            for ln in s.lines
                        ],
                    }
                    for s in self.sections
                ],
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(raw: str) -> Pack:
        d = json.loads(raw)
        return Pack(
            incident_id=d["incident_id"],
            condition=d["condition"],
            perturbation=d["perturbation"],
            sections=tuple(
                Section(
                    signal=s["signal"],
                    header=s["header"],
                    omitted=s["omitted"],
                    lines=tuple(
                        Line(id=ln["id"], services=tuple(ln["services"]), text=ln["text"])
                        for ln in s["lines"]
                    ),
                )
                for s in d["sections"]
            ),
        )
