import re

import pytest

from rootline_harness.catalog import forbidden_strings
from rootline_harness.packers import (
    CONDITIONS,
    Pack,
    Snapshot,
    build_pack,
    count_tokens,
    load_snapshot,
)
from rootline_harness.packers.logs import pack_logs
from rootline_harness.packers.metrics import pack_metrics
from rootline_harness.packers.traces import pack_traces
from tests.synth import LABEL

BUDGET = 5000
ID_RE = re.compile(r"^[MTL]-\d{4}$")


@pytest.mark.parametrize("condition", CONDITIONS)
def test_pack_is_deterministic(snapshot_dir, condition) -> None:
    a = build_pack(load_snapshot(snapshot_dir), condition, BUDGET)
    b = build_pack(load_snapshot(snapshot_dir), condition, BUDGET)
    assert a.render() == b.render()
    assert a.to_json() == b.to_json()


@pytest.mark.parametrize("condition", CONDITIONS)
@pytest.mark.parametrize("budget", [600, 2000, BUDGET])
def test_budget_never_exceeded(snapshot: Snapshot, condition, budget) -> None:
    pack = build_pack(snapshot, condition, budget)
    assert count_tokens(pack.render()) <= budget


@pytest.mark.parametrize("condition", CONDITIONS)
def test_no_label_strings_in_pack(snapshot: Snapshot, condition) -> None:
    text = build_pack(snapshot, condition, BUDGET).render().lower()
    for s in forbidden_strings():
        assert s.lower() not in text, f"{s!r} leaked into the {condition} pack"
    for key in ("fault", "flag"):
        assert str(LABEL[key]).lower() not in text


def test_combined_gives_each_signal_a_third(snapshot: Snapshot) -> None:
    pack = build_pack(snapshot, "combined", 3000)
    assert [s.signal for s in pack.sections] == ["metrics", "traces", "logs"]
    for s in pack.sections:
        assert count_tokens(s.render()) <= 1000
        assert s.lines, f"{s.signal} section is empty"


def test_ids_are_stable_across_conditions(snapshot: Snapshot) -> None:
    alone = build_pack(snapshot, "metrics", BUDGET).evidence_index()
    combined = build_pack(snapshot, "combined", BUDGET).evidence_index()
    shared = set(alone) & set(combined)
    assert shared
    for i in shared:
        assert alone[i] == combined[i]
    assert all(ID_RE.match(i) for i in combined)


def test_metrics_rank_payment_errors_first(snapshot: Snapshot) -> None:
    lines = pack_metrics(snapshot).lines
    assert lines[0].id == "M-0001"
    top = [ln for ln in lines[:6]]
    assert any("payment" in ln.services and "error_ratio" in ln.text for ln in top)
    assert "new:0.5" in next(ln.text for ln in top if "error_ratio" in ln.text)
    healthy = [ln for ln in lines if "product-catalog" in ln.services]
    assert healthy and lines.index(healthy[0]) > 2


def test_traces_show_payment_on_critical_path(snapshot: Snapshot) -> None:
    lines = pack_traces(snapshot).lines
    assert len(lines) == 40
    errored = [ln for ln in lines if " ERROR " in ln.text]
    assert len(errored) >= 20  # slow traces with error spans also count
    assert "payment:" in errored[0].text and errored[0].text.endswith("!")
    assert "payment" in errored[0].services
    assert " ERROR " in lines[0].text
    for ln in lines:
        if "!" in ln.text:
            assert " ERROR " in ln.text, "a trace with error spans must not say ok"


def test_logs_surface_new_payment_errors(snapshot: Snapshot) -> None:
    lines = pack_logs(snapshot).lines
    top = lines[0]
    assert top.services == ("payment",)
    assert "Payment request failed" in top.text
    assert "sev=ERROR" in top.text and "base=0.0/min" in top.text


def test_pack_json_round_trip(snapshot: Snapshot) -> None:
    pack = build_pack(snapshot, "combined", BUDGET)
    again = Pack.from_json(pack.to_json())
    assert again == pack


def test_cli_prints_pack(snapshot_dir, capsys) -> None:
    from rootline_harness.packers.__main__ import main

    assert main([str(snapshot_dir), "--condition", "logs"]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("## LOGS")
    assert "prompt tokens" in out.err
