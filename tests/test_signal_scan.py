"""Signal discovery actions stay together and fit real, scaled viewer cells."""

import platform
from pathlib import Path
from types import SimpleNamespace

import pytest
from imgui_bundle import hello_imgui, imgui
from imgui_bundle import icons_fontawesome_6 as fa

from myogestic import Context, _scale, _theme
from myogestic.sources import LSLSource
from myogestic.stream import Stream, StreamInfo
from myogestic.widgets.common import PRIMARY_FILL, muted, ui_px
from myogestic.widgets.signals import _scan
from myogestic.widgets.signals._controls import render_controls
from myogestic.widgets.signals._state import ViewerState


@pytest.fixture
def scan_ui(imgui_frame, monkeypatch):
    """Capture real item geometry with the application's body and icon fonts."""
    monkeypatch.setattr(_scan, "_scans", {})
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    io = imgui.get_io()
    font_path = Path(_theme._SYS_FONTS.get(platform.system(), ""))
    if not font_path.is_file():
        font_path = Path(hello_imgui.asset_file_full_path("fonts/Roboto/Roboto-Regular.ttf"))
    io.font_default = io.fonts.add_font_from_file_ttf(str(font_path), 14)
    config = imgui.ImFontConfig()
    config.merge_mode = True
    io.fonts.add_font_from_file_ttf(
        hello_imgui.asset_file_full_path("fonts/Font_Awesome_6_Free-Solid-900.otf"), 14, config,
    )
    stream = Stream("emg", source=LSLSource("scan-test"), window_ms=1000)
    ui = SimpleNamespace(stream=stream, items=[], tooltips=[], frames=[], bounds=(),
                         state=_scan._ScanState(), jobs=[], click="", selection=None)
    _scan._scans["emg"] = ui.state

    for method in ("button", "combo", "text", "text_wrapped", "text_colored"):
        original = getattr(imgui, method)

        def item(*args, _original=original, _method=method, **kwargs):
            result = _original(*args, **kwargs)
            label = args[1] if _method == "text_colored" else args[0]
            ui.items.append(SimpleNamespace(
                kind=_method, label=label,
                lo=tuple(imgui.get_item_rect_min()), hi=tuple(imgui.get_item_rect_max()),
                color=tuple(args[0] if _method == "text_colored"
                            else imgui.get_style_color_vec4(imgui.Col_.text)),
                fill=tuple(imgui.get_style_color_vec4(imgui.Col_.button)),
            ))
            if _method == "button" and label == ui.click:
                ui.click = ""
                return True
            if _method == "combo" and ui.selection is not None:
                selected, ui.selection = ui.selection, None
                return True, selected
            return result

        monkeypatch.setattr(imgui, method, item)

    monkeypatch.setattr(imgui, "set_item_tooltip", ui.tooltips.append)
    monkeypatch.setattr(_scan._threading, "Thread", lambda *, target, daemon: SimpleNamespace(
        start=lambda: ui.jobs.append(target),
    ))

    def render(width=640, scale=1, *, connected=False, show_connect=True, frames=3):
        monkeypatch.setattr(_scale, "_current", scale)
        _theme.apply_theme()
        style = imgui.get_style()
        style.scale_all_sizes(scale)
        style.font_scale_main = scale
        io.display_size = imgui.ImVec2(max(width, 700), 900)

        def draw():
            imgui.set_next_window_pos(imgui.ImVec2(0, 0))
            imgui.set_next_window_size(imgui.ImVec2(width, 850))
            imgui.begin("scan-cell", flags=imgui.WindowFlags_.no_title_bar)
            origin = imgui.get_cursor_screen_pos()
            avail = imgui.get_content_region_avail()
            ui.bounds = (origin.x, origin.y, origin.x + avail.x, origin.y + avail.y)
            if connected:
                stream.info = StreamInfo(n_channels=8, fs=2048)
                stream.status = "connected"
                ctx = Context(streams={"emg": stream, "aux": stream})
                viewer = ViewerState(show_retarget=True)
                render_controls(ctx, "scan-viewer", "emg", stream, viewer, True)
            else:
                _scan._disconnected_ui("emg", stream, show_connect=show_connect)
            ui.scroll = (imgui.get_scroll_max_x(), imgui.get_scroll_max_y())
            imgui.end()

        ui.frames.clear()
        for _ in range(frames):
            ui.items.clear()
            ui.tooltips.clear()
            imgui_frame(draw)
            ui.frames.append(list(ui.items))
        return ui

    ui.render = render
    return ui


def _actions(items):
    connect, = [item for item in items if item.label.endswith("##emg_reconnect")]
    scan, = [item for item in items if "Scan" in item.label]
    return connect, scan


def _assert_centered(items, bounds):
    center = (min(item.lo[0] for item in items) + max(item.hi[0] for item in items)) / 2
    assert center == pytest.approx((bounds[0] + bounds[2]) / 2, abs=1)


def _assert_action_layout(items, bounds):
    connect, scan = _actions(items)
    pair_width = sum(item.hi[0] - item.lo[0] for item in (connect, scan))
    pair_width += imgui.get_style().item_spacing.x
    scan_top = scan.lo[1]
    if scan.kind == "text_colored":
        scan_top -= imgui.get_style().frame_padding.y
    if pair_width <= bounds[2] - bounds[0]:
        assert scan_top == pytest.approx(connect.lo[1], abs=1)
        assert scan.lo[0] >= connect.hi[0]
        _assert_centered([connect, scan], bounds)
    else:
        assert scan_top >= connect.hi[1]
        _assert_centered([connect], bounds)
        _assert_centered([scan], bounds)


@pytest.mark.parametrize("scale", [1, 2])
@pytest.mark.parametrize("width", [320, 640])
def test_empty_state_actions_share_a_centered_row_or_wrap(scan_ui, width, scale):
    view = scan_ui.render(width, scale)
    for items in view.frames:
        _assert_action_layout(items, view.bounds)
        connect, scan = _actions(items)
        assert connect.fill == tuple(PRIMARY_FILL)
        assert scan.fill != connect.fill
        assert scan.label.startswith(f"{fa.ICON_FA_ARROWS_ROTATE}  Scan")
    assert "Look for other outlets" in view.tooltips


@pytest.mark.parametrize("scale", [1, 2])
@pytest.mark.parametrize("width", [320, 1200])
@pytest.mark.parametrize("busy", [False, True])
def test_results_center_directly_below_actions_and_fit(scan_ui, width, scale, busy):
    scan_ui.state.busy = busy
    scan_ui.state.results = [{"name": "An outlet with a long name " * 5, "info": "64 channels"}]
    view = scan_ui.render(width, scale)
    for items in view.frames:
        combo, = [item for item in items if item.kind == "combo"]
        connect, = [item for item in items if item.label == "Connect##emg"]
        actions = _actions(items)
        assert combo.lo[1] == pytest.approx(connect.lo[1], abs=1)
        # An aligned status occupies a full frame, including bottom padding.
        bottom = max(item.hi[1] + (imgui.get_style().frame_padding.y
                                  if item.kind == "text_colored" else 0) for item in actions)
        assert combo.lo[1] == pytest.approx(bottom + imgui.get_style().item_spacing.y, abs=1)
        _assert_centered([combo, connect], view.bounds)
        if width == 1200:
            assert combo.hi[0] - combo.lo[0] == pytest.approx(ui_px(300), abs=1)
        for item in items:
            assert view.bounds[0] - 1 <= item.lo[0] <= item.hi[0] <= view.bounds[2] + 1, item.label
            assert view.bounds[1] - 1 <= item.lo[1] <= item.hi[1] <= view.bounds[3] + 1, item.label
    assert view.scroll == (0, 0)


@pytest.mark.parametrize("scale", [1, 2])
@pytest.mark.parametrize("width", [320, 640])
def test_scanning_stays_in_the_action_group_with_muted_status(scan_ui, width, scale):
    scan_ui.state.busy = True
    view = scan_ui.render(width, scale)
    connect, status = _actions(view.items)
    assert status.label == "Scanning…"
    assert status.kind == "text_colored"
    assert status.color == tuple(muted())
    assert not any(item.kind == "button" and "Scan" in item.label for item in view.items)
    _assert_action_layout([connect, status], view.bounds)


@pytest.mark.parametrize("scale", [1, 2])
@pytest.mark.parametrize("width", [320, 640])
@pytest.mark.parametrize("busy", [False, True])
def test_connected_retarget_still_draws_scan_and_results(scan_ui, width, scale, busy):
    scan_ui.state.busy = busy
    scan_ui.state.results = [{"name": "Another outlet", "info": "8 channels"}]
    view = scan_ui.render(width, scale, connected=True)
    assert any("Scan" in item.label for item in view.items)
    assert any(item.label == "##scan_emg" for item in view.items)
    assert any(item.label == "Connect##emg" for item in view.items)
    assert not any(item.label.endswith("##emg_reconnect") for item in view.items)
    for item in view.items:
        if "Scan" in item.label or item.label in ("##scan_emg", "Connect##emg"):
            assert view.bounds[0] - 1 <= item.lo[0] <= item.hi[0] <= view.bounds[2] + 1


def test_scan_and_selected_connection_keep_their_behavior(scan_ui, monkeypatch):
    results = [{"name": "First", "info": "8 ch"}, {"name": "Second", "info": "16 ch"}]
    monkeypatch.setattr(scan_ui.stream._source, "discover", lambda: results)
    connections = []
    monkeypatch.setattr(scan_ui.stream, "reconnect", lambda name=None: connections.append(name))
    view = scan_ui.render()
    scan_ui.click = _actions(view.items)[1].label
    scan_ui.render(frames=1)
    assert scan_ui.state.busy
    scan_ui.jobs.pop()()
    assert not scan_ui.state.busy
    assert scan_ui.state.results == results
    scan_ui.selection = 1
    scan_ui.click = "Connect##emg"
    scan_ui.render(frames=1)
    scan_ui.jobs.pop()()
    assert connections == ["Second"]
    assert scan_ui.state.results == []
    scan_ui.click = _actions(scan_ui.items)[0].label
    scan_ui.render(frames=1)
    scan_ui.jobs.pop()()
    assert connections == ["Second", None]


def test_show_connect_false_hides_all_discovery_controls(scan_ui):
    scan_ui.state.results = [{"name": "Another outlet", "info": "8 ch"}]
    view = scan_ui.render(show_connect=False)
    assert not any(item.kind in ("button", "combo") for item in view.items)


def test_source_without_discovery_keeps_centered_connect(scan_ui, monkeypatch):
    monkeypatch.setattr(scan_ui.stream._source, "discover", None)
    view = scan_ui.render(320, 2)
    buttons = [item for item in view.items if item.kind == "button"]
    assert len(buttons) == 1
    _assert_centered(buttons, view.bounds)
