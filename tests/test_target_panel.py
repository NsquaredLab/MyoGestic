"""`TargetPanel` connects before it launches, and stops only what it started.

Real connectors over stub targets, real child processes, real frames: the row's
next step happens in `ui`, so every test draws.
"""

import sys
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from myogestic.controls import Capability, ControlLink, ControlLinkConnector, load_control_map
from myogestic.widgets import TargetPanel
from myogestic.widgets.common import DANGER, IDLE, SUCCESS, WARNING
from myogestic.widgets.panels import process_launcher

SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


class _Target:
    """A control target that answers once ``up``, or refuses with ``error``."""

    def __init__(self, *, up: bool = False, error: Exception | None = None) -> None:
        self.up, self.error = up, error

    def capabilities(self):
        if self.error is not None:
            raise self.error
        return [Capability("cursor.x", "continuous", lo=-1.0, hi=1.0)] if self.up else None

    def bind(self, controls) -> None:
        pass

    def send(self, values, changed) -> None:
        pass

    def stop(self) -> None:
        pass


def _spec(argv=SLEEPER, *, refusal: str = ""):
    """`InterfaceSpec`'s shape and nothing more."""

    def launcher():
        if refusal:
            raise FileNotFoundError(refusal)
        return [("Hand", list(argv))]

    return SimpleNamespace(name="Hand", launcher=launcher)


def _connector(target: _Target) -> ControlLinkConnector:
    link = ControlLink(load_control_map({"dofs": {"aim": "cursor.x"}}), [target])
    return ControlLinkConnector(link, retry_s=0.0)


def _until(frame, panel: TargetPanel, predicate, *, timeout_s: float = 3.0) -> None:
    """Draw frames until ``predicate`` holds; the panel advances only while drawn."""
    deadline = monotonic() + timeout_s
    while not predicate():
        assert monotonic() < deadline, "the panel never got there"
        frame(panel.ui)
        sleep(0.005)
    frame(panel.ui)


@pytest.fixture(autouse=True)
def _own_registry(monkeypatch):
    registry: dict = {}
    monkeypatch.setattr(process_launcher, "_procs", registry)
    yield
    for state in registry.values():
        state.stop()


def test_a_target_without_a_connector_is_launched_and_stopped(imgui_frame):
    panel = TargetPanel([_spec()])
    imgui_frame(panel.ui)
    idle = panel._view("Hand")
    assert (idle.tone, idle.words, idle.action) == (IDLE, "Not running", "Launch")

    panel.start("Hand")
    running = panel._view("Hand")
    assert panel.running("Hand")
    assert (running.tone, running.words, running.action) == (SUCCESS, "Running", "Stop")
    assert running.detail.startswith("PID ")
    imgui_frame(panel.ui)

    panel.stop("Hand")
    assert not panel.running("Hand")
    assert panel._view("Hand").words == "Not running"


def test_connect_launches_only_when_nothing_answers_then_binds_it(imgui_frame):
    target = _Target()
    connector = _connector(target)
    panel = TargetPanel([_spec()], connectors={"Hand": connector})
    try:
        assert panel._view("Hand").action == "Connect"
        panel.start("Hand")
        _until(imgui_frame, panel, lambda: panel.running("Hand"))
        waiting = panel._view("Hand")
        assert (waiting.tone, waiting.words) == (WARNING, "Waiting for it to answer")

        target.up = True  # the launched process starts listening
        _until(imgui_frame, panel, lambda: connector.connected)
        bound = panel._view("Hand")
        assert (bound.tone, bound.words, bound.action) == (SUCCESS, "Connected", "Stop")

        panel.stop("Hand")
        _until(imgui_frame, panel, lambda: not connector.connected)
        assert not panel.running("Hand")
        assert panel._view("Hand").words == "Not running"
    finally:
        connector.stop()


def test_a_target_already_running_is_bound_and_never_launched(imgui_frame):
    connector = _connector(_Target(up=True))
    panel = TargetPanel([_spec()], connectors={"Hand": connector})
    try:
        panel.start("Hand")
        _until(imgui_frame, panel, lambda: connector.connected and not panel._rows["Hand"].pending)
        imgui_frame(panel.ui)
        assert not panel.running("Hand")
        bound = panel._view("Hand")
        assert (bound.words, bound.action) == ("Connected", "")  # not this card's to stop
    finally:
        connector.stop()


def test_a_target_that_answers_and_refuses_is_not_launched_over(imgui_frame):
    connector = _connector(_Target(error=RuntimeError("VHI v1.0.0 is too old")))
    panel = TargetPanel([_spec()], connectors={"Hand": connector})
    try:
        panel.start("Hand")
        _until(imgui_frame, panel, lambda: not panel._rows["Hand"].pending)
        assert not panel.running("Hand")
        refused = panel._view("Hand")
        assert (refused.tone, refused.words, refused.action) == (
            DANGER,
            "Connection failed",
            "Retry",
        )
        assert "too old" in refused.detail
    finally:
        connector.stop()


def test_nothing_answering_and_nothing_to_launch_says_so(imgui_frame):
    connector = _connector(_Target())
    refusal = "Hand: not installed here.\n  Run the installer."
    panel = TargetPanel([_spec(refusal=refusal)], connectors={"Hand": connector})
    try:
        assert panel._view("Hand").detail == "cannot launch here"  # known before any press
        panel.start("Hand")
        _until(imgui_frame, panel, lambda: not panel._rows["Hand"].pending)
        failed = panel._view("Hand")
        assert (failed.tone, failed.words, failed.action) == (DANGER, "Nothing answered", "Retry")
        assert panel._rows["Hand"].refusal == refusal  # the row's tooltip
    finally:
        connector.stop()


def test_a_launched_target_that_exits_drops_its_bus_once(imgui_frame):
    target = _Target()
    connector = _connector(target)
    quits = [sys.executable, "-c", "import sys, time; time.sleep(1.0); sys.exit(3)"]
    panel = TargetPanel([_spec(quits)], connectors={"Hand": connector})
    try:
        panel.start("Hand")
        _until(imgui_frame, panel, lambda: panel.running("Hand"))
        target.up = True
        _until(imgui_frame, panel, lambda: connector.connected)
        _until(imgui_frame, panel, lambda: not connector.connected)  # it exited
        exited = panel._view("Hand")
        assert (exited.tone, exited.words, exited.action) == (DANGER, "Exited", "Connect")
        assert exited.detail.startswith("code 3")

        assert connector.poll() is True  # one someone else started answers
        _until(imgui_frame, panel, lambda: connector.connected)
        for _ in range(5):
            imgui_frame(panel.ui)
        assert connector.connected  # and is kept
    finally:
        connector.stop()


def test_mistakes_name_what_to_write():
    with pytest.raises(ValueError, match="own name"):
        TargetPanel([_spec(), _spec()])
    with pytest.raises(ValueError, match="key each by its name"):
        TargetPanel([_spec()], connectors={"VHI": _connector(_Target())})
    with pytest.raises(ValueError, match="No target named 'VHI'"):
        TargetPanel([_spec()]).start("VHI")
