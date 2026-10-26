"""Viewer headers and their original body cards fit the light, scaled window."""

import platform
import runpy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from imgui_bundle import hello_imgui, imgui
from matplotlib import get_data_path

from myogestic import Px, _scale, _theme
from myogestic.grid import _AreaCell
from myogestic.widgets import AppHeader, AppLogo
from myogestic.widgets.panels import app_header
from myogestic.widgets.signals import _state

ROOT = Path(__file__).resolve().parents[1]
VIEWERS = {
    "high_channel_viewer": "High-channel viewer",
    "electrode_grids": "Electrode grids",
    "electrode_overview": "Electrode overview",
}


@pytest.mark.parametrize("name,title,launch_failed", [
    *((name, title, False) for name, title in VIEWERS.items()),
    ("high_channel_viewer", "High-channel viewer", True),
])
@pytest.mark.parametrize("width", [2560, 1280])
@pytest.mark.parametrize("connected", [False, True])
@pytest.mark.parametrize("ui_font", ["platform", "dejavu"])
def test_viewer_header_and_body_fit(
    name, title, launch_failed, width, connected, ui_font, monkeypatch, implot_frame,
):
    """Measure real text, actions and cell bounds after the header takes its row."""
    ns = runpy.run_path(str(ROOT / "examples" / "synthetic" / f"{name}.py"))
    app, grid = ns["app"], ns["grid"]
    header = ns["header"]
    assert isinstance(header, AppHeader)
    assert header.title == title
    assert header.steps is header.participant is None
    assert not header.show_state
    assert grid._row_tracks[0] == Px(52)
    assert grid._areas["header"] == (0, 1, 0, grid.cols)
    assert grid._bare == {"header"}
    if launch_failed:
        process = ns["processes"]._process_state("EMG Generator 256ch")
        process._launch_error = "The generator could not be launched."

    monkeypatch.setattr(_state, "_viewers", {})
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    io = imgui.get_io()
    if ui_font == "dejavu":
        # Matplotlib ships this wider Linux face on macOS and Windows too.
        font_path = Path(get_data_path()) / "fonts/ttf/DejaVuSans.ttf"
        assert font_path.is_file()
    else:
        font_path = Path(_theme._SYS_FONTS.get(platform.system(), ""))
        if not font_path.is_file():
            font_path = Path(hello_imgui.asset_file_full_path("fonts/Roboto/Roboto-Regular.ttf"))
    io.font_default = io.fonts.add_font_from_file_ttf(str(font_path), 14)
    font = io.fonts.add_font_from_file_ttf(
        str(ROOT / "myogestic/assets/fonts/IBMPlexMono-Regular.ttf"), 13,
    )
    monkeypatch.setattr(_theme, "_MONO_FONT", font)
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    io.display_size = imgui.ImVec2(width, 1656)

    # Retain the logo's real layout; only its GPU texture needs a stand-in.
    monkeypatch.setattr(hello_imgui, "asset_exists", lambda name: True)
    monkeypatch.setattr(hello_imgui, "image_and_size_from_asset", lambda name: SimpleNamespace(
        texture_id=1, size=imgui.ImVec2(519, 128),
    ))
    monkeypatch.setattr(imgui, "image", lambda texture, size: imgui.dummy(size))
    monkeypatch.setattr(app_header, "status_pill", lambda *args: pytest.fail("viewers have no state pill"))

    stream = app.ctx.streams["emg"]
    if connected:
        if name == "high_channel_viewer":
            source = runpy.run_path(str(ROOT / "examples/synthetic/electrode_grids.py"))
            stream._source = source["_SyntheticGridSource"]()
        stream.reconnect()
        stream._acquire_step()
        assert stream.status == "connected"

    items, cells, logos = [], {}, []
    original_logo = AppLogo.ui

    def logo(self):
        logos.append(self._asset)
        return original_logo(self)

    monkeypatch.setattr(AppLogo, "ui", logo)

    def remember(label):
        draw = imgui.get_window_draw_list()
        items.append((str(label), tuple(imgui.get_item_rect_min()), tuple(imgui.get_item_rect_max()),
                      tuple(draw.get_clip_rect_min()), tuple(draw.get_clip_rect_max())))

    for method in (
        "text_unformatted", "text_wrapped", "text_disabled", "text", "button", "small_button", "combo",
    ):
        original = getattr(imgui, method)

        def item(label, *args, _original=original, **kwargs):
            result = _original(label, *args, **kwargs)
            remember(label)
            return result

        monkeypatch.setattr(imgui, method, item)
    original_text = imgui.text_colored

    def colored(color, label):
        original_text(color, label)
        remember(label)

    monkeypatch.setattr(imgui, "text_colored", colored)
    original_exit = _AreaCell.__exit__

    def exit_cell(self, *args):
        pos, size = imgui.get_window_pos(), imgui.get_window_size()
        cells[self._name] = (tuple(pos), (pos.x + size.x, pos.y + size.y),
                            imgui.get_scroll_max_x(), imgui.get_scroll_max_y())
        return original_exit(self, *args)

    monkeypatch.setattr(_AreaCell, "__exit__", exit_cell)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1656))
        imgui.begin("viewer-layout", flags=imgui.WindowFlags_.no_title_bar)
        app._ui_fn(app.ctx)
        assert imgui.get_scroll_max_x() == imgui.get_scroll_max_y() == 0
        imgui.end()

    try:
        for _ in range(4):
            items.clear()
            cells.clear()
            logos.clear()
            implot_frame(draw)
    finally:
        stream.disconnect()

    assert logos == ["myogestic_logo_line.png"]
    assert any(label == title for label, *_ in items)
    header_lo, header_hi, *_ = cells["header"]
    assert header_hi[1] - header_lo[1] == pytest.approx(104)
    assert len(cells) == {"high_channel_viewer": 5, "electrode_grids": 5,
                          "electrode_overview": 7}[name]
    for cell, (lo, hi, scroll_x, scroll_y) in cells.items():
        assert scroll_x == scroll_y == 0, (cell, scroll_x, scroll_y)
        assert 0 <= lo[0] < hi[0] <= width and 0 <= lo[1] < hi[1] <= 1656, (cell, lo, hi)
        if cell != "header":
            assert lo[1] >= header_hi[1]
    clipped = [(label, lo, hi, clip_lo, clip_hi) for label, lo, hi, clip_lo, clip_hi in items
               if any(lo[i] < clip_lo[i] - 1 or hi[i] > clip_hi[i] + 1 for i in (0, 1))]
    assert not clipped, clipped


def test_electrode_grids_keep_separate_selections_and_one_manual_range(monkeypatch, implot_frame):
    """Every electrode belongs to one tile; quiet arrays retain their relative amplitude."""
    ns = runpy.run_path(str(ROOT / "examples/synthetic/electrode_grids.py"))
    app, viewers = ns["app"], ns["viewers"]
    monkeypatch.setattr(_state, "_viewers", {})
    monkeypatch.setattr(AppLogo, "ui", lambda self: None)
    stream = app.ctx.streams["emg"]
    stream.reconnect()
    stream._acquire_step()
    try:
        implot_frame(lambda: app._ui_fn(app.ctx))
        states = [_state._viewers[viewer._widget_id] for viewer in viewers]
        assert len({id(state) for state in states}) == 4
        assert all(state.scale_mode == "manual" for state in states)
        assert {(state.y_min, state.y_max) for state in states} == {ns["Y_RANGE"]}
        assert all(not state.per_channel_scale for state in states)
        scopes = [set(viewer._channel_scope) for viewer in viewers]
        assert set.union(*scopes) == set(range(256))
        assert sum(map(len, scopes)) == 256
        assert all(len(scope) == 64 for scope in scopes)
        for viewer, state, scope, channel_grid in zip(
            viewers, states, scopes, stream.info.channel_grids, strict=True,
        ):
            assert viewer._stream_name == "emg"
            assert set(channel_grid.columns) == scope
            enabled = _state.resolve_enabled(state, "emg", 256, viewer._initial_channels,
                                             list(viewer._channel_scope))
            assert enabled == scope

        # Editing one tile cannot change any other tile's channel selection.
        states[0].channels.clear()
        assert all(states[i].channels == scopes[i] for i in range(1, 4))
    finally:
        stream.disconnect()


def test_electrode_grid_source_is_paced_and_preserves_amplitude_differences(monkeypatch):
    """A standalone stream must not busy-loop, and shared axes must show quieter arrays."""
    ns = runpy.run_path(str(ROOT / "examples/synthetic/electrode_grids.py"))
    times = iter([0.0, 0.0, ns["CHUNK"] / ns["FS"]])
    monkeypatch.setattr(ns["time"], "perf_counter", lambda: next(times))
    source = ns["_SyntheticGridSource"]()
    info = source.connect()
    data, timestamps = source.read()
    assert data.shape == (ns["CHUNK"], info.n_channels)
    assert info.n_channels == 256
    assert data.dtype == np.float32
    assert source.read() == (None, None)
    next_data, next_timestamps = source.read()
    assert next_data.shape == data.shape
    assert next_timestamps[0] - timestamps[-1] == pytest.approx(1.0 / info.fs)
    rms = np.sqrt(np.mean(data.reshape(ns["CHUNK"], 4, 64) ** 2, axis=(0, 2)))
    assert np.all(np.diff(rms) < 0)


@pytest.mark.parametrize("width", [400, 640, 900, 1800])
@pytest.mark.parametrize("state", ["connected", "disconnected", "lost", "error"])
def test_signal_viewer_fits_small_tile(width, state, monkeypatch, imgui_frame):
    """Toolbar groups and wrapped guidance fit without changing viewer controls."""
    from imgui_bundle import imgui

    from myogestic import Context, Stream, _scale, _theme
    from myogestic.sources import LSLSource
    from myogestic.stream import StreamInfo
    from myogestic.widgets.signals._controls import render_controls
    from myogestic.widgets.signals._scan import _disconnected_ui
    from myogestic.widgets.signals._state import ViewerState

    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width, 1200)
    stream = Stream("emg", source=LSLSource("tile-test"), window_ms=1000)
    ctx = Context(streams={"emg": stream})
    viewer = ViewerState()
    if state in ("connected", "lost"):
        stream.info = StreamInfo(n_channels=64, fs=2048)
    if state == "connected":
        stream.status = "connected"
    elif state == "error":
        stream.last_error = "The amplifier connection failed; verify the device and try connecting again."
    bounds, labels = [], []
    for method in ("button", "small_button", "combo", "text_wrapped"):
        original = getattr(imgui, method)

        def item(label, *args, _original=original, **kwargs):
            result = _original(label, *args, **kwargs)
            draw = imgui.get_window_draw_list()
            bounds.append((label, imgui.get_item_rect_max().x, draw.get_clip_rect_max().x))
            labels.append(label)
            return result

        monkeypatch.setattr(imgui, method, item)

    def draw():
        imgui.set_next_window_size(imgui.ImVec2(width, 1200))
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.begin("small-viewer", flags=imgui.WindowFlags_.no_title_bar)
        render_controls(ctx, "emg", "emg", stream, viewer, False)
        if state != "connected":
            _disconnected_ui("emg", stream)
        assert imgui.get_scroll_max_x() == imgui.get_scroll_max_y() == 0
        imgui.end()

    for _ in range(4):
        bounds.clear()
        labels.clear()
        imgui_frame(draw)
    assert all(right <= clip + 1 for _, right, clip in bounds), bounds
    if state == "connected":
        for control in ("pause", "df", "channels", "display", "chrome"):
            assert any(label.endswith(f"##emg_{control}") for label in labels), labels
        assert any(label.startswith("Auto") for label in labels)
        assert any(label.startswith("Manual") for label in labels)
    else:
        assert any(label.endswith("##emg_reconnect") for label in labels)
        assert any("connect" in label.lower() or "source" in label.lower() for label in labels)
