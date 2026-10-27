"""The hardware recorder composes the session shell without connecting on import."""

from __future__ import annotations

import platform
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def otb_app(monkeypatch, tmp_path):
    """Build the real example without a device or a persistent session folder."""
    from myogestic.sources.otb import SessantaquattroSource
    from myogestic.widgets.signals._state import _viewers
    from myogestic.widgets.training._session_state import _states

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        SessantaquattroSource, "connect", lambda self: pytest.fail("unexpected hardware connection")
    )
    _states.clear()
    _viewers.clear()
    namespace = runpy.run_path(str(_ROOT / "examples/otb/sessantaquattro_app.py"))
    streams = tuple(namespace["app"].ctx.streams.values())
    try:
        yield namespace
    finally:
        for stream in streams:
            stream.stop()
        _states.clear()
        _viewers.clear()


def test_sessantaquattro_uses_the_session_shell(otb_app):
    from myogestic import Fr, Px
    from myogestic.widgets import AppHeader, StatusBar

    ns = otb_app
    layout, header, steps = (ns[name] for name in ("layout", "header", "steps"))
    assert isinstance(header, AppHeader) and header.title == "Sessantaquattro"
    assert header.steps is steps and header.participant is ns["participant"]
    assert header.show_state
    assert steps.steps == ["Connect", "Record"]
    assert steps._widget_id == "sessantaquattro_steps"
    assert isinstance(ns["status"], StatusBar)
    assert ns["status"].stream == "emg" and ns["status"].pipeline is None
    assert ns["app"].ctx.require_participant
    assert not ns["streams"]._show_header and not ns["recording"]._show_header
    assert not ns["viewer"]._show_connect
    assert ns["recording"]._on_record == ns["app"].start_recording
    assert ns["recording"]._on_stop == ns["app"].stop_recording
    assert ns["recording"]._class_names == ["Rest", "Contract"]
    source = ns["source"]
    assert (source._nch_mode, source._fs_mode, source._mode) == (3, 2, "monopolar")
    assert ns["app"].ctx.streams["emg"]._source is source
    assert layout.panel_names == {"header", "signal", "step", "sessions", "log", "status"}
    assert layout._breakpoint == Px(1100)
    assert layout._wide._col_tracks == [Fr(1), Px(400)]
    assert layout._wide._areas == {
        "header": (0, 1, 0, 2),
        "signal": (1, 3, 0, 1),
        "step": (1, 2, 1, 2),
        "sessions": (2, 4, 1, 2),
        "log": (3, 4, 0, 1),
        "status": (4, 5, 0, 2),
    }
    assert list(layout._narrow._areas) == ["header", "signal", "step", "sessions", "log", "status"]
    for grid in (layout._wide, layout._narrow):
        assert grid._bare == {"header", "status"}
        assert grid._row_tracks[0] == Px(52) and grid._row_tracks[-1] == Px(26)


def test_sessantaquattro_completion_tracks_connection_and_participant_takes(
    otb_app, monkeypatch, tmp_path
):
    """An unattached stream or another participant's take never completes a step."""
    ctx, done = otb_app["app"].ctx, otb_app["_step_done"]
    assert done(ctx) == [False, False]
    ctx.participant = "P-014"
    stream = SimpleNamespace(status="connected", info=object())
    monkeypatch.setitem(ctx.streams, "emg", stream)
    folder = tmp_path / "sessions" / ctx.participant
    folder.mkdir(parents=True)
    (folder / "someone-else_take.session.zip").touch()
    assert done(ctx) == [True, False]
    (folder / "P-014_take.session.zip").touch()
    assert done(ctx) == [True, True]
    stream.info = None
    assert done(ctx) == [False, True]
    ctx.participant = "P-015"
    assert done(ctx) == [False, False]
    monkeypatch.delitem(ctx.streams, "emg")
    assert done(ctx) == [False, False]


@pytest.mark.parametrize("step", [0, 1])
@pytest.mark.parametrize("width", [2560, 1800, 1280])
@pytest.mark.parametrize("participant", ["", "P-014"])
@pytest.mark.parametrize("state", ["idle", "recording", "failed", "connected"])
def test_sessantaquattro_shell_fits_light_theme(
    otb_app,
    monkeypatch,
    implot_frame,
    step,
    width,
    participant,
    state,
):
    """Render every step at scale two and measure cards, text and actions."""
    import numpy as np
    from imgui_bundle import hello_imgui, imgui

    from myogestic import StreamInfo, _scale, _theme
    from myogestic.grid import _AreaCell
    from myogestic.widgets.panels import recording
    from myogestic.widgets.signals import stream_panel

    ns, ctx = otb_app, otb_app["app"].ctx
    ctx.participant = participant
    ctx.state = "recording" if state == "recording" else "idle"
    ctx.recording = state == "recording"
    ns["steps"].active = step
    stream = ctx.streams["emg"]
    if state == "failed":
        stream.last_error = (
            "Accept timed out: the device did not connect to this PC. Check its server IP address."
        )
    elif state == "connected":
        stream.info = StreamInfo(
            fs=2000, n_channels=64, channel_names=[f"EMG {i}" for i in range(64)]
        )
        stream.status = "connected"
        stream._allocate_buffers()
        stream._data.extend(np.zeros((2000, 64), dtype=np.float32))
        stream._timestamps.extend(np.arange(2000, dtype=np.float64) / 2000)
        stream._total_seq = 2000
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    font_path = Path(_theme._SYS_FONTS.get(platform.system(), ""))
    if not font_path.is_file():
        font_path = Path(hello_imgui.asset_file_full_path("fonts/Roboto/Roboto-Regular.ttf"))
    imgui.get_io().font_default = imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 14)
    for attr, filename, size in (
        ("_MONO_FONT", "IBMPlexMono-Regular.ttf", 13),
        ("_DISPLAY_FONT", "InstrumentSerif-Regular.ttf", 28),
    ):
        font = imgui.get_io().fonts.add_font_from_file_ttf(
            str(_ROOT / "myogestic/assets/fonts" / filename), size
        )
        monkeypatch.setattr(_theme, attr, font)
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width, 1656)
    headers, views, cells, items = [], [], [], []
    original_header = ns["panel_header"]

    def header(title, *args, **kwargs):
        headers.append(title)
        return original_header(title, *args, **kwargs)

    monkeypatch.setitem(ns["app"]._ui_fn.__globals__, "panel_header", header)
    monkeypatch.setattr(recording, "panel_header", header)
    monkeypatch.setattr(stream_panel, "panel_header", header)
    monkeypatch.setattr(
        imgui, "begin_tab_bar", lambda *a: pytest.fail("the session shell has no tabs")
    )

    for method in (
        "button",
        "small_button",
        "text",
        "text_unformatted",
        "text_wrapped",
        "text_colored",
    ):
        render = getattr(imgui, method)

        def item(*args, render=render, method=method, **kwargs):
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            result = render(*args, **kwargs)
            items.append((method, str(args), imgui.get_item_rect_max().x - right))
            return result

        monkeypatch.setattr(imgui, method, item)

    for name in ("header", "streams", "viewer", "recording", "sessions", "log", "status"):
        widget = ns[name]
        render = type(widget).ui

        def view(self, *args, name=name, render=render, **kwargs):
            views.append((name, kwargs))
            return render(self, *args, **kwargs)

        monkeypatch.setattr(type(widget), "ui", view)

    exit_cell = _AreaCell.__exit__

    def measure_cell(self, *args):
        cells.append(
            (
                self._name,
                imgui.get_cursor_pos_y(),
                imgui.get_window_size().y,
                imgui.get_scroll_max_x(),
                imgui.get_scroll_max_y(),
            )
        )
        return exit_cell(self, *args)

    monkeypatch.setattr(_AreaCell, "__exit__", measure_cell)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1656))
        imgui.begin("sessantaquattro-shell", flags=imgui.WindowFlags_.no_title_bar)
        ns["app"]._ui_fn(ctx)
        assert imgui.get_scroll_max_x() == imgui.get_scroll_max_y() == 0
        imgui.end()

    for _ in range(4):
        headers.clear()
        views.clear()
        cells.clear()
        items.clear()
        implot_frame(draw)
    assert headers == [ns["steps"].steps[step]]
    expected = {"header", "viewer", "recording", "sessions", "log", "status"}
    assert {name for name, _ in views} == expected | ({"streams"} if step == 0 else set())
    assert [kwargs for name, kwargs in views if name == "recording"] == (
        [{}] if step == 1 else [{"visible": False}]
    )
    assert next(kwargs for name, kwargs in views if name == "sessions") == {
        "participant": participant
    }
    assert all(overhang <= 1 for _, _, overhang in items), items
    assert all(
        horizontal == vertical == 0 and cursor - imgui.get_style().item_spacing.y <= height
        for _, cursor, height, horizontal, vertical in cells
    ), cells
    assert ns["layout"]._active is (ns["layout"]._wide if width == 2560 else ns["layout"]._narrow)


def test_sessantaquattro_recording_advances_off_step(otb_app, monkeypatch, implot_frame):
    """A warm-up starts and a timed take stops even after returning to Connect."""
    from myogestic.widgets import RecordingControls

    ns, ctx = otb_app, otb_app["app"].ctx
    ctx.participant = "P-014"
    now, calls = [0.0], []

    def start():
        calls.append("start")
        ctx.state = "recording"
        ctx.recording = True

    def stop():
        calls.append("stop")
        ctx.state = "idle"
        ctx.recording = False

    recording = RecordingControls(
        ns["CLASSES"],
        on_record=start,
        on_stop=stop,
        timed=True,
        take_lengths=(1.0,),
        warmups=(1.0,),
    )
    monkeypatch.setattr(recording._machine, "_clock", lambda: now[0])
    monkeypatch.setitem(ns["app"]._ui_fn.__globals__, "recording", recording)
    ns["steps"].active = 0
    recording._start(ctx)
    assert recording.take.phase == "warmup"
    now[0] = 1.0
    implot_frame(lambda: ns["app"]._ui_fn(ctx))
    assert calls == ["start"] and recording.take.phase == "recording"
    now[0] = 2.0
    implot_frame(lambda: ns["app"]._ui_fn(ctx))
    assert calls == ["start", "stop"] and recording.take.phase == "saved"
    assert ctx.state == "idle"


@pytest.mark.parametrize("recording", [False, True])
def test_sessantaquattro_connect_button_reaches_device_only_while_idle(
    otb_app,
    monkeypatch,
    implot_frame,
    recording,
):
    """The step uses the existing source connection and locks it during a take."""
    from imgui_bundle import imgui

    from myogestic.widgets.signals import stream_panel

    ns, ctx = otb_app, otb_app["app"].ctx
    ctx.state = "recording" if recording else "idle"
    ctx.recording = recording
    calls = []

    def reconnect(target=None):
        calls.append(target)
        return False

    monkeypatch.setattr(ctx.streams["emg"], "reconnect", reconnect)
    monkeypatch.setattr(
        stream_panel._threading, "Thread", lambda target, daemon: SimpleNamespace(start=target)
    )
    render_button = imgui.button

    def click(label, *args, **kwargs):
        result = render_button(label, *args, **kwargs)
        return True if label.endswith("##sp_conn_emg") else result

    monkeypatch.setattr(imgui, "button", click)
    implot_frame(lambda: ns["app"]._ui_fn(ctx))
    assert calls == ([] if recording else [None])
    if not recording:
        assert ctx.streams["emg"].last_error


def test_sessantaquattro_keeps_the_device_dropout_warning(otb_app, monkeypatch, capsys):
    ns = otb_app
    monkeypatch.setattr(ns["app"], "run", lambda: None)
    ns["source"].dropped_samples = 8
    ns["source"].dropout_events = 2
    ns["main"]()
    assert "8 samples dropped in 2 gaps" in capsys.readouterr().out
