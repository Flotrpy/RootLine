"""Demo panel logic for Board B's Linux side, free of board-only imports so
it can be tested anywhere.

Buttons arrive as "fault" or "reset"; the panel calls the Rootline
controller's HTTP API (:8088) and mirrors /status onto the LEDs.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

log = logging.getLogger("rootline.panel")

STATES = ("healthy", "faulty", "diagnosing")
DEFAULTS = {"PANEL_FAULTS": "paymentFailure,toxiReset", "POLL_SECONDS": "1"}


def load_settings(path: Path, env: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Environment first, then the JSON file, then defaults.
    CONTROLLER_URL has no default: the panel cannot guess the PC's IP."""
    from_file: dict[str, str] = {}
    if path.exists():
        from_file = {k: str(v) for k, v in json.loads(path.read_text()).items()}
    out = {}
    for key in ("CONTROLLER_URL", *DEFAULTS):
        value = env.get(key) or from_file.get(key) or DEFAULTS.get(key)
        if not value:
            raise SystemExit(f"{key} is not set: put it in {path.name} or the environment")
        out[key] = value
    return out


class Controller:
    """Minimal client for the controller API (stdlib only, for the board)."""

    def __init__(self, base_url: str, timeout: float = 3.0) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str) -> dict[str, object]:
        req = urllib.request.Request(self.base + path, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise ControllerError(f"{method} {path}: HTTP {e.code}: {body.strip()}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ControllerError(f"{method} {path}: {e}") from e

    def status(self) -> dict[str, object]:
        return self._request("GET", "/status")

    def inject(self, fault: str) -> dict[str, object]:
        return self._request("POST", f"/faults/{fault}")

    def reset(self) -> dict[str, object]:
        return self._request("POST", "/reset")


class ControllerError(Exception):
    pass


class Panel:
    """Buttons in, LEDs out. Thread-safe: Bridge callbacks and the polling
    loop run on different threads."""

    def __init__(
        self,
        controller: Controller,
        set_leds: Callable[[str], object],
        faults: Sequence[str],
        show_hypothesis: Callable[[str], object] | None = None,
    ) -> None:
        if not faults:
            raise ValueError("at least one fault is needed for the fault button")
        self.controller = controller
        self.set_leds = set_leds
        self.faults = list(faults)
        self.show_hypothesis = show_hypothesis
        self._next = 0
        self._lock = threading.Lock()
        self._shown_state: str | None = None
        self._shown_hypothesis: str | None = None

    def on_button(self, which: str) -> None:
        with self._lock:
            try:
                if which == "fault":
                    fault = self.faults[self._next % len(self.faults)]
                    self._next += 1
                    log.info("fault button: injecting %s", fault)
                    self._apply(self.controller.inject(fault))
                elif which == "reset":
                    log.info("reset button")
                    self._apply(self.controller.reset())
                else:
                    log.warning("unknown button %r", which)
            except ControllerError as e:
                # A second press while a fault is active answers 409; the
                # LEDs already show the truth, so just log it.
                log.warning("%s", e)

    def poll(self) -> None:
        with self._lock:
            try:
                self._apply(self.controller.status())
            except ControllerError as e:
                log.warning("controller unreachable: %s", e)

    def _apply(self, status: dict[str, object]) -> None:
        state = str(status.get("state", ""))
        if state in STATES and state != self._shown_state:
            self.set_leds(state)
            self._shown_state = state
        hypothesis = str(status.get("hypothesis") or "")
        if self.show_hypothesis and hypothesis != self._shown_hypothesis:
            self.show_hypothesis(hypothesis)
            self._shown_hypothesis = hypothesis
