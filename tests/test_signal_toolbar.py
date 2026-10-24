"""Signal toolbar layout and reachability through its real ImGui popups."""

from types import SimpleNamespace

import pytest
from imgui_bundle import imgui

from myogestic.core import Context
from myogestic.sources import SyntheticSource
from myogestic.stream import Stream
from myogestic.widgets import SignalViewer, common
from myogestic.widgets.signals import _controls, _state
from myogestic.widgets.signals import viewer as viewer_module


@pytest.fixture
def toolbar(imgui_frame, monkeypatch):
    """Track submitted items, keeping real layout, popup and style-stack behavior."""
    monkeypatch.setattr(_state, "_viewers", {})
    ctx = Context()
    stream = Stream("emg", source=SyntheticSource(n_channels=8, fs=2048), window_ms=500, buffer_ms=60000)
    assert stream.reconnect()
    stream._acquire_step()
    ctx.streams["emg"] = stream
    viewer = SignalViewer("emg", widget_id="toolbar", selectable=True)
    ui = SimpleNamespace(
        ctx=ctx, viewer=viewer, items={}, click="", changes={}, popups=set(),
        title_y=0.0, plot_y=0.0, texts=[], width=900, bounds={},
    )

    def track(name):
        real = getattr(imgui, name)

        def submit(label, *args, **kwargs):
            result = real(label, *args, **kwargs)
            lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            ui.items[label] = (lo.x, lo.y, hi.x, hi.y, imgui.get_id(label))
            ui.bounds[label] = imgui.get_window_pos().x + imgui.get_window_size().x
            if label in ui.changes:
                return True, ui.changes.pop(label)
            if ui.click and label.endswith(ui.click):
                ui.click = ""
                return True
            return result

        monkeypatch.setattr(imgui, name, submit)

    for name in ("button", "small_button", "combo", "slider_float", "input_float", "checkbox"):
        track(name)

    real_popup = imgui.begin_popup

    def popup(label, *args, **kwargs):
        opened = real_popup(label, *args, **kwargs)
        if opened:
            ui.popups.add(label)
        return opened

    monkeypatch.setattr(imgui, "begin_popup", popup)
    real_header = common.panel_header

    def header(*args, **kwargs):
        real_header(*args, **kwargs)
        if args[0].startswith("SIGNAL"):
            ui.title_y = imgui.get_item_rect_min().y

    for module in (common, viewer_module, _controls):
        monkeypatch.setattr(module, "panel_header", header, raising=False)

    def plot(**kwargs):
        ui.plot_y = imgui.get_cursor_screen_pos().y
        imgui.dummy(imgui.ImVec2(1, 80))

    monkeypatch.setattr(viewer_module, "render_plot", plot)
    real_frame = viewer_module.build_signal_frame

    def signal_frame(stream, state, enabled):
        ui.state = state
        return real_frame(stream, state, enabled)

    monkeypatch.setattr(viewer_module, "build_signal_frame", signal_frame)

    def draw():
        ui.items.clear()
        ui.popups.clear()
        imgui.begin_child("toolbar_cell", imgui.ImVec2(ui.width, 450))
        viewer.ui(ctx)
        imgui.end_child()

    def frame(click="", changes=None):
        ui.click = click
        ui.changes.update(changes or {})
        imgui_frame(draw)

    ui.frame = frame
    try:
        yield ui
    finally:
        stream.disconnect()
        _controls._grid_ui.pop("toolbar", None)


def test_header_is_one_row(imgui_frame, toolbar):
    """A wide connected viewer gives the plot all but one header row."""
    toolbar.frame()
    assert toolbar.plot_y - toolbar.title_y <= (
        imgui.get_frame_height() + imgui.get_style().item_spacing.y
    )
    assert any(label.endswith("_display") for label in toolbar.items)


def test_display_popup_opens(imgui_frame, toolbar, monkeypatch):
    """Display opens a scoped popup and is selected on the following frame."""
    selected = []
    real_push = _controls.push_selected

    def push():
        selected.append(True)
        real_push()

    monkeypatch.setattr(_controls, "push_selected", push)
    toolbar.frame("toolbar_display")
    toolbar.frame()
    assert "toolbar_display_popup" in toolbar.popups
    assert selected, "the open Display button needs a persistent selected cue"
    assert any(label.endswith("toolbar_win") for label in toolbar.items)


def test_every_control_reachable(imgui_frame, toolbar):
    """Both popups retain all controls, including conditional range and RMS inputs."""
    toolbar.frame("toolbar_display")
    toolbar.frame(changes={"##toolbar_df": 3})
    toolbar.frame("toolbar_scale_seg1")
    expected = {
        "toolbar_pause", "toolbar_df", "toolbar_scale_seg0", "toolbar_scale_seg1",
        "toolbar_win", "toolbar_detail", "toolbar_one_to_one", "toolbar_gain",
        "toolbar_transient", "toolbar_lanes_seg0", "toolbar_lanes_seg1",
        "toolbar_rescale", "toolbar_notch_seg0", "toolbar_notch_seg1",
        "toolbar_notch_seg2", "toolbar_diag", "toolbar_ymin", "toolbar_ymax",
        "toolbar_rmswin", "toolbar_rmshop",
    }
    submitted = {label.split("##")[-1] for label in toolbar.items}
    assert expected <= submitted
    toolbar.frame("toolbar_channels")
    toolbar.frame()
    assert "toolbar_channels_popup" in toolbar.popups
    submitted = {label.split("##")[-1] for label in toolbar.items}
    assert {f"toolbar_bar_{op}" for op in ("all", "none", "invert", "edit")} <= submitted
    toolbar.frame("toolbar_bar_none")
    toolbar.frame()
    assert any(label.startswith("0/8 ch") for label in toolbar.items)
    toolbar.frame("toolbar_bar_invert")
    toolbar.frame()
    assert any(label.startswith("8/8 ch") for label in toolbar.items)
    toolbar.frame("toolbar_bar_edit")
    assert _controls._grid_ui["toolbar"].show_grid


@pytest.mark.parametrize("selectable,count,expected", [(True, 1, False), (True, 2, True), (False, 2, False)])
def test_stream_picker_only_with_two_streams(toolbar, selectable, count, expected):
    """Picker and reconnect consume header space only for selectable multi-stream viewers."""
    toolbar.viewer._selectable = selectable
    toolbar.ctx.streams["emg"]._source.discover = lambda: []
    if count == 2:
        toolbar.ctx.streams["aux"] = toolbar.ctx.streams["emg"]
    toolbar.frame()
    assert any(label.endswith("toolbar_sel") for label in toolbar.items) is expected
    assert any(label.endswith("toolbar_retarget") for label in toolbar.items) is expected


def test_collapsed_controls_hide_popups_and_leave_title(toolbar):
    """Collapsing an open popup hides controls without losing the title or restore toggle."""
    toolbar.frame("toolbar_display")
    toolbar.frame("toolbar_chrome")
    toolbar.frame()
    assert not toolbar.popups
    assert not any(label.endswith("toolbar_display") for label in toolbar.items)
    assert any(label.endswith("toolbar_chrome") for label in toolbar.items)
    assert toolbar.title_y > 0


def test_display_popup_controls_fit(toolbar):
    """Detailed statistics must not push their Show stats action out of the popup."""
    toolbar.frame("toolbar_display")
    toolbar.frame()
    toolbar.frame()
    assert any(label.endswith("toolbar_diag") for label in toolbar.items)
    for label, rect in toolbar.items.items():
        if label.endswith(("toolbar_diag", "toolbar_one_to_one", "toolbar_transient")):
            assert rect[2] <= toolbar.bounds[label], label


@pytest.mark.parametrize("control,value,attribute,expected", [
    ("##toolbar_win", 2.5, "window", 2.5),
    ("##toolbar_detail", 50.0, "detail_factor", 1.5),
    ("##toolbar_gain", 2.0, "gain", 2.0),
    ("##toolbar_transient", 20.0, "transient_ms", 20.0),
    ("toolbar_notch_seg1", None, "mains_notch", 50),
    ("toolbar_lanes_seg1", None, "per_channel_scale", True),
    ("toolbar_one_to_one", None, "one_to_one", True),
    ("toolbar_rescale", None, "rescale_pending", "shared"),
    ("toolbar_diag", None, "show_diagnostics", True),
])
def test_display_control_changes_state(toolbar, control, value, attribute, expected):
    """Moved controls still update the state consumed by the plot."""
    toolbar.frame("toolbar_display")
    toolbar.frame(control if value is None else "", {control: value} if value is not None else {})
    assert getattr(toolbar.state, attribute) == expected


@pytest.mark.parametrize("stream_count", [1, 2])
def test_narrow_header_wraps_without_overlapping_title(toolbar, stream_count):
    """A narrow header moves its controls below the title rather than drawing over it."""
    toolbar.width = 400
    if stream_count == 2:
        toolbar.ctx.streams["aux"] = toolbar.ctx.streams["emg"]
        toolbar.ctx.streams["emg"]._source.discover = lambda: []
    toolbar.frame()
    pause = next(rect for label, rect in toolbar.items.items() if label.endswith("toolbar_pause"))
    assert pause[1] >= toolbar.title_y + imgui.get_text_line_height_with_spacing()
    for label, rect in toolbar.items.items():
        assert rect[2] <= toolbar.bounds[label], label
