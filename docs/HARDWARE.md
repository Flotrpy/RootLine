# Hardware guide: the two Arduino UNO Q boards

The hardware arm runs **unattended**: every fault is triggered on the boards
over SSH, so the 12 hardware snapshots run straight after the 30 pilot
snapshots in one night (`controller/deploy/overnight.sh`).

| Board | Role | Name used here |
|-------|------|----------------|
| Board A | Wi-Fi relay for checkout → payment; the radio under test | `affan1` |
| Board B | contention generator (iperf3); optional demo panel | `affan2` |

## The three faults

All three degrade Board A's real Wi-Fi link. `hw/board/rootline-fault`
always schedules its own undo on the board, so a lost SSH connection can
never leave a fault in place.

| Fault | What happens | Undo | Compared with |
|-------|--------------|------|---------------|
| `hwWeakSignal` | Board A's transmit power drops to 1 dBm (`ROOTLINE_HW_TXPOWER_MBM`, default 100 mBm) | power back to auto; the board also reverts by itself after 8 min | `netemLoss` |
| `hwContention` | Board B floods the 2.4 GHz channel with 30 Mbit/s UDP to the PC for 5 min | iperf3 stopped | `toxiLatency` |
| `hwWifiOutage` | Board A's Wi-Fi radio turns off for 30 s, then back on | board checked reachable | `toxiReset` |

`hwWifiOutage` replaces the charter's manual "power cut": the relay loses its
link for 30 s without a person unplugging it. The report calls it a Wi-Fi
outage.

## Decisions

| Question | Decision |
|----------|----------|
| Connected to a computer during the campaign? | No. Both boards on USB-C chargers in fixed spots, on Wi-Fi |
| Which Wi-Fi? | Your home Wi-Fi. Both boards pinned to **2.4 GHz** on the board itself (Stage 2), so contention and the weak link share a band |
| Router settings? | None needed. Boards keep their address in practice; check with `ping` before each session |
| Where does the controller run? | On the PC, inside WSL (Ubuntu), with Docker Desktop |
| iperf3 server | A small container on the PC, started by the overnight script |

## Stage 1: SSH keys from WSL (5 min, once)

The controller logs in to the boards without a password. In WSL:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
```

```bash
ssh-copy-id arduino@192.168.1.250
```

```bash
ssh-copy-id arduino@192.168.1.217
```

Each `ssh-copy-id` asks for that board's password once. Afterwards
`ssh arduino@192.168.1.250 true` must return without asking anything.

## Stage 2: board settings (10 min, once)

From the RootLine checkout in WSL, set the two addresses:

```bash
export A=arduino@192.168.1.250 B=arduino@192.168.1.217
```

Install the fault script and its one sudo rule on Board A:

```bash
scp hw/board/rootline-fault hw/board/rootline.sudoers $A:~
```

```bash
ssh -t $A 'sudo install -m 0755 ~/rootline-fault /usr/local/bin/rootline-fault && sudo install -m 0440 ~/rootline.sudoers /etc/sudoers.d/rootline && sudo visudo -c'
```

`visudo -c` must end with `parsed OK`.

Pin both boards to 2.4 GHz and turn off Wi-Fi power saving (slow, jittery
pings otherwise). This needs NetworkManager, which App Lab's Wi-Fi setup
normally uses; run it for `$A` and then `$B`:

```bash
ssh -t $A 'c=$(nmcli -t -f NAME,TYPE connection show --active | grep 802-11-wireless | cut -d: -f1); sudo nmcli connection modify "$c" 802-11-wireless.band bg 802-11-wireless.powersave 2 && sudo nmcli connection up "$c"; iw dev wlan0 link | grep freq'
```

The connection drops for a few seconds and comes back. The last line must
show a frequency starting with `24` (for example `freq: 2437`). If `nmcli`
is not found, tell us; the faults still work, but contention is weaker if
the boards sit on 5 GHz.

## Stage 3: check (2 min, before every night)

With the demo running in the hardware wiring (the overnight script does this
itself), or any time to check the boards alone:

```bash
export ROOTLINE_BOARD_A=$A ROOTLINE_BOARD_B=$B ROOTLINE_IPERF_SERVER=192.168.1.178
```

```bash
./bin/rootlinectl hw check
```

Every line must say `PASS`. `--outage` also tests a 5 s Wi-Fi outage and
waits for Board A to come back. The iperf3 line only passes while the iperf3
server runs (the overnight script starts it; to test it alone, start it with
the `docker run ... rootline-iperf` line from `controller/deploy/overnight.sh`).

## Stage 4: the night

See `docs/RELEASE.md` and the header of `controller/deploy/overnight.sh`.
The script runs the pilot campaign, switches the demo to the hardware wiring
(`compose.hardware.yml`), starts the iperf3 server, runs `hw check`, and only
then the 12 hardware snapshots. If the check fails it stops and keeps the
pilot data.

Optional: log Board A's radio during the hardware campaign (pyarrow is
already installed in `~/rootline-venv`):

```bash
ssh $A 'nohup ~/rootline-venv/bin/python ~/wifi_logger.py --iface wlan0 --out ~/wifi-hardware.parquet >/dev/null 2>&1 &'
```

## The demo panel (optional, for the launch video)

Wiring and App Lab steps are in `hw/mcu-panel/README.md` and
`hw/bridge-app/README.md`. Never run `rootlinectl serve` during a campaign:
a button press would inject a fault mid-incident.

## Safety

- Contention stays on your own network: `iperf_contention.sh` refuses any
  server outside private address ranges, and the overnight script points it
  at the PC.
- For 5 minutes in each of the 4 contention incidents, other 2.4 GHz devices
  at home will be slow. Run the night when nobody minds.
- The panel cannot trigger hardware faults; the controller refuses them over
  its API.

## Known limits

- The relay sent no telemetry during the campaign (no `edge-relay` spans in
  any hardware snapshot), so hardware snapshots contain the same services as
  emulated ones.
- Lower transmit power degrades the uplink from Board A; the downlink is
  unchanged. It is a real radio impairment, but not the same as moving the
  board away. With the board near the router, `hwWeakSignal` left no visible
  trace in checkout's calls to payment (see `fault_visibility.csv`).
- Contention can make Board B unreachable over SSH until its own flood ends.
  All three hardware faults end by themselves, so a failed clear after the
  snapshot is logged as a note, not a failed incident.
- The fault categories and emulated counterparts are fixed for v0.1 in the
  controller's catalog.
