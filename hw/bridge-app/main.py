"""Board B Linux-side app (Arduino App Lab): bridges the MCU panel to the
Rootline controller.

Environment:
  CONTROLLER_URL  e.g. http://192.168.1.20:8088 (required)
  PANEL_FAULTS    comma-separated faults the fault button cycles through
                  (default: paymentFailure,toxiReset)
  POLL_SECONDS    status polling interval (default 1)
"""

from __future__ import annotations

import logging
import os
import time

from arduino.app_utils import App, Bridge  # available on the UNO Q only
from panel import Controller, Panel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

controller = Controller(os.environ["CONTROLLER_URL"])
faults = [f.strip() for f in os.environ.get("PANEL_FAULTS", "paymentFailure,toxiReset").split(",")]
poll_seconds = float(os.environ.get("POLL_SECONDS", "1"))

panel = Panel(
    controller,
    set_leds=lambda state: Bridge.call("set_status", state),
    faults=[f for f in faults if f],
    show_hypothesis=lambda h: logging.info("top hypothesis: %s", h or "(none)"),
)

Bridge.provide("button_pressed", panel.on_button)


def loop() -> None:
    panel.poll()
    time.sleep(poll_seconds)


App.run(user_loop=loop)
