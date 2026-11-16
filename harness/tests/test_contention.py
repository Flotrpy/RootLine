"""Board B contention script and Wi-Fi logger (hw/contention)."""

import os
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from wifi_logger import Logger, parse_iw_link, read_counters

SCRIPT = Path(__file__).parents[2] / "hw" / "contention" / "iperf_contention.sh"

IW_CONNECTED = """Connected to aa:bb:cc:dd:ee:ff (on wlan0)
\tSSID: rootline-lab
\tfreq: 2437.0
\tRX: 123456 bytes (789 packets)
\tTX: 65432 bytes (321 packets)
\tsignal: -78 dBm
\trx bitrate: 65.0 MBit/s
\ttx bitrate: 72.2 MBit/s MCS 7 short GI
"""


def test_parse_iw_link() -> None:
    assert parse_iw_link(IW_CONNECTED) == (True, -78.0, 2437.0, 72.2)
    assert parse_iw_link("Not connected.") == (False, None, None, None)
    assert parse_iw_link("") == (False, None, None, None)


def test_read_counters(tmp_path) -> None:
    stats = tmp_path / "wlan0" / "statistics"
    stats.mkdir(parents=True)
    (stats / "rx_bytes").write_text("1000\n")
    (stats / "tx_bytes").write_text("500\n")
    assert read_counters("wlan0", tmp_path) == (1000, 500)


def test_logger_rates_reset_and_parquet(tmp_path) -> None:
    t = [100.0]
    counters = iter([(0, 0), (125_000, 12_500), (10, 10)])  # third: interface restarted
    log = Logger(
        "wlan0",
        read_link=lambda _i: IW_CONNECTED,
        counters=lambda _i: next(counters),
        clock=lambda: t[0],
    )
    first = log.sample()
    t[0] += 1
    second = log.sample()
    t[0] += 1
    third = log.sample()
    assert first.rx_bps is None
    assert second.rx_bps == pytest.approx(1_000_000) and second.tx_bps == pytest.approx(100_000)
    assert third.rx_bps is None  # counter reset: no bogus negative rate
    out = tmp_path / "wifi.parquet"
    log.write(out)
    table = pq.read_table(out)
    assert table.num_rows == 3
    assert table.column("rssi_dbm").to_pylist() == [-78.0] * 3
    assert not (tmp_path / "wifi.parquet.tmp").exists()


def run_script(server: str, tmp_path, **env: str) -> subprocess.CompletedProcess[str]:
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "iperf3").write_text('#!/bin/sh\necho "iperf3 $*"\n')
    (fake / "iperf3").chmod(0o755)
    full_env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "IPERF_SERVER": server, **env}
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=full_env)


@pytest.mark.parametrize("server", ["192.168.1.20", "10.0.0.5", "172.16.0.1", "172.31.255.254"])
def test_script_runs_against_private_servers(server, tmp_path) -> None:
    r = run_script(server, tmp_path, BITRATE="20M", DURATION="60")
    assert r.returncode == 0, r.stderr
    assert f"iperf3 --client {server} --udp --bitrate 20M --time 60" in r.stdout


@pytest.mark.parametrize(
    "server", ["8.8.8.8", "172.32.0.1", "192.169.1.1", "300.1.1.1", "lab.local"]
)
def test_script_refuses_public_or_invalid_servers(server, tmp_path) -> None:
    r = run_script(server, tmp_path)
    assert r.returncode == 2 and "refusing" in r.stderr
    assert "iperf3 --client" not in r.stdout


@pytest.mark.parametrize(
    ("env", "msg"), [({"DURATION": "5000"}, "DURATION"), ({"BITRATE": "fast"}, "BITRATE")]
)
def test_script_validates_parameters(env, msg, tmp_path) -> None:
    r = run_script("192.168.1.20", tmp_path, **env)
    assert r.returncode == 2 and msg in r.stderr
