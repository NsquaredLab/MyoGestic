"""The copyable session template trains real takes and keeps its shell usable."""

import runpy
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def session_app(monkeypatch, tmp_path):
    from myogestic.tools import emg_generator

    monkeypatch.chdir(tmp_path)
    sent = []
    monkeypatch.setattr(emg_generator, "control_outlet",
                        lambda: SimpleNamespace(push_sample=lambda value: sent.append(value)))
    ns = runpy.run_path(str(ROOT / "examples/synthetic/my_session_app.py"))
    ns["sent"] = sent
    yield ns
    for stream in ns["app"].ctx.streams.values():
        stream.detach_session()
        stream.stop()
    if ns["app"].ctx.session is not None:
        ns["app"].ctx.session.close()


def test_template_trains_saved_windows_and_preserves_class_indices(session_app, tmp_path):
    """Train on real session storage, including a nonconsecutive subset of classes."""
    from myogestic import StreamInfo, TrainingData
    from myogestic.session import Session

    ns = session_app
    session = Session(str(tmp_path / "takes"))
    session.init_stream("emg", StreamInfo(n_channels=2, fs=100))
    session.append("emg", np.repeat([[0.02, 0.04], [0.8, 0.6], [0.4, 0.9]], 100, axis=0),
                   np.arange(300) / 100)
    for label in range(3):
        session.add_label(label, timestamp=float(label))
    session.save_meta("template test", ["Rest", "Fist", "Open"])
    path = session.path
    session.close()
    model = ns["train"](TrainingData(paths=[str(path)], classes={0, 2}))
    assert set(model) == {0, 2}
    for label, value in [(0, [0.02, 0.04]), (2, [0.4, 0.9])]:
        window = np.repeat(np.asarray(value)[:, None], 20, axis=1)
        features = ns["extract"]({"emg": window})
        np.testing.assert_allclose(features, value)
        np.testing.assert_allclose(model[label], value)
        assert ns["predict"](model, features) == {"class": label}
    for data in (TrainingData(paths=[]), TrainingData(paths=[str(path)], classes={0})):
        with pytest.raises(ValueError, match="at least two gesture classes"):
            ns["train"](data)


def test_connect_is_nonblocking_single_attempt_and_reports_launch_failure(session_app, monkeypatch):
    """A double click cannot create two workers; a failed launch leaves Retry usable."""
    ns = session_app
    pending, calls = [], []
    monkeypatch.setattr(ns["threading"], "Thread",
                        lambda *, target, daemon: SimpleNamespace(start=lambda: pending.append(target)))
    monkeypatch.setattr(ns["processes"], "launch", lambda name: calls.append(name))
    monkeypatch.setattr(ns["app"].ctx.streams["emg"], "reconnect", lambda: calls.append("connect"))
    ns["_connect"]()
    ns["_connect"]()
    assert ns["connection"]["busy"] and len(pending) == 1 and calls == []
    pending.pop()()
    assert calls == ["EMG Generator", "connect"] and not ns["connection"]["busy"]

    def fail(name):
        raise OSError("generator missing")

    monkeypatch.setattr(ns["processes"], "launch", fail)
    ns["_connect"]()
    pending.pop()()
    assert not ns["connection"]["busy"]
    assert ns["connection"]["error"] == "generator missing"
    ns["app"].ctx.state = "recording"
    ns["_connect"]()
    assert pending == []


def test_recording_uses_selected_gesture_after_simulator_preview(session_app, monkeypatch):
    """Previewing Rest must not turn a Fist-labelled take into a Rest signal."""
    ns = session_app
    ns["app"].ctx.current_label = 1
    ns["simulator"].set(0)
    recorded = []
    monkeypatch.setattr(ns["app"], "start_recording", lambda: recorded.append(ns["simulator"].value))
    ns["_on_record"]()
    assert recorded == [1.0]
    np.testing.assert_array_equal(ns["sent"][-1], np.array([1.0], dtype=np.float32))


def test_completion_follows_this_participants_takes(session_app, monkeypatch, tmp_path):
    ns = session_app
    ctx = ns["app"].ctx
    assert ns["_step_done"](ctx) == [False] * 4
    ctx.participant = "P-014"
    folder = tmp_path / "sessions" / ctx.participant
    folder.mkdir(parents=True)
    (folder / "someone_else_take.session.zip").touch()
    monkeypatch.setitem(ctx.streams, "emg", SimpleNamespace(status="connected", info=object(),
                                                           detach_session=lambda: None, stop=lambda: None))
    assert ns["_step_done"](ctx) == [True, False, False, False]
    (folder / "P-014_take.session.zip").touch()
    ns["pipeline"].model = {0: np.zeros(8), 1: np.ones(8)}
    ctx.state = "predicting"
    assert ns["_step_done"](ctx) == [True] * 4


def test_switching_steps_keeps_the_same_recording_and_stream(session_app, monkeypatch, implot_frame):
    """Navigation must not stop a take, lose its label or detach acquisition."""
    from myogestic import StreamInfo

    ns = session_app
    app = ns["app"]
    app.ctx.participant = "P-014"
    app.ctx.current_label = 1
    stream = app.ctx.streams["emg"]
    source = SimpleNamespace(
        connect=lambda: StreamInfo(n_channels=2, fs=100), disconnect=lambda: None,
        read=lambda: (np.ones((10, 2), dtype=np.float32), np.arange(10) / 100),
    )
    monkeypatch.setattr(stream, "_source", source)
    assert stream.reconnect()
    stream._acquire_step()
    ns["recording"]._start(app.ctx)
    session = app.ctx.session
    assert session is not None and app.ctx.state == "recording"
    assert [label.class_index for label in session.label_track] == [1]
    for step in (0, 2, 3, 1):
        ns["steps"].active = step
        implot_frame(lambda: app._ui_fn(app.ctx))
        stream._acquire_step()
        assert app.ctx.state == "recording" and app.ctx.session is session
        assert stream._session is session
    assert session.stores["emg"].shape == (40, 2)
    assert ns["simulator"].value == 1


@pytest.mark.parametrize("width", [2560, 1800, 800])
@pytest.mark.parametrize("step", range(4))
@pytest.mark.parametrize("state", ["empty", "ready", "recording"])
def test_shell_fits_in_light_theme_at_scale_two(
    session_app, monkeypatch, implot_frame, width, step, state,
):
    """Exercise real controls at the default window and two narrow layouts."""
    from imgui_bundle import hello_imgui, imgui

    from myogestic import Px, _scale, _theme
    from myogestic.grid import _AreaCell
    from myogestic.widgets import AppHeader

    ns = session_app
    app = ns["app"]
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width, 1656)
    # Keep logo geometry real; only texture upload needs a display.
    monkeypatch.setattr(hello_imgui, "asset_exists", lambda name: True)

    def asset(name):
        width, height = struct.unpack(">II", (ROOT / "myogestic/assets" / name).read_bytes()[16:24])
        return SimpleNamespace(texture_id=1, size=imgui.ImVec2(width, height))

    monkeypatch.setattr(hello_imgui, "image_and_size_from_asset", asset)
    monkeypatch.setattr(imgui, "image", lambda texture, size: imgui.dummy(size))
    ns["steps"].active = step
    if state != "empty":
        app.ctx.participant = "P-014"
        ns["pipeline"].model = {0: np.zeros(8), 1: np.ones(8)}
        ns["pipeline"].predictions = {"class": 1}
    if state == "recording":
        app.ctx.state = "recording"
    assert isinstance(ns["header"], AppHeader)
    assert ns["header"].steps is ns["steps"]
    assert ns["header"].participant is ns["participant"]
    assert ns["steps"].steps == ["Connect", "Record", "Train", "Predict"]
    assert ns["status"].pipeline is ns["pipeline"]
    assert app.ctx.require_participant and not ns["recording"]._show_header
    for grid in (ns["layout"]._wide, ns["layout"]._narrow):
        assert grid._bare == {"header", "status"}
        assert grid._row_tracks[0] == Px(52) and grid._row_tracks[-1] == Px(26)
    cells, buttons, visibility = [], [], []
    leave = _AreaCell.__exit__
    record_ui = ns["recording"].ui
    button = imgui.button

    def leave_cell(cell, *args):
        cells.append((cell._name, imgui.get_scroll_max_x(), imgui.get_scroll_max_y()))
        leave(cell, *args)

    def record(ctx, *, visible=True):
        visibility.append(visible)
        record_ui(ctx, visible=visible)

    def measure_button(label, *args, **kwargs):
        edge = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        result = button(label, *args, **kwargs)
        buttons.append((label, imgui.get_item_rect_max().x - edge))
        return result

    monkeypatch.setattr(_AreaCell, "__exit__", leave_cell)
    monkeypatch.setattr(ns["recording"], "ui", record)
    monkeypatch.setattr(imgui, "button", measure_button)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1656))
        imgui.begin("session-template", flags=imgui.WindowFlags_.no_title_bar)
        app._ui_fn(app.ctx)
        assert imgui.get_scroll_max_x() == imgui.get_scroll_max_y() == 0
        imgui.end()

    for _ in range(4):
        cells.clear()
        buttons.clear()
        visibility.clear()
        implot_frame(draw)
    assert {name for name, *_ in cells} == ns["layout"].panel_names
    assert visibility == [step == 1]
    assert all(horizontal == 0 for _, horizontal, _ in cells), cells
    assert all(vertical == 0 for name, _, vertical in cells if name in {"header", "simulator", "status"}), cells
    assert all(overhang <= 1 for _, overhang in buttons), buttons
    assert ns["layout"]._active is (ns["layout"]._wide if width == 2560 else ns["layout"]._narrow)


def test_gallery_render_entries_draw_without_capturing(monkeypatch, implot_frame, tmp_path):
    from imgui_bundle import imgui

    from myogestic import App
    from myogestic.tools import emg_generator
    from myogestic.widgets import AppLogo, StepBar

    gallery = runpy.run_path(str(ROOT / "tools/widget_screenshot.py"))
    default_step = StepBar(["First", "Second"]).active
    capture_calls = []
    monkeypatch.setitem(gallery["render_app_header"].__globals__, "_self_capture_after",
                        lambda seconds, path: capture_calls.append(path.name))
    monkeypatch.setattr(AppLogo, "ui", lambda self: None)
    monkeypatch.setattr(emg_generator, "control_outlet",
                        lambda: SimpleNamespace(push_sample=lambda value: None))

    def run(app, *, window_size):
        width, height = window_size
        imgui.get_io().display_size = imgui.ImVec2(width, height)

        def draw():
            imgui.set_next_window_size(imgui.ImVec2(width, height))
            imgui.begin("gallery-probe")
            app._ui_fn(app.ctx)
            imgui.end()

        implot_frame(draw)
        for stream in app.ctx.streams.values():
            stream.stop()

    monkeypatch.setattr(App, "run", run)
    for name in ("AppHeader", "StatusBar", "SimulatorControls"):
        gallery["WIDGETS"][name](tmp_path / f"{name}.png")
    assert capture_calls == ["AppHeader.png", "StatusBar.png", "SimulatorControls.png"]
    assert StepBar(["First", "Second"]).active == default_step
