"""Token budget: every prompt is at most 6,000 input tokens.

Tokens are counted with tiktoken's cl100k_base as a shared approximation
across models; the exact count is recorded with every run.
"""

from __future__ import annotations

from functools import cache

import tiktoken

from rootline_harness.packers.evidence import Pack, Section

PROMPT_BUDGET = 6000
ENCODING = "cl100k_base"


@cache
def _encoder() -> tiktoken.Encoding:
    return tiktoken.get_encoding(ENCODING)


def count_tokens(text: str) -> int:
    return len(_encoder().encode(text, disallowed_special=()))


def fit_section(section: Section, budget: int) -> Section:
    """Keep the longest prefix of ranked lines whose rendering fits budget.

    Binary search over the prefix length; each candidate is rendered and
    counted exactly, so the result never exceeds the budget unless the bare
    header alone does.
    """
    if count_tokens(section.render()) <= budget:
        return section
    lo, hi = 0, len(section.lines)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(section.keep(mid).render()) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return section.keep(lo)


def fit_pack(pack: Pack, budget: int) -> Pack:
    """Split the budget evenly across sections, then trim any remainder.

    The even split is what gives the combined condition a third of the
    budget for each signal. The final loop drops the lowest-ranked line of
    the largest section until the joined pack fits, which covers the few
    tokens the section separators cost.
    """
    n = max(1, len(pack.sections))
    share = budget // n
    sections = [fit_section(s, share) for s in pack.sections]
    out = Pack(pack.incident_id, pack.condition, pack.perturbation, tuple(sections))
    while count_tokens(out.render()) > budget:
        i = max(range(len(sections)), key=lambda j: len(sections[j].lines))
        if not sections[i].lines:
            raise ValueError("budget too small for section headers")
        sections[i] = sections[i].keep(len(sections[i].lines) - 1)
        out = Pack(pack.incident_id, pack.condition, pack.perturbation, tuple(sections))
    return out
