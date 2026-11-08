# bridge-app (Board B Linux side)

Runs on the UNO Q's Linux side under Arduino App Lab, next to the
`mcu-panel` sketch. Fault and reset presses arrive over Bridge RPC and
become controller API calls; every second it reads `/status` and sets the
LEDs (`healthy`, `faulty`, `diagnosing`).

| Variable | Default | Meaning |
|----------|---------|---------|
| `CONTROLLER_URL` | (required) | e.g. `http://192.168.1.20:8088` |
| `PANEL_FAULTS` | `paymentFailure,toxiReset` | faults the fault button cycles through |
| `POLL_SECONDS` | `1` | status polling interval |

The controller must listen on the LAN for the board to reach it:
`./bin/rootlinectl serve --addr 0.0.0.0:8088`. Only emulated faults can be
triggered from the panel: the controller refuses hardware faults, which
need an operator.

`panel.py` has no board-only imports; its tests live in
`harness/tests/test_bridge_app.py`. Only `main.py` imports `arduino.app_utils`.
