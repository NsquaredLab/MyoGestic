"""The shipped browser app uses the public workflow and portable saved takes.

Also run with `uv run --with zarr==2.18.7 --extra dev pytest -p no:zarr -q
 tests/test_browser_playground.py`: this is the browser's synchronous storage
backend, and that run forbids *all* Python threads throughout the workflow.
The ordinary suite exercises the desktop Zarr 3 backend too.
"""

import json
import runpy
import sys
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import zarr

from myogestic import App, Fr, Px
from myogestic import _browser as browser
from myogestic import stream as stream_module
from myogestic.ml import pipeline as pipeline_module
from myogestic.session import iter_labeled_windows, open_session_store
from myogestic.widgets import AppHeader, DevicePicker, SessionManager, StatusBar
from myogestic.widgets.training import _session_state

APP_PATH = Path(__file__).resolve().parents[1] / "docs/playground/app.py"


@pytest.fixture(params=[(1440, 900), (390, 844)], ids=["desktop", "phone"])
def playground(monkeypatch, tmp_path, request):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(browser, "IS_BROWSER", True)
    monkeypatch.setattr(browser, "_scheduler", browser._BrowserScheduler())
    monkeypatch.setattr(stream_module, "_IS_BROWSER", True)
    monkeypatch.setattr(pipeline_module, "_IS_BROWSER", True)
    monkeypatch.setattr(App, "run", lambda *a, **kw: None)
    monkeypatch.setattr(_session_state, "_states", {})

    # Zarr 3 itself needs threads; the browser installs synchronous Zarr 2.
    # In that backend the entire import/connect/record/read/train/predict loop
    # must run with Thread.start forbidden, not just an app-specific sampler.
    if zarr.__version__.startswith("2."):
        monkeypatch.setattr(threading.Thread, "start", _no_threads)
    width, height = request.param
    monkeypatch.setitem(sys.modules, "js", SimpleNamespace(
        window=SimpleNamespace(innerWidth=width, innerHeight=height),
        document=SimpleNamespace(body=SimpleNamespace(setAttribute=lambda *a: None)),
    ))
    app = runpy.run_path(str(APP_PATH))
    # Drive source and take clocks deterministically, without waiting or a GUI.
    import mne_lsl.lsl
    clock = [100.0]
    monkeypatch.setattr(mne_lsl.lsl, "local_clock", lambda: clock[0])
    app["recording"]._machine._clock = lambda: clock[0]
    app["clock"] = clock
    return app


def _no_threads(*args, **kwargs):
    raise AssertionError("Pyodide cannot start threads")


def connect(app):
    app["device"]._connect(app["app"].ctx, app["stream"], app["synthetic"])
    assert app["stream"].status == "connected"


def acquire(app, chunks=1):
    for _ in range(chunks):
        app["clock"][0] += 1 / 16
        app["stream"]._acquire_step()


def record(app, index=0):
    ctx, controls = app["app"].ctx, app["recording"]
    app["_on_gesture"](index)
    controls._start(ctx)
    assert controls.take.phase == "warmup"
    assert not ctx.recording
    app["clock"][0] += 1.0
    # Keep acquisition's clock aligned after the warm-up.
    app["stream"]._source._next_tick = app["clock"][0]
    controls.ui(ctx, visible=False)
    assert controls.take.phase == "recording"
    assert ctx.recording and ctx.session is not None
    take = ctx.session
    acquire(app, 48)  # exactly three seconds at 1024 Hz
    controls.ui(ctx, visible=False)  # timer must stop even on a different step
    assert not ctx.recording
    assert ctx.state == "idle"
    assert controls.take.phase == "saved"
    assert not ctx.pending_saves
    assert take.path.is_file() and take.path.name.endswith(".mg.zip")
    return take.path


def test_standard_widgets_and_responsive_tracks(playground):
    app = playground
    assert isinstance(app["header"], AppHeader)
    assert isinstance(app["device"], DevicePicker)
    assert isinstance(app["sessions"], SessionManager)
    assert isinstance(app["status"], StatusBar)
    assert not app["app"].ctx.recording
    assert not app["stream"]._connected
    assert app["app"].ctx.participant == "P-DEMO"
    assert app["steps"].steps == ["Connect", "Record", "Train", "Predict"]
    layout = app["layout"]
    assert layout._breakpoint == Px(1100)
    assert layout._wide._row_tracks == [Px(52), Fr(3), Fr(1), Px(110), Px(26)]
    assert layout._wide._col_tracks == [Fr(1), Px(400)]
    assert layout._narrow._row_tracks == [Px(52), Fr(2.4), Fr(4.5), Fr(1.5), Px(60), Px(26)]
    assert layout._wide._bare == layout._narrow._bare == {"header", "status"}
    assert len(app["device"]._devices) == 1
    assert app["recording"]._timed


def test_connect_and_synthetic_read_need_no_threads_or_sleep(playground, monkeypatch):
    monkeypatch.setattr(threading.Thread, "start", _no_threads)
    monkeypatch.setattr("time.sleep", lambda *_: pytest.fail("browser read must not sleep"))
    playground["device"]._start_scan(playground["synthetic"])
    assert playground["device"]._targets[0]["name"] == "Synthetic EMG"
    assert not playground["device"]._scanning
    connect(playground)
    source = playground["stream"]._source
    before = source._next_tick, source._pos
    assert source.read() == (None, None)
    assert (source._next_tick, source._pos) == before
    acquire(playground)
    assert playground["stream"].get_window()[0].shape == (8, 64)


def test_timed_takes_save_real_arrays_and_train_from_selection(playground):
    app = playground
    connect(app)
    paths = [record(app, index) for index in range(3)]
    for index, path in enumerate(paths):
        with zipfile.ZipFile(path) as archive:
            meta = json.loads(archive.read("meta.json"))
            assert meta["participant"] == "P-DEMO"
            assert meta["class_names"] == app["CLASSES"]
            assert meta["duration_s"] == pytest.approx(3 - 1 / 1024)
        with open_session_store(path) as saved:
            signal, ts = saved.get_continuous("emg")
            assert signal.shape == (3072, 8)
            assert len(ts) == 3072
            assert saved.label_track[0].class_index == index
    summary = app["sessions"].selection()
    assert summary.n_total == summary.n_selected == 3
    assert all(summary.class_seconds[name] > 2.9 for name in app["CLASSES"])

    app["sessions"].select_all("P-DEMO")  # public rescan also reads packed takes
    from myogestic import TrainingData
    app["pipeline"].training_data = TrainingData(
        paths=[str(p) for p in paths], class_names=app["CLASSES"], classes={0, 1, 2},
    )
    app["pipeline"].start_training()
    assert app["pipeline"].model is not None, app["pipeline"].train_log
    assert app["metrics"]["takes"] == 3
    assert app["metrics"]["windows"] > 60
    assert app["metrics"]["accuracy"] > 0.95
    assert len(list(iter_labeled_windows(paths, "emg", 250, 100, classes={2}))) > 20

    # The running prediction must follow an actual change in synthetic samples.
    app["pipeline"].start_predicting()
    for index in (2, 0, 1):
        app["_on_gesture"](index)
        for _ in range(16):
            acquire(app)
            app["pipeline"]._predict_step(app["app"])
        assert app["pipeline"].predictions["class"] == index
    app["pipeline"].stop_predicting()


def test_start_stop_take_stays_active_and_preserves_the_saved_archive(playground):
    """Keep the original recording fix as well as the new timed workflow."""
    app = playground
    connect(app)
    controls, ctx = app["recording"], app["app"].ctx
    controls._timed = False
    controls._start(ctx)
    acquire(app, 8)
    controls.ui(ctx, visible=False)
    assert ctx.recording and ctx.state == "recording"
    assert controls.take.phase == "recording"
    first = ctx.session
    controls._machine.stop()
    assert not ctx.recording and controls.take.phase == "saved"
    archive = first.path.read_bytes()
    controls._start(ctx)
    acquire(app, 4)
    controls._machine.stop()
    assert first.path.read_bytes() == archive
    assert app["sessions"].selection().n_total == 2


def test_training_has_no_fabricated_fallback(playground):
    from myogestic import TrainingData
    with pytest.raises(ValueError, match="Record and select"):
        playground["train"](TrainingData(paths=[], class_names=[], classes=set()))


def test_state_attribute_is_written_only_when_state_changes(playground, monkeypatch):
    writes = []
    monkeypatch.setattr(sys.modules["js"].document.body, "setAttribute", lambda *a: writes.append(a))
    publish = playground["_publish_state"]
    publish()
    publish()
    assert len(writes) == 1
    assert writes[0][0] == "data-mg-state"
    connect(playground)
    publish()
    publish()
    assert len(writes) == 2
    state = json.loads(writes[-1][1])
    assert state["connected"] and state["step"] == "Connect"
    assert state["sessions"]["total"] == 0


@pytest.mark.parametrize("step", [0, 1, 2, 3], ids=["connect", "record", "train", "predict"])
def test_primary_action_fits_without_scrolling(playground, implot_frame, monkeypatch, step):
    """The real canvas controls must fit their step card before any scrolling."""
    from imgui_bundle import imgui

    from myogestic import _theme

    _theme.apply_theme()
    imgui.get_style().font_size_base = 16.0
    width = sys.modules["js"].window.innerWidth
    height = sys.modules["js"].window.innerHeight
    size = imgui.ImVec2(width, height)
    imgui.get_io().display_size = size
    playground["steps"].active = step
    action = ["Connect", "##rec_btn", "Train", "Predict"][step]
    measured = []
    real_button = imgui.button

    def button(label, *args, **kwargs):
        result = real_button(label, *args, **kwargs)
        if action in label:
            lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            origin, bounds = imgui.get_window_pos(), imgui.get_window_size()
            measured.append((lo.y, hi.y, origin.y, origin.y + bounds.y))
        return result

    monkeypatch.setattr(imgui, "button", button)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(size)
        imgui.begin("playground", flags=imgui.WindowFlags_.no_title_bar)
        playground["ui"](playground["app"].ctx)
        imgui.end()

    for _ in range(3):
        implot_frame(draw)
    assert measured, action
    top, bottom, card_top, card_bottom = measured[-1]
    assert card_top <= top < bottom <= min(card_bottom, height), measured[-1]
