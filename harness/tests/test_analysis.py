"""End-to-end check of the analysis on a synthetic run set.

The run records below are invented test inputs with known answers; they
exist only to check the arithmetic and are never reported anywhere.
"""

import json
import math
from pathlib import Path

import polars as pl
import pytest

from analysis.__main__ import main, plan_remediation, reproduce
from analysis.tables import best_model, hypotheses, summary
from rootline_harness.runner import RUN_COLUMNS
from rootline_harness.scorers import Label

APP = [f"app{i}-r1" for i in range(8)]
NET = [f"net{i}-r1" for i in range(4)]
HEALTHY = ["healthy-r1", "healthy-r2"]
INCIDENTS = APP + NET + HEALTHY

LABELS = {
    **{i: Label(i.split("-")[0], "payment", "error", "application") for i in APP},
    **{i: Label(i.split("-")[0], "payment", "network_reset", "network", "e") for i in NET},
    **{i: Label("healthy", "none", "none", "none") for i in HEALTHY},
}


def answer(correct: bool, healthy: bool, conf: float = 0.8) -> str:
    if healthy and correct:
        return json.dumps(
            {"abstain": False, "layer": "none", "hypotheses": [],
             "action": {"type": "no_action", "target": None}}
        )  # fmt: skip
    return json.dumps(
        {"abstain": False, "layer": "application",
         "hypotheses": [{"rank": 1, "service": "payment", "category": "error",
                         "confidence": conf, "evidence": []}],
         "action": {"type": "disable_feature", "target": "payment"}}
    )  # fmt: skip


def record(inc, model, tier, cond, pert, top1, layer_ok=None, conf=0.8, tokens=1000):
    healthy = LABELS[inc].healthy
    r: dict[str, object] = {c: None for c in RUN_COLUMNS}
    r.update(
        run_id=f"{inc}|{cond}|{pert}|{model}", incident_id=inc, condition=cond,
        perturbation=pert, model_id=model, tier=tier, provider="p",
        prompt_tokens=tokens, completion_tokens=50, latency_ms=10,
        raw_output=answer(top1, healthy, conf), parsed_ok=True, top1=top1, top3=top1,
        layer_ok=top1 if layer_ok is None else layer_ok, evidence_validity=None,
        confidence=0.0 if healthy and top1 else conf, action_type="disable_feature",
        action_target="payment", started_at="2026-11-08T10:00:00+00:00",
    )  # fmt: skip
    return r


def build_runs() -> pl.DataFrame:
    rows = []
    for inc in INCIDENTS:
        net = inc in NET
        # Tier C "big": combined right everywhere; metrics right on half.
        rows.append(record(inc, "big", "C", "combined", "p0", True, layer_ok=not net))
        rows.append(record(inc, "big", "C", "metrics", "p0", inc in APP[:4] + HEALTHY))
        rows.append(record(inc, "big", "C", "traces", "p0", inc in APP[:2] + HEALTHY))
        rows.append(record(inc, "big", "C", "logs", "p0", inc in HEALTHY))
        # P1 breaks half the app faults.
        rows.append(record(inc, "big", "C", "combined", "p1", inc not in APP[:4]))
        # Small tiers for the cascade.
        rows.append(record(inc, "mid", "B", "combined", "p0", inc in APP, conf=0.75, tokens=300))
        rows.append(record(inc, "tiny", "A", "combined", "p0", inc in APP[:4], conf=0.5,
                           tokens=100))  # fmt: skip
    return pl.DataFrame(rows, infer_schema_length=None)


RUNS = build_runs()


def test_summary_rows() -> None:
    s = summary(RUNS, LABELS)
    row = s.filter(
        (pl.col("model_id") == "big") & (pl.col("condition") == "combined")
        & (pl.col("perturbation") == "p0")
    ).row(0, named=True)  # fmt: skip
    assert row["n"] == 14 and row["top1"] == 1.0
    assert row["healthy_false_alarm_rate"] == 0.0
    assert row["top1_ci_low"] == row["top1_ci_high"] == 1.0
    tiny = s.filter(pl.col("model_id") == "tiny").row(0, named=True)
    assert tiny["healthy_false_alarm_rate"] == 1.0  # wrong on healthy = claimed a fault


def test_best_model() -> None:
    assert best_model(RUNS) == "big"


def test_hypotheses() -> None:
    hyp, cascade = hypotheses(RUNS, LABELS, [], None)
    by = {r["rq"]: r for r in hyp.to_dicts()}
    # RQ1: combined 14/14 vs best single (metrics, 6/14) -> +57 pp.
    assert by["RQ1"]["effect"] == pytest.approx(8 / 14)
    assert by["RQ1"]["threshold_met"] and "best single=metrics" in by["RQ1"]["detail"]
    # RQ2: app layer 8/8, network 0/4 -> 1.0 gap.
    assert by["RQ2"]["effect"] == pytest.approx(1.0) and by["RQ2"]["threshold_met"]
    # RQ3: 14/14 -> 10/14, relative drop 4/14.
    assert by["RQ3"]["effect"] == pytest.approx(4 / 14)
    assert by["RQ4"]["status"] == "tested" and cascade is not None
    assert by["RQ5"]["status"].startswith("not run")
    assert by["RQ6"]["status"].startswith("not run")
    tested = [r for r in by.values() if r["status"] == "tested"]
    assert all(r["p_holm"] >= r["p_value"] for r in tested)


def test_rq5_with_trials() -> None:
    trials = [
        {"incident_id": i, "recovered": i in APP[:3], "harmful": i in HEALTHY} for i in INCIDENTS
    ]
    hyp, _ = hypotheses(RUNS, LABELS, trials, None)
    rq5 = hyp.filter(pl.col("rq") == "RQ5").row(0, named=True)
    assert rq5["effect"] == pytest.approx(1 - 3 / 14)
    assert "harmful-action rate=0.143" in rq5["detail"]


def test_plan_remediation() -> None:
    cmds = plan_remediation(RUNS, "big")
    assert len(cmds) == 13  # every -r1 incident: 8 app + 4 network + healthy-r1
    assert cmds[0].startswith("./bin/rootlinectl remediate --action disable_feature")
    assert "--jsonl data/runs/remediation.jsonl" in cmds[0]


@pytest.fixture
def repo(tmp_path) -> Path:
    (tmp_path / "data" / "runs").mkdir(parents=True)
    (tmp_path / "data" / "labels").mkdir()
    RUNS.write_parquet(tmp_path / "data" / "runs" / "runs.parquet")
    for inc, lbl in LABELS.items():
        (tmp_path / "data" / "labels" / f"{inc}.json").write_text(
            json.dumps({"fault": lbl.fault, "service": lbl.service, "category": lbl.category,
                        "layer": lbl.layer, "edge": lbl.edge, "flag": None, "variant": None})
        )  # fmt: skip
    return tmp_path


def test_reproduce_writes_everything_deterministically(repo) -> None:
    out = repo / "paper" / "figures"
    res = reproduce(repo, out)
    for f in ("summary.csv", "hypotheses.csv", "results.json", "rq1_conditions.svg",
              "rq2_layers.svg", "rq4_cascade.svg", "cascade_sweep.csv"):  # fmt: skip
        assert (out / f).exists(), f
    assert (out / "rq1_conditions.svg").read_text().startswith("<svg")
    assert res["label"] == "pilot (n=14 snapshots)"
    first = {f.name: f.read_bytes() for f in out.iterdir()}
    reproduce(repo, out)
    assert first == {f.name: f.read_bytes() for f in out.iterdir()}
    # results.json never holds NaN, which is not valid JSON.
    assert not math.isnan(json.loads((out / "results.json").read_text())["rq4_theta"])


def test_reproduce_refuses_unlabelled_runs(repo) -> None:
    (repo / "data" / "labels" / "app0-r1.json").unlink()
    with pytest.raises(SystemExit, match="runs without labels"):
        reproduce(repo, repo / "out")


def test_cli(repo, capsys) -> None:
    assert main(["--root", str(repo), "reproduce"]) == 0
    assert "RQ1: tested" in capsys.readouterr().out
    assert main(["--root", str(repo), "plan-remediation"]) == 0
    assert "# remediation trials for big" in capsys.readouterr().out
