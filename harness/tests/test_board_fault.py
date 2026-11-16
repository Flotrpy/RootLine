"""Board A's rootline-fault script, run against stub iw/systemd-run/systemctl."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "hw" / "board" / "rootline-fault"
OVERNIGHT = Path(__file__).parents[2] / "controller" / "deploy" / "overnight.sh"


@pytest.fixture
def stubs(tmp_path):
    log = tmp_path / "calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("iw", "systemd-run", "systemctl"):
        p = bin_dir / name
        p.write_text(f'#!/bin/sh\necho "{name} $*" >> {log}\n')
        p.chmod(0o755)
    return bin_dir, log


def run(stubs, *args: str):
    bin_dir, log = stubs
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env)
    calls = log.read_text().splitlines() if log.exists() else []
    return r, calls


def test_weak_on_sets_power_and_schedules_revert_first(stubs) -> None:
    r, calls = run(stubs, "weak-on", "100")
    assert r.returncode == 0, r.stderr
    revert = next(i for i, c in enumerate(calls) if c.startswith("systemd-run"))
    power = next(i for i, c in enumerate(calls) if "txpower fixed 100" in c)
    assert revert < power, "the safety-net revert must be scheduled before power drops"
    assert "--on-active=480" in calls[revert] and "txpower auto" in calls[revert]


def test_weak_off_restores_and_cancels_revert(stubs) -> None:
    r, calls = run(stubs, "weak-off")
    assert r.returncode == 0
    assert any("txpower auto" in c for c in calls)
    assert any(c.startswith("systemctl stop rootline-weak-revert.timer") for c in calls)


def test_outage_runs_as_a_detached_job(stubs) -> None:
    r, calls = run(stubs, "outage", "30")
    assert r.returncode == 0
    job = "\n".join(calls)  # the job's shell script spans several lines
    assert job.startswith("systemd-run") and "rootline-outage-" in job
    assert "sleep 1" in job and "sleep 30" in job and "nmcli radio wifi on" in job


@pytest.mark.parametrize(
    "args",
    [
        ("weak-on",),
        ("weak-on", "5000"),
        ("weak-on", "abc"),
        ("weak-on", "100", "10"),
        ("outage", "0"),
        ("outage", "999"),
        ("outage", "1;reboot"),
        ("explode",),
        (),
    ],
)
def test_rejects_bad_arguments(stubs, args) -> None:
    r, calls = run(stubs, *args)
    assert r.returncode == 2
    assert not any("txpower fixed" in c or "rootline-outage" in c for c in calls)


def test_overnight_script_parses() -> None:
    assert subprocess.run(["bash", "-n", str(OVERNIGHT)]).returncode == 0


def test_overnight_script_requires_settings() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DEMO_", "ROOTLINE_", "HW_"))}
    r = subprocess.run(["bash", str(OVERNIGHT)], capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "DEMO_DIR" in r.stderr
