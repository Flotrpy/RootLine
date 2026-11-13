"""P1: anonymise service names.

Every service becomes svc-NN with one consistent mapping per snapshot,
applied to every field of the pack and to the prompt's service and edge
lists. The mapping is kept for scoring and never shown to the model.

Service names also hide inside identifiers such as
"oteldemo.PaymentService/Charge", so each name is matched in its kebab,
snake, flat, CamelCase and upper-case forms. Matches must sit on a token or
camel-case boundary, so short names like "ad" never hit words like
"handled".

P1 runs are v0.2 (RQ3); review the boundary rules against the v0.1 span
names before then.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import replace
from functools import cache

from rootline_harness.catalog import SERVICES
from rootline_harness.packers.evidence import Line, Pack, Section


def mapping_for(incident_id: str, services: tuple[str, ...] = SERVICES) -> dict[str, str]:
    """Deterministic per-snapshot mapping, shuffled so svc numbers do not
    follow alphabetical order."""
    seed = int.from_bytes(hashlib.sha256(incident_id.encode()).digest()[:8], "big")
    numbers = list(range(1, len(services) + 1))
    random.Random(seed).shuffle(numbers)
    return {s: f"svc-{n:02d}" for s, n in zip(sorted(services), numbers, strict=True)}


def _variants(name: str) -> set[str]:
    parts = name.split("-")
    return {
        "-".join(parts),
        "_".join(parts),
        "".join(parts),
        "".join(p.capitalize() for p in parts),
        "_".join(p.upper() for p in parts),
        "".join(p.upper() for p in parts),
    }


@cache
def _pattern(services: tuple[str, ...]) -> tuple[re.Pattern[str], dict[str, str]]:
    owner: dict[str, str] = {}
    for s in services:
        for v in _variants(s):
            owner.setdefault(v, s)
    alts = sorted(owner, key=lambda v: (-len(v), v))

    # Start: not after a letter or digit, or at a lower->Upper camel boundary.
    # End: an all-caps form must not run into another capital ("AD" in
    # "ADDR"); any other form must not run into a lowercase letter or digit.
    def alt(v: str) -> str:
        end = r"(?![A-Za-z0-9])" if v.isupper() else r"(?![a-z0-9])"
        return re.escape(v) + end

    pat = r"(?:(?<![A-Za-z0-9])|(?<=[a-z])(?=[A-Z]))(?:" + "|".join(map(alt, alts)) + ")"
    return re.compile(pat), owner


def anonymise_text(text: str, mapping: dict[str, str]) -> str:
    pattern, owner = _pattern(tuple(sorted(mapping)))
    return pattern.sub(lambda m: mapping[owner[m.group(0)]], text)


def anonymise_pack(pack: Pack, mapping: dict[str, str]) -> Pack:
    def line(ln: Line) -> Line:
        return replace(
            ln,
            text=anonymise_text(ln.text, mapping),
            services=tuple(mapping.get(s, s) for s in ln.services),
        )

    def section(s: Section) -> Section:
        return replace(s, header=anonymise_text(s.header, mapping), lines=tuple(map(line, s.lines)))

    return replace(pack, perturbation="p1", sections=tuple(map(section, pack.sections)))


def invert(mapping: dict[str, str]) -> dict[str, str]:
    return {v: k for k, v in mapping.items()}
