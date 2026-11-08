# contention (Board B Linux side)

**Safety:** only ever create contention on your own network and channel.
`iperf_contention.sh` refuses any iperf3 server outside private address
ranges. Keep both boards on an isolated home-lab SSID.

## hwContention

Both boards stay on the 2.4 GHz-only lab SSID for the whole hardware
campaign (see `docs/HARDWARE.md`), so nothing is switched mid-incident.

1. Start an iperf3 server on the laptop: `iperf3 --server`.
2. On Board B, when `rootlinectl` prompts you:

```bash
IPERF_SERVER=192.168.1.20 BITRATE=30M DURATION=300 ./iperf_contention.sh
```

## Wi-Fi logger

The charter runs it on Board B during every hardware incident; running a
second copy on Board A records the relay's own radio, which is what
hwWeakSignal actually degrades. It writes 1 Hz Parquet: RSSI, frequency,
bitrate and rx/tx throughput.

```bash
python3 -m venv ~/rootline-venv && ~/rootline-venv/bin/pip install pyarrow
~/rootline-venv/bin/python wifi_logger.py --iface wlan0 --out wifi-hardware.parquet
```

Copy the file to `data/hw/<incident>-<board>-wifi.parquet` on the laptop.
Snapshot folders stay exactly as the snapshotter wrote them, and the
logger's data is never shown to models: it documents the fault.
