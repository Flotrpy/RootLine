"""Board B bridge app logic (hw/bridge-app/panel.py)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from panel import Controller, ControllerError, Panel


class FakeController:
    def __init__(self) -> None:
        self.state = "healthy"
        self.hypothesis = ""
        self.calls: list[str] = []

    def status(self) -> dict[str, object]:
        return {"state": self.state, "hypothesis": self.hypothesis}

    def inject(self, fault: str) -> dict[str, object]:
        self.calls.append(f"inject {fault}")
        if self.state != "healthy":
            raise ControllerError("POST /faults: HTTP 409")
        self.state = "faulty"
        return self.status()

    def reset(self) -> dict[str, object]:
        self.calls.append("reset")
        self.state = "healthy"
        return self.status()


def make_panel(**kw):
    ctrl = FakeController()
    leds: list[str] = []
    hyps: list[str] = []
    panel = Panel(ctrl, leds.append, kw.get("faults", ["paymentFailure", "toxiReset"]), hyps.append)  # type: ignore[arg-type]
    return panel, ctrl, leds, hyps


def test_buttons_cycle_faults_and_reset() -> None:
    panel, ctrl, leds, _ = make_panel()
    panel.on_button("fault")
    panel.on_button("reset")
    panel.on_button("fault")
    assert ctrl.calls == ["inject paymentFailure", "reset", "inject toxiReset"]
    assert leds == ["faulty", "healthy", "faulty"]


def test_second_fault_press_is_harmless() -> None:
    panel, _ctrl, leds, _ = make_panel()
    panel.on_button("fault")
    panel.on_button("fault")  # 409 from the controller: logged, no crash
    assert leds == ["faulty"]


def test_poll_only_updates_on_change() -> None:
    panel, ctrl, leds, hyps = make_panel()
    panel.poll()
    panel.poll()
    ctrl.state, ctrl.hypothesis = "diagnosing", ""
    panel.poll()
    ctrl.state, ctrl.hypothesis = "faulty", "payment / error"
    panel.poll()
    assert leds == ["healthy", "diagnosing", "faulty"]
    assert hyps == ["", "payment / error"]


def test_unknown_state_and_button_are_ignored() -> None:
    panel, ctrl, leds, _ = make_panel()
    ctrl.state = "exploded"
    panel.poll()
    panel.on_button("self-destruct")
    assert leds == [] and ctrl.calls == []


def test_needs_a_fault() -> None:
    with pytest.raises(ValueError):
        Panel(FakeController(), print, [])  # type: ignore[arg-type]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._reply(200, {"state": "healthy"})

    def do_POST(self) -> None:
        if self.path == "/faults/hwPowerCut":
            self._reply(403, {"error": "manual faults need an operator"})
        else:
            self._reply(200, {"state": "faulty" if "faults" in self.path else "healthy"})

    def _reply(self, code: int, body: dict[str, str]) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass


def test_controller_client_against_http() -> None:
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = Controller(f"http://127.0.0.1:{srv.server_port}/")
        assert c.status() == {"state": "healthy"}
        assert c.inject("paymentFailure")["state"] == "faulty"
        assert c.reset()["state"] == "healthy"
        with pytest.raises(ControllerError, match="HTTP 403"):
            c.inject("hwPowerCut")
    finally:
        srv.shutdown()
    with pytest.raises(ControllerError):
        Controller("http://127.0.0.1:1", timeout=0.5).status()


def test_load_settings_order(tmp_path) -> None:
    from panel import load_settings

    cfg = tmp_path / "rootline.json"
    cfg.write_text(json.dumps({"CONTROLLER_URL": "http://file:8088", "POLL_SECONDS": "2"}))
    s = load_settings(cfg, env={"POLL_SECONDS": "5"})
    assert s == {
        "CONTROLLER_URL": "http://file:8088",
        "PANEL_FAULTS": "paymentFailure,toxiReset",
        "POLL_SECONDS": "5",
    }
    with pytest.raises(SystemExit, match="CONTROLLER_URL"):
        load_settings(tmp_path / "missing.json", env={})
