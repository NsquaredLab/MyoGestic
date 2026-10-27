"""What the flagship example claims on a fresh launch.

Every one of these was got wrong at least once: a panel reading another panel's
stream, a stream showing itself connected that nobody connected, and a device
dropdown naming something its stream was never attached to.
"""

import runpy
from pathlib import Path

import pytest
from imgui_bundle import imgui

import myogestic.core
from myogestic.session import Session
from myogestic.widgets import ParticipantPanel
from myogestic.widgets.training._session_state import SessionWidgetState, _states

_APP = Path(__file__).resolve().parent.parent / "examples" / "start_here" / "force_ramps.py"


@pytest.fixture
def app_module(monkeypatch):
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    monkeypatch.syspath_prepend(str(_APP.parent))
    return runpy.run_path(str(_APP), run_name="__main__")


def test_force_ramps_requires_participant(app_module):
    assert app_module["app"].ctx.require_participant is True


def test_force_ramps_constructs_participant_panel(app_module):
    assert isinstance(app_module["participant"], ParticipantPanel)


@pytest.mark.parametrize("participant_id", ["", "P-014"])
def test_force_ramps_renders_participant(
    app_module, implot_frame, monkeypatch, tmp_path, participant_id
):
    """The participant selector is visible on the first frame, before Record."""
    app = app_module["app"]
    app.ctx.participant = participant_id
    rendered = []
    original_ui = ParticipantPanel.ui

    def draw_participant(self, ctx):
        self._key_file = tmp_path / "participant-key.csv"
        rendered.append(ctx)
        original_ui(self, ctx)

    monkeypatch.setattr(ParticipantPanel, "ui", draw_participant)
    implot_frame(lambda: app._ui_fn(app.ctx))

    assert rendered == [app.ctx]


def test_force_ramps_sessions_follow_participant(app_module, implot_frame, monkeypatch, tmp_path):
    """Scan finds labelled takes, and switching participants clears the old selection."""
    monkeypatch.chdir(tmp_path)
    app = app_module["app"]
    selections = []
    manager = app_module["sessions"]
    original_ui = manager.ui

    def capture_selection(*args, **kwargs):
        data = original_ui(*args, **kwargs)
        selections.append(data)
        return data

    monkeypatch.setattr(manager, "ui", capture_selection)
    state = SessionWidgetState()
    monkeypatch.setitem(_states, app_module["sessions"]._widget_id, state)
    paths = []
    for participant_id in ("P-014", "P-015"):
        take = Session(participant=participant_id)
        take.save_meta("force ramps")
        paths.append(str(take.pack_to_zip().resolve()))

    scan = False
    button = imgui.button

    def click_scan(label, *args, **kwargs):
        clicked = button(label, *args, **kwargs)
        return (scan and label.startswith("Scan folder##")) or clicked

    monkeypatch.setattr(imgui, "button", click_scan)
    app.ctx.participant = "P-014"
    scan = True
    implot_frame(lambda: app._ui_fn(app.ctx))
    assert [row["path"] for row in state.sessions] == paths[:1]
    state.sessions[0]["selected"] = True

    app.ctx.participant = "P-015"
    scan = False
    implot_frame(lambda: app._ui_fn(app.ctx))
    assert [row["path"] for row in state.sessions] == paths[1:]
    assert all(row["participant"] == "P-015" for row in state.sessions)
    assert not any(row["selected"] for row in state.sessions)
    assert selections[-1].paths == []

    scan = True
    implot_frame(lambda: app._ui_fn(app.ctx))
    assert [row["path"] for row in state.sessions] == paths[1:]


def test_nothing_but_the_target_attaches_itself(app_module):
    """ "Nothing attaches on its own" is the project's rule, and a green stream
    the operator never connected reads as the app having done something behind
    them.

    The target is the one exception, and only because `start_recording` sizes a
    Zarr array per *attached* stream: a target that went live when a block
    started would never be in the take.
    """
    ctx = app_module["app"].ctx
    attached = {name for name, s in ctx.streams.items() if s._connected}
    assert attached == {"target"}, f"connected without being asked: {attached - {'target'}}"


def test_the_force_panel_reads_a_force_stream_not_the_emg_one(app_module):
    """Wired to `emg`, connecting an amplifier lit up the Force panel — one
    panel visibly changing another for a signal it has nothing to do with."""
    task = app_module["tracking"]
    assert task._stream_name == "force"
    assert task._stream_name in app_module["app"].ctx.streams


def test_the_picker_does_not_offer_the_task_s_own_target(app_module):
    """One Connect there replaces the `TargetSource` the task is driving."""
    picker = app_module["device"]
    ctx = app_module["app"].ctx
    offered = {n for n in ctx.streams if n not in picker._excluded}
    assert "target" not in offered
    assert {"emg", "force"} <= offered


def test_the_target_stream_carries_the_source_the_task_drives(app_module):
    """Otherwise the task writes to something attached to nothing, and the
    recording holds the wrong data under the name `target`."""
    ctx = app_module["app"].ctx
    task_target = app_module["target"]
    assert ctx.streams["target"]._source is task_target
