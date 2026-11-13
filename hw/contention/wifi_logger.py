"""Board B: log Wi-Fi signal and throughput at 1 Hz to Parquet.

    python3 wifi_logger.py --iface wlan0 --out wifi-hwContention-r1.parquet

Reads signal strength, frequency and bitrate from `iw dev <iface> link`
and byte counters from /sys/class/net/<iface>/statistics. Rewrites the
Parquet file atomically every --flush seconds and on exit, so a power cut
loses at most one flush interval. Needs pyarrow (pip install pyarrow).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

_SIGNAL = re.compile(r"signal:\s*(-?\d+(?:\.\d+)?)\s*dBm")
_FREQ = re.compile(r"freq:\s*(\d+(?:\.\d+)?)")
_TX = re.compile(r"tx bitrate:\s*(\d+(?:\.\d+)?)\s*MBit/s")


@dataclass
class Sample:
    ts: int  # unix ms
    iface: str
    connected: bool
    rssi_dbm: float | None
    freq_mhz: float | None
    tx_bitrate_mbps: float | None
    rx_bytes: int
    tx_bytes: int
    rx_bps: float | None
    tx_bps: float | None


def parse_iw_link(text: str) -> tuple[bool, float | None, float | None, float | None]:
    """Return (connected, rssi_dbm, freq_mhz, tx_bitrate_mbps)."""
    if "Not connected" in text or "Connected to" not in text:
        return False, None, None, None

    def grab(rx: re.Pattern[str]) -> float | None:
        m = rx.search(text)
        return float(m.group(1)) if m else None

    return True, grab(_SIGNAL), grab(_FREQ), grab(_TX)


def _iw() -> str:
    # Debian installs iw in /usr/sbin, which a normal user's PATH (and a
    # plain SSH session) does not include.
    return shutil.which("iw") or "/usr/sbin/iw"


def read_iw(iface: str) -> str:
    out = subprocess.run([_iw(), "dev", iface, "link"], capture_output=True, text=True, timeout=5)
    return out.stdout


def read_counters(iface: str, root: Path = Path("/sys/class/net")) -> tuple[int, int]:
    stats = root / iface / "statistics"
    return int((stats / "rx_bytes").read_text()), int((stats / "tx_bytes").read_text())


class Logger:
    def __init__(
        self,
        iface: str,
        read_link: Callable[[str], str] = read_iw,
        counters: Callable[[str], tuple[int, int]] = read_counters,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.iface = iface
        self.read_link = read_link
        self.counters = counters
        self.clock = clock
        self.samples: list[Sample] = []
        self._prev: tuple[float, int, int] | None = None

    def sample(self) -> Sample:
        now = self.clock()
        connected, rssi, freq, tx_rate = parse_iw_link(self.read_link(self.iface))
        rx, tx = self.counters(self.iface)
        rx_bps = tx_bps = None
        if self._prev is not None:
            dt = now - self._prev[0]
            # Counters reset if the interface restarts (e.g. after a power cut).
            if dt > 0 and rx >= self._prev[1] and tx >= self._prev[2]:
                rx_bps = (rx - self._prev[1]) * 8 / dt
                tx_bps = (tx - self._prev[2]) * 8 / dt
        self._prev = (now, rx, tx)
        s = Sample(
            int(now * 1000), self.iface, connected, rssi, freq, tx_rate, rx, tx, rx_bps, tx_bps
        )
        self.samples.append(s)
        return s

    def write(self, out: Path) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        schema = pa.schema(
            [
                ("ts", pa.int64()),
                ("iface", pa.string()),
                ("connected", pa.bool_()),
                ("rssi_dbm", pa.float64()),
                ("freq_mhz", pa.float64()),
                ("tx_bitrate_mbps", pa.float64()),
                ("rx_bytes", pa.int64()),
                ("tx_bytes", pa.int64()),
                ("rx_bps", pa.float64()),
                ("tx_bps", pa.float64()),
            ]
        )
        table = pa.Table.from_pylist([asdict(s) for s in self.samples], schema=schema)
        tmp = out.with_suffix(out.suffix + ".tmp")
        pq.write_table(table, tmp, compression="zstd")
        os.replace(tmp, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Log Wi-Fi signal and throughput at 1 Hz to Parquet.")
    ap.add_argument("--iface", default="wlan0")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--duration", type=float, default=0, help="seconds; 0 = until Ctrl-C")
    ap.add_argument("--flush", type=float, default=30)
    args = ap.parse_args(argv)

    logger = Logger(args.iface)
    stop = False

    def handle(_sig: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)
    start = last_flush = time.monotonic()
    while not stop and (args.duration <= 0 or time.monotonic() - start < args.duration):
        try:
            s = logger.sample()
            print(f"{s.ts} rssi={s.rssi_dbm} freq={s.freq_mhz} rx_bps={s.rx_bps}", flush=True)
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            print(f"sample failed: {e}", flush=True)
        if time.monotonic() - last_flush >= args.flush:
            logger.write(args.out)
            last_flush = time.monotonic()
        time.sleep(1)
    logger.write(args.out)
    print(f"wrote {len(logger.samples)} samples to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
