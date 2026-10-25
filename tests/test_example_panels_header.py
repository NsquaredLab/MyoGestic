"""Panel demos open with the shared header without losing their body content."""

import runpy
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from imgui_bundle import hello_imgui, imgui

from myogestic import Grid, Layout, Px, _scale, _theme
from myogestic.grid import _AreaCell
from myogestic.widgets import AppHeader, AppLogo

PANELS = Path(__file__).resolve().parents[1] / "examples" / "panels"
TITLES = {
    "app_logo": "AppLogo",
    "control_map_editor": "ControlMapEditor",
    "device_picker": "DevicePicker",
    "feature_selector": "FeatureSelector",
    "heatmap": "Heatmap",
    "image": "Image",
    "line_plot": "LinePlot",
    "log_panel": "LogPanel",
    "participant_panel": "ParticipantPanel",
    "pipeline_panel": "PipelinePanel",
    "pong": "PongTask",
    "post_processor": "PostProcessor",
    "prediction_label": "PredictionLabel",
    "process_launcher": "ProcessLauncher",
    "raw_signal_viewer": "RawSignalViewer",
    "record_button": "RecordButton",
    "recording_controls": "RecordingControls",
    "scatter2d": "Scatter2D",
    "scatter3d": "Scatter3D",
    "session_manager": "SessionManager",
    "signal_viewer": "SignalViewer",
    "step_bar": "StepBar",
    "stream_manager": "StreamManager",
    "stream_panel": "StreamPanel",
    "template_inspector": "TemplateInspector",
    "tracking_task": "TrackingTask",
    "trial_preview": "TrialPreview",
    "vhi_movements": "VhiMovementPanel",
}
STATE_DEMOS = {
    "record_button", "recording_controls", "session_manager", "pipeline_panel",
    "prediction_label", "pong", "tracking_task",
}


def test_every_panel_demo_is_covered():
    """A new demo must join the header and visibility checks."""
    assert {path.stem for path in PANELS.glob("*.py") if path.stem != "app_header"} == set(TITLES)


@pytest.mark.parametrize("name", TITLES)
@pytest.mark.parametrize("width", [2560, 1280, 800])
def test_panel_header_and_body_fit_at_scale_two(name, width, monkeypatch, implot_frame):
    """Draw the real UI in light mode at the default size and narrow widths."""
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width, 1656)
    # Keep image geometry real while replacing only the GL texture backend.
    monkeypatch.setattr(hello_imgui, "asset_exists", lambda name: True)

    def asset(name):
        path = PANELS.parents[1] / "myogestic" / "assets" / name
        width, height = struct.unpack(">II", path.read_bytes()[16:24])
        return SimpleNamespace(texture_id=1, size=imgui.ImVec2(width, height))

    monkeypatch.setattr(hello_imgui, "image_and_size_from_asset", asset)
    monkeypatch.setattr(imgui, "image", lambda texture, size: imgui.dummy(size))
    namespace = runpy.run_path(str(PANELS / f"{name}.py"))
    app = namespace["app"]
    try:
        headers = [value for value in namespace.values() if isinstance(value, AppHeader)]
        assert len(headers) == 1, "each demo needs one shared application header"
        header = headers[0]
        assert header.title == TITLES[name]
        assert header.show_state is (name in STATE_DEMOS)
        assert header.steps is None and header.participant is None
        layouts = [value for value in namespace.values() if isinstance(value, (Grid, Layout))]
        assert len(layouts) == 1
        layout = layouts[0]
        grids = (layout._wide, layout._narrow) if isinstance(layout, Layout) else (layout,)
        for grid in grids:
            assert grid._areas["header"] == (0, 1, 0, grid.cols)
            assert grid._row_tracks[0] == Px(52)
            assert "header" in grid._bare

        cells, calls, logos, clipped = [], [], [], []
        active = []
        enter, leave = _AreaCell.__enter__, _AreaCell.__exit__
        header_ui = header.ui
        logo_ui = AppLogo.ui

        def enter_cell(cell):
            result = enter(cell)
            active.append(cell._name)
            return result

        def leave_cell(cell, *args):
            cells.append((cell._name, tuple(imgui.get_window_pos()),
                          tuple(imgui.get_window_size()), imgui.get_scroll_max_y()))
            active.pop()
            leave(cell, *args)

        def draw_header(ctx):
            calls.append(active[-1])
            return header_ui(ctx)

        def draw_logo(logo):
            logos.append(active[-1])
            return logo_ui(logo)

        def track(original):
            def draw(*args, **kwargs):
                result = original(*args, **kwargs)
                if active:
                    draw_list = imgui.get_window_draw_list()
                    lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
                    clip_lo, clip_hi = draw_list.get_clip_rect_min(), draw_list.get_clip_rect_max()
                    if lo.x < clip_lo.x - 1 or hi.x > clip_hi.x + 1 or lo.y < clip_lo.y - 1 or hi.y > clip_hi.y + 1:
                        clipped.append((active[-1], str(args), tuple(lo), tuple(hi),
                                        tuple(clip_lo), tuple(clip_hi)))
                return result
            return draw

        monkeypatch.setattr(_AreaCell, "__enter__", enter_cell)
        monkeypatch.setattr(_AreaCell, "__exit__", leave_cell)
        monkeypatch.setattr(header, "ui", draw_header)
        monkeypatch.setattr(AppLogo, "ui", draw_logo)
        for method in ("text", "text_unformatted", "text_colored", "text_disabled", "text_wrapped",
                       "button", "small_button", "slider_float"):
            monkeypatch.setattr(imgui, method, track(getattr(imgui, method)))

        def draw():
            imgui.set_next_window_pos(imgui.ImVec2(0, 0))
            imgui.set_next_window_size(imgui.ImVec2(width, 1656))
            imgui.begin("panel-header-probe", flags=(imgui.WindowFlags_.no_title_bar
                                                    | imgui.WindowFlags_.no_saved_settings))
            app._ui_fn(app.ctx)
            imgui.end()

        for _ in range(4):
            cells.clear()
            calls.clear()
            logos.clear()
            clipped.clear()
            implot_frame(draw)
        assert calls == ["header"]
        assert logos == (["header", "body"] if name == "app_logo" else ["header"])
        assert cells[0][0] == "header"
        assert cells[0][2][1] == 104
        header_bottom = cells[0][1][1] + cells[0][2][1]
        assert all(pos[1] >= header_bottom for _, pos, _, _ in cells[1:])
        assert all(pos[1] + size[1] <= 1656 for _, pos, size, _ in cells)
        assert all(scroll == 0 for _, _, _, scroll in cells), cells
        assert not clipped, clipped
    finally:
        for stream in app.ctx.streams.values():
            stream.stop()
