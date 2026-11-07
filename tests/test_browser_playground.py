"""Exercise the shipped playground callbacks without starting a GUI or threads."""

import runpy
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from myogestic import App
from myogestic import _browser as browser
from myogestic import stream as stream_module
from myogestic.ml import pipeline as pipeline_module


@pytest.fixture
def playground(monkeypatch):
    # These are the flags derived from sys.platform == "emscripten" in Pyodide.
    # Keep CPython's real platform so NumPy/sklearn can load their native wheels.
    monkeypatch.setattr(browser, "IS_BROWSER", True)
    monkeypatch.setattr(browser, "_scheduler", browser._BrowserScheduler())
    monkeypatch.setattr(stream_module, "_IS_BROWSER", True)
    monkeypatch.setattr(pipeline_module, "_IS_BROWSER", True)
    monkeypatch.setattr(App, "run", lambda *a, **kw: None)

    def no_threads(*args, **kwargs):
        raise AssertionError("Pyodide cannot start threads")

    monkeypatch.setattr(threading.Thread, "start", no_threads)
    monkeypatch.setitem(
        sys.modules, "js",
        SimpleNamespace(window=SimpleNamespace(innerWidth=1440, innerHeight=900)),
    )
    path = Path(__file__).resolve().parents[1] / "docs/playground/app.py"
    return runpy.run_path(str(path))


def test_browser_record_callback_keeps_take_active_until_stop(playground):
    """The real callbacks must satisfy the same take contract as App.start_recording."""
    ctx = playground["app"].ctx
    controls = playground["rec_controls"]
    controls._start(ctx)
    controls.ui(ctx, visible=False)

    # Before the fix the callback changed state but not this flag; _begin_recording
    # immediately reset the take to idle and the UI disabled Record forever.
    assert ctx.recording
    assert ctx.state == "recording"
    assert controls.take.phase == "recording"
    assert ctx.session is None  # in-memory capture never opens threaded zarr

    stream = playground["stream"]
    stream.start()
    stream._acquire_step()  # fill a window before the sampler's first due tick
    browser.tick_all()
    assert playground["recorded_X"]
    assert playground["recorded_y"] == [0]

    controls._machine.stop()
    assert not ctx.recording
    assert ctx.state == "idle"
    assert controls.take.phase == "saved"
    assert len(playground["sessions"]) == 1
    saved = playground["sessions"][0]
    assert len(saved["X"]) == len(saved["y"]) == 1

    # A subsequent capture cannot mutate the session that Stop just saved.
    controls._start(ctx)
    assert ctx.recording
    assert len(saved["X"]) == 1
    assert playground["recorded_X"] == []
    controls._machine.stop()


def test_browser_state_attribute_is_written_only_when_state_changes(playground, monkeypatch):
    writes = []
    monkeypatch.setattr(
        sys.modules["js"], "document",
        SimpleNamespace(body=SimpleNamespace(setAttribute=lambda *args: writes.append(args))),
        raising=False,
    )
    publish = playground["_publish_state"]
    publish()
    publish()
    assert len(writes) == 1
    assert writes[0][0] == "data-mg-state"
    playground["rec_controls"]._start(playground["app"].ctx)
    publish()
    publish()
    assert len(writes) == 2
