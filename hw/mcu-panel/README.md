# mcu-panel (Board B microcontroller)

Two buttons and three LEDs for the launch demo. Button presses go over
Arduino Bridge RPC (`Bridge.notify("button_pressed", "fault"|"reset")`) to
the Linux-side bridge app, which calls the controller; the bridge app sets
the LEDs back with `Bridge.call("set_status", "healthy"|"faulty"|"diagnosing")`.

## Build target (recorded for the quality gate)

| Item | Value |
|------|-------|
| FQBN | `arduino:zephyr:unoq` |
| Core | `arduino:zephyr@1.1.0` ("Arduino Q Boards") |
| Library | `Arduino_RouterBridge@0.4.4` (pulls in `Arduino_RPClite`, `MsgPack`) |
| Size | 90,724 bytes flash (11%), 36,496 bytes RAM (13%) |

```bash
arduino-cli core install arduino:zephyr@1.1.0
arduino-cli lib install Arduino_RouterBridge@0.4.4
arduino-cli compile --fqbn arduino:zephyr:unoq --warnings all hw/mcu-panel
```

Upload from Arduino App Lab, or with `arduino-cli upload` on the board.
The debounce and state logic have desktop tests:

```bash
cd hw/mcu-panel/test && g++ -std=c++17 -Wall -Wextra -Werror -I.. debounce_test.cpp -o t && ./t
```

## Wiring

| Part | Pin | Notes |
|------|-----|-------|
| Fault button | D2 → GND | internal pull-up, active low |
| Reset button | D3 → GND | internal pull-up, active low |
| Green LED (healthy) | D5 → 220 Ω → GND | |
| Red LED (faulty) | D6 → 220 Ω → GND | |
| Yellow LED (diagnosing) | D7 → 220 Ω → GND | |

All three LEDs light at power-up until the bridge app reports a state (a
lamp test); if they stay on, the bridge app is not running.

The optional small display for the model's top hypothesis is not wired in
v0.1 (first thing to cut if the schedule slips). The bridge app already
reads the hypothesis from the controller's `/status`.
