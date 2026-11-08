# Hardware runbook (Phase 3)

Two Arduino UNO Q boards. Board A relays checkout → payment over real
Wi-Fi; Board B makes controlled contention and runs the demo panel.
Everything here runs on your own isolated lab network.

## What you need

- Both UNO Q boards, USB-C power, the laptop running the demo
- For the panel: 2 push buttons, 3 LEDs (green, red, yellow), 3 × 220 Ω
  resistors, jumper wires
- A machine on the same network running `iperf3 --server`
- The laptop's LAN IP (`HW_LAN_BIND`) and Board A's IP (`HW_RELAY_ADDR`)

## 1. Board A: edge relay

On the laptop:

```bash
make build    # also writes bin/edge-relay-arm64
```

Copy `bin/edge-relay-arm64` (as `edge-relay`), `hw/edge-relay/edge-relay.service`
and `hw/edge-relay/edge-relay.env.example` to Board A, then follow
`hw/edge-relay/README.md` (install, edit the two IPs, enable the service).

## 2. Laptop: route checkout through Board A

```bash
export ROOTLINE_DIR=/path/to/RootLine HW_LAN_BIND=192.168.1.20 HW_RELAY_ADDR=192.168.1.50:50051
docker compose -f docker-compose.yml -f "$ROOTLINE_DIR/compose.override.yml" -f "$ROOTLINE_DIR/compose.hardware.yml" up -d
```

Check the shop still works, and that `journalctl -u edge-relay -f` on Board A
shows connections.

## 3. Board B: panel and contention

1. Wire the buttons and LEDs as in `hw/mcu-panel/README.md`.
2. Upload `hw/mcu-panel` from Arduino App Lab (FQBN `arduino:zephyr:unoq`).
   All three LEDs light until the bridge app runs.
3. Add `hw/bridge-app` to an App Lab app with `CONTROLLER_URL=http://<laptop>:8088`.
4. On the laptop: `./bin/rootlinectl serve --addr 0.0.0.0:8088`. The LEDs
   should switch to green.
5. Copy `hw/contention/` to Board B and install pyarrow for the logger.

Panel check: press the fault button, the red LED lights and the shop
breaks; press reset, green comes back.

## 4. Collect the 12 hardware snapshots

Start the Wi-Fi logger (see `hw/contention/README.md`), then:

```bash
./bin/rootlinectl campaign --plan plans/hardware.yaml
```

Stay at the keyboard. For each incident the controller prints exactly what
to do (move Board A, start contention, cut power for 30 s), waits for you
to press Enter, and logs the time to `data/hw/operator-log.jsonl`. The
snapshot window starts when you confirm. About 2.6 hours in total; Ctrl-C
is safe and the campaign resumes where it stopped.

## 5. Score and compare

Run the models on the 12 new snapshots like the others, then
`make reproduce` writes `paper/figures/emulation_validity.csv`: accuracy on
each real fault next to its emulated counterpart (weak signal ↔ packet
loss, contention ↔ latency, power cut ↔ connection resets).

## Safety

- Contention only on your own network: `iperf_contention.sh` refuses any
  server outside private address ranges.
- `rootlinectl` never triggers a physical fault remotely; the panel can only
  inject emulated faults.

## Known limits

- Hardware snapshots contain the `edge-relay` service, which emulated
  snapshots do not (Toxiproxy is not instrumented). This gives the models
  extra evidence on hardware faults.
- The categories for the three real faults, and their emulated
  counterparts, are marked `TODO(flotrpy)` in the controller's catalog.
