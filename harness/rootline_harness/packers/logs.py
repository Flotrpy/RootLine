"""Logs packer: Drain3 templates per service, ranked by how much their
frequency changed after fault onset, with two raw examples each."""

from __future__ import annotations

import math
from collections import Counter, defaultdict

import polars as pl
from drain3 import TemplateMiner
from drain3.masking import MaskingInstruction
from drain3.template_miner_config import TemplateMinerConfig

from rootline_harness.packers.evidence import Section, clip, make_lines, redact
from rootline_harness.packers.snapshot import Snapshot

MAX_TEMPLATE = 140
MAX_EXAMPLE = 140
N_EXAMPLES = 2

_MASKS = [
    MaskingInstruction(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "UUID"
    ),
    MaskingInstruction(r"\b[0-9a-fA-F]{16,}\b", "HEX"),
    MaskingInstruction(r"\b\d+(\.\d+)?(ms|s|%)?\b", "NUM"),
]


def _miner() -> TemplateMiner:
    cfg = TemplateMinerConfig()
    cfg.profiling_enabled = False
    cfg.drain_sim_th = 0.4
    cfg.drain_depth = 4
    cfg.masking_instructions = list(_MASKS)
    return TemplateMiner(config=cfg)


def pack_logs(snap: Snapshot) -> Section:
    logs = (
        snap.logs.filter((pl.col("ts") >= snap.start_ms) & (pl.col("ts") < snap.end_ms))
        .with_columns(body=pl.col("body").fill_null(""), severity=pl.col("severity").fill_null(""))
        .sort(["service", "ts", "body"])
    )
    base_min = max((snap.t0_ms - snap.start_ms) / 60_000, 1e-9)
    fault_min = max((snap.end_ms - snap.t0_ms) / 60_000, 1e-9)

    ranked: list[tuple[float, int, str, str, tuple[tuple[str, ...], str]]] = []
    for (service,), grp in logs.group_by(["service"], maintain_order=True):
        miner = _miner()
        base_n: Counter[int] = Counter()
        fault_n: Counter[int] = Counter()
        sev: dict[int, Counter[str]] = defaultdict(Counter)
        examples: dict[int, list[str]] = defaultdict(list)
        base_examples: dict[int, list[str]] = defaultdict(list)
        for ts, severity, body in grp.select("ts", "severity", "body").iter_rows():
            text = redact(body)
            cid = miner.add_log_message(text)["cluster_id"]
            sev[cid][severity.upper() or "UNSET"] += 1
            if ts < snap.t0_ms:
                base_n[cid] += 1
                if len(base_examples[cid]) < N_EXAMPLES:
                    base_examples[cid].append(text)
            else:
                fault_n[cid] += 1
                if len(examples[cid]) < N_EXAMPLES:
                    examples[cid].append(text)
        for cluster in miner.drain.clusters:
            cid = cluster.cluster_id
            b, f = base_n[cid] / base_min, fault_n[cid] / fault_min
            score = abs(math.log2((f + 1) / (b + 1)))
            severity = sorted(sev[cid].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            ex = examples[cid] or base_examples[cid]
            tpl = clip(cluster.get_template(), MAX_TEMPLATE)
            line = (
                f'svc={service} sev={severity} base={b:.1f}/min fault={f:.1f}/min tpl="{tpl}" '
                f"ex={[clip(e, MAX_EXAMPLE) for e in ex]}"
            )
            ranked.append((score, fault_n[cid], str(service), tpl, ((str(service),), line)))
    ranked.sort(key=lambda r: (-r[0], -r[1], r[2], r[3]))
    return Section(
        signal="logs",
        header="log templates per service, rate before vs after fault onset, with examples",
        lines=make_lines("logs", [r[4] for r in ranked]),
    )
