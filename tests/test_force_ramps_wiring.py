"""What the flagship example claims on a fresh launch.

Every one of these was got wrong at least once: a panel reading another panel's
stream, a stream showing itself connected that nobody connected, and a device
dropdown naming something its stream was never attached to.
"""

import runpy
from pathlib import Path

import pytest

import myogestic.core

_APP = Path(__file__).resolve().parent.parent / "examples" / "start_here" / "force_ramps.py"


@pytest.fixture
def app_module(monkeypatch):
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    monkeypatch.syspath_prepend(str(_APP.parent))
    return runpy.run_path(str(_APP), run_name="__main__")


def test_nothing_but_the_target_attaches_itself(app_module):
    """"Nothing attaches on its own" is the project's rule, and a green stream
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
