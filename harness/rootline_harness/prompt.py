"""Build the full prompt for one (snapshot, condition, perturbation).

The pack gets whatever is left of the 6,000-token budget after the
instructions, so the whole prompt always fits free-tier limits and every
condition gets the same space.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rootline_harness.catalog import CATEGORIES, EDGES, SERVICES
from rootline_harness.packers import PROMPT_BUDGET, Condition, Pack, Snapshot, build_pack
from rootline_harness.packers.budget import count_tokens
from rootline_harness.perturb import anonymise_pack, anonymise_text, mapping_for

Perturbation = Literal["p0", "p1"]

TEMPLATE = """You are the on-call engineer for a microservice web shop. Below is telemetry \
from a 10-minute window; "fault onset" is the midpoint. The window may contain a fault, or \
the system may be healthy.

Find the root cause using only the evidence below.

Services: {services}
Network edges you can act on: {edges}
Categories: {categories}
Layers: application (the service itself is broken), network (the link between services is \
degraded), none (healthy).

Answer with ONE JSON object and nothing else:
{{"abstain": bool, "layer": "application"|"network"|"none",
 "hypotheses": [{{"rank": 1, "service": str, "category": str, "confidence": 0.0-1.0,
                 "evidence": ["evidence IDs such as M-0001, T-0001, L-0001"]}}],
 "action": {{"type": "restart"|"disable_feature"|"clear_network_fault"|"no_action",
            "target": service, edge, or null for no_action}}}}

Rules: give up to 3 hypotheses ranked best first; cite only IDs that appear below; \
confidence is your probability that the hypothesis is right; if healthy use layer "none", \
no hypotheses and no_action; set abstain true only if the evidence is unusable.

EVIDENCE
{pack}
"""


@dataclass(frozen=True)
class Prompt:
    text: str
    tokens: int
    pack: Pack
    mapping: dict[str, str] | None  # P1 only: real service -> svc-NN


def _render(services: list[str], edges: list[str], pack_text: str) -> str:
    return TEMPLATE.format(
        services=", ".join(services),
        edges=", ".join(edges),
        categories=", ".join(c for c in CATEGORIES if c != "none"),
        pack=pack_text,
    )


def build_prompt(
    snap: Snapshot,
    condition: Condition,
    perturbation: Perturbation = "p0",
    budget: int = PROMPT_BUDGET,
) -> Prompt:
    mapping = mapping_for(snap.incident_id) if perturbation == "p1" else None
    services = sorted(SERVICES)
    edges = list(EDGES)
    if mapping:
        services = sorted(mapping[s] for s in services)
        edges = [anonymise_text(e, mapping) for e in edges]

    overhead = count_tokens(_render(services, edges, ""))
    # Anonymising changes token counts, so pack with a little headroom and
    # re-check the final prompt; shrink and retry in the rare case it is over.
    margin = 0
    while True:
        pack = build_pack(snap, condition, budget - overhead - margin)
        if mapping:
            pack = anonymise_pack(pack, mapping)
        text = _render(services, edges, pack.render())
        tokens = count_tokens(text)
        if tokens <= budget:
            return Prompt(text=text, tokens=tokens, pack=pack, mapping=mapping)
        margin += tokens - budget + 16
