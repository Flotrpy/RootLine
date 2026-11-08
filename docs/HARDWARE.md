# Hardware guide: the two Arduino UNO Q boards

This is the complete, in-order guide for Phase 3. Read "The plan" once,
then follow the stages. Commands assume the laptop is the machine running
the OpenTelemetry Demo and that you are in the RootLine checkout.

## The plan (decisions already made)

| Question | Decision | Why |
|----------|----------|-----|
| Set up both boards at once? | **No: first-time setup one board at a time**, then both run together | Out of the box both boards look identical over USB and on the network; one at a time means you never configure the wrong one |
| Same computer or two? | **One computer is enough.** A second computer only helps if you set the boards up during the overnight campaign (see "When") | Board setup is light work, but compiling on the demo laptop during a campaign adds latency noise to the snapshots |
| Connected to a computer during the campaign? | **No.** After setup both boards run on their own power over Wi-Fi | Board A must be unplugged (power cut) and carried around (weak signal) |
| How is Board A powered? | **A USB-C power bank** (or a long cable to a wall charger) | You carry it to the weak-signal spot and unplug it for the power cut |
| How is Board B powered? | Any USB-C charger, near the laptop | It stays put; its panel is for the demo video |
| Which Wi-Fi? | **Both boards on a 2.4 GHz-only lab SSID for the whole hardware campaign.** The laptop on Ethernet, or on 5 GHz | Contention only works on a shared channel. Switching bands mid-incident would make Board A reconnect, which looks like an extra fault |
| IP addresses | **Reserve fixed IPs (DHCP reservation) for the laptop and Board A** | After the power cut Board A reboots; if its IP changed, checkout could no longer reach it |
| iperf3 server | **The laptop** (`iperf3 --server`) | Saves a device; the contention happens on the air between Board B and the router |
| Wi-Fi logger | **On Board A** (the radio under test), plus Board B during contention if you like | Board A's link is what the faults degrade |

## When to do each stage

The stages overlap with the rest of the project like this:

1. **Saturday, before the overnight campaign, or Sunday morning:** Stages
   1–4 (prepare the network, set up both boards, install the relay and the
   panel). These touch only the boards. Avoid compiling on the demo laptop
   *while the overnight campaign runs*; Sunday morning is ideal because the
   model runs (Kaggle, Cerebras, Groq) do not need the demo running.
2. **Only after the overnight campaign and the 15 remediation trials are
   finished:** Stage 5 (switch the demo to the hardware wiring) and Stage 6
   (the 12 hardware snapshots, about 2.6 hours with you at the keyboard).
   The hardware wiring replaces the emulated checkout → payment route, so it
   must never overlap those runs.
3. **After the hardware campaign:** Stage 7 (score the new snapshots) and
   Stage 8 (the demo video, optional).

## What you need

- Both UNO Q boards, each with a USB-C cable
- A USB-C power bank for Board A, and a USB-C charger for Board B
- A Wi-Fi router where you can create a **2.4 GHz-only SSID** (a guest
  network or a travel router works) and reserve DHCP addresses
- For the panel: a breadboard, 2 push buttons, 3 LEDs (green, red, yellow),
  3 × 220 Ω resistors, about 8 jumper wires
- On the laptop: Arduino App Lab, Go (for `make build`), `iperf3`
- Tape and a pen to label the boards **A** and **B**

## Stage 1: prepare the network (15 min)

1. On the router, create an SSID for the lab, for example `rootline-lab-24`,
   on **2.4 GHz only**. Use a fixed channel (1, 6 or 11) so contention is
   reproducible, and keep other devices off it.
2. Connect the laptop by Ethernet if you can; otherwise to the router's
   5 GHz network. Note its IP: this is `HW_LAN_BIND` (for example
   `192.168.1.20`).
3. Reserve that IP for the laptop in the router's DHCP settings.
4. Allow incoming connections on the laptop from the LAN on these ports:
   `50051` (payment, or the demo's `PAYMENT_PORT`), `4318` (snapshotter),
   `8088` (controller, for the panel) and `5201` (iperf3).
5. Turn off sleep on the laptop for the campaign days.

## Stage 2: first-time setup, one board at a time (20–40 min per board)

Do Board A completely, then Board B.

1. Label the board (A or B). Connect **only this board** to the laptop with
   USB-C.
2. Open Arduino App Lab and follow its first-run setup for the board:
   - give it a name: `rootline-a` for Board A, `rootline-b` for Board B;
   - set a password for the Linux user (App Lab shows the user name,
     usually `arduino`);
   - join the `rootline-lab-24` Wi-Fi;
   - install any updates it offers. This can take a while; let it finish.
3. In the router, find the board (by its name or MAC address) and **reserve
   its IP**. Note Board A's IP: this is `HW_RELAY_ADDR`'s host (for example
   `192.168.1.50`).
4. Check you can reach the board's Linux side from the laptop:

   ```bash
   ssh arduino@192.168.1.50
   ```

   If SSH is not available, App Lab's terminal or `adb shell` over USB also
   work; use whichever App Lab offers for copying files in the next stages.
5. On the board, install the tools the scripts need:

   ```bash
   sudo apt update && sudo apt install -y iw iperf3 python3-venv
   ```

   ```bash
   python3 -m venv ~/rootline-venv && ~/rootline-venv/bin/pip install pyarrow
   ```

6. Unplug the board from the laptop. Repeat for the other board.

## Stage 3: Board A, the relay (15 min)

1. On the laptop, build the arm64 binary:

   ```bash
   make build
   ```

   This writes `bin/edge-relay-arm64`.
2. Copy the relay files and the logger to Board A:

   ```bash
   scp bin/edge-relay-arm64 hw/edge-relay/edge-relay.service hw/edge-relay/edge-relay.env.example hw/contention/wifi_logger.py arduino@192.168.1.50:~
   ```

3. On Board A:

   ```bash
   sudo install -m 0755 ~/edge-relay-arm64 /usr/local/bin/edge-relay
   ```

   ```bash
   sudo mkdir -p /etc/rootline && sudo cp ~/edge-relay.env.example /etc/rootline/edge-relay.env
   ```

   Edit `/etc/rootline/edge-relay.env` and put the **laptop's** IP in both
   `UPSTREAM_ADDR` and `OTLP_ENDPOINT` (keep the ports; use the demo's
   `PAYMENT_PORT` if it is not 50051). Then:

   ```bash
   sudo cp ~/edge-relay.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now edge-relay
   ```

   ```bash
   systemctl status edge-relay
   ```

   It should say `active (running)`. It stays enabled, so it starts by
   itself after every reboot, including the power cut.
4. Move Board A to its **normal spot**: on the power bank, 2–3 m from the
   router with a clear line of sight. Find a **weak-signal spot** too:
   another room, behind a wall, or inside a metal biscuit tin with the lid
   resting on the cable. Check RSSI there:

   ```bash
   iw dev wlan0 link
   ```

   You want `signal:` between -75 and -85 dBm while still connected. Mark
   both spots so every replica uses the same ones.

## Stage 4: Board B, the panel (30 min)

1. **With Board B unpowered**, wire the breadboard (see
   `hw/mcu-panel/README.md`):
   - fault button between **D2** and **GND**; reset button between **D3**
     and **GND** (on 4-leg buttons, use two diagonal legs);
   - each LED: **D5** (green), **D6** (red), **D7** (yellow) → 220 Ω
     resistor → LED long leg; LED short leg (flat side) → **GND**.
   The pins are 3.3 V logic: never connect a signal pin to 5 V.
2. Power Board B from its charger, and open it in App Lab over the network
   (or USB). Create a new app, for example `rootline-panel`:
   - **sketch part:** copy in `hw/mcu-panel/mcu-panel.ino`, `debounce.h`
     and `status.h` (if App Lab asks for a library, add
     `Arduino_RouterBridge`);
   - **Python part:** copy in `hw/bridge-app/main.py` and `panel.py`, plus a
     `rootline.json` made from `rootline.json.example` with the laptop's IP.
3. Run the app. All three LEDs light first (lamp test) and stay on until
   the controller answers. That is expected: the controller is started only
   for the panel check and the demo, never during a campaign.
4. Copy the contention script to Board B:

   ```bash
   scp hw/contention/iperf_contention.sh hw/contention/wifi_logger.py arduino@192.168.1.51:~
   ```

5. Panel check, any time the demo is up with its normal wiring:

   ```bash
   ./bin/rootlinectl serve --addr 0.0.0.0:8088
   ```

   Green lights. Press the fault button: red lights and the shop starts
   failing. Press reset: green again. Stop `serve` (Ctrl-C) afterwards.

## Stage 5: switch the demo to the hardware wiring (10 min)

Only after the overnight campaign and the remediation trials are done.

1. Stop any `rootlinectl serve`, and do not run it during the campaign
   (a panel press would inject a fault mid-incident).
2. From the demo checkout:

   ```bash
   export ROOTLINE_DIR=/path/to/RootLine HW_LAN_BIND=192.168.1.20 HW_RELAY_ADDR=192.168.1.50:50051
   ```

   ```bash
   docker compose -f docker-compose.yml -f "$ROOTLINE_DIR/compose.override.yml" -f "$ROOTLINE_DIR/compose.hardware.yml" up -d
   ```

3. Check traffic flows through the board: on Board A,
   `journalctl -u edge-relay -f` shows connections, and the shop works.
4. Start the iperf3 server on the laptop, and leave it running:

   ```bash
   iperf3 --server
   ```

## Stage 6: the 12 hardware snapshots (about 2.6 hours, stay at the keyboard)

1. Put Board A at its normal spot on the power bank, Board B on its charger,
   both on `rootline-lab-24`.
2. On Board A, start the Wi-Fi logger in its own terminal:

   ```bash
   ~/rootline-venv/bin/python ~/wifi_logger.py --iface wlan0 --out ~/wifi-hardware.parquet
   ```

3. On the laptop:

   ```bash
   ./bin/rootlinectl campaign --plan plans/hardware.yaml
   ```

4. The order of the 12 incidents is shuffled. For each one the controller
   prints exactly what to do, waits for Enter, and logs the time to
   `data/hw/operator-log.jsonl`. **Press Enter the moment the fault is
   live**, because that moment becomes the incident's T0:

   | Fault | When the prompt appears | When the clear prompt appears |
   |-------|------------------------|-------------------------------|
   | hwWeakSignal | carry Board A to the weak spot; press Enter once RSSI holds at -75 to -85 dBm | bring it back to the normal spot |
   | hwContention | on Board B run `IPERF_SERVER=192.168.1.20 DURATION=300 ./iperf_contention.sh`; press Enter at its first output line | check it finished |
   | hwPowerCut | unplug Board A **and press Enter at the same moment**; plug it back in after 30 s (phone timer) | check `systemctl status edge-relay`, then restart the logger |

5. Ctrl-C is safe: the fault is cleared and a rerun resumes where it
   stopped. A step you could not do properly is better redone: stop, and
   ask before deleting any snapshot.
6. Afterwards, copy the logger output to the laptop as
   `data/hw/hardware-boardA-wifi.parquet`.

## Stage 7: score and compare

Run the models on the 12 new snapshots as for the others (`run enqueue`,
`run work`, `run export`), then:

```bash
make reproduce
```

`paper/figures/emulation_validity.csv` compares each real fault with its
emulated counterpart (weak signal ↔ packet loss, contention ↔ latency,
power cut ↔ connection resets).

## Stage 8: the demo video (optional)

With the demo on its normal wiring and `rootlinectl serve` running: press
the fault button (red LED, the shop breaks), then mark the diagnosis:

```bash
curl -X POST http://localhost:8088/diagnosis -d '{"diagnosing": true}'
```

(yellow LED), run a model on a snapshot of the same fault
(`./bin/rootline replay ... --model ollama/<name>`), and post its top
hypothesis:

```bash
curl -X POST http://localhost:8088/diagnosis -d '{"hypothesis": "payment / error"}'
```

The bridge app logs the hypothesis; the small display is not wired in v0.1.

## Safety

- Contention only on your own network: `iperf_contention.sh` refuses any
  server outside private address ranges.
- The panel can only inject emulated faults; the controller refuses
  hardware faults over the API.
- Never switch on an appliance you use as a shield; a closed metal tin is
  enough.

## Known limits

- Hardware snapshots contain the `edge-relay` service, which emulated
  snapshots do not: extra evidence for models on hardware faults.
- The categories of the three real faults, and their emulated counterparts,
  are still marked `TODO(flotrpy)` in the controller's catalog.
