"""Signal discovery actions stay together and fit real, scaled viewer cells."""

import platform
from pathlib import Path
from types import SimpleNamespace

import pytest
from imgui_bundle import hello_imgui, imgui

from myogestic import Context, _scale, _theme
from myogestic.sources import LSLSource
from myogestic.stream import Stream, StreamInfo
from myogestic.widgets.common import PRIMARY_FILL
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
        hello_imgui.asset_file_full_path("fonts/Font_Awesome_6_Free-Solid-900.otf"),
        14,
        config,
    )
    stream = Stream("emg", source=LSLSource("scan-test"), window_ms=1000)
    ui = SimpleNamespace(
        stream=stream,
        items=[],
        tooltips=[],
        frames=[],
        bounds=(),
        state=_scan._ScanState(),
        jobs=[],
        click="",
        selection=None,
    )
    _scan._scans["emg"] = ui.state

    for method in ("button", "combo", "text", "text_wrapped", "text_colored"):
        original = getattr(imgui, method)

        def item(*args, _original=original, _method=method, **kwargs):
            result = _original(*args, **kwargs)
            label = args[1] if _method == "text_colored" else args[0]
            ui.items.append(
                SimpleNamespace(
                    kind=_method,
                    label=label,
                    lo=tuple(imgui.get_item_rect_min()),
                    hi=tuple(imgui.get_item_rect_max()),
                    color=tuple(
                        args[0]
                        if _method == "text_colored"
                        else imgui.get_style_color_vec4(imgui.Col_.text)
                    ),
                    fill=tuple(imgui.get_style_color_vec4(imgui.Col_.button)),
                )
            )
            if _method == "button" and label == ui.click:
                ui.click = ""
                return True
            if _method == "combo" and ui.selection is not None:
                selected, ui.selection = ui.selection, None
                return True, selected
            return result

        monkeypatch.setattr(imgui, method, item)

    monkeypatch.setattr(imgui, "set_item_tooltip", ui.tooltips.append)
    monkeypatch.setattr(
        _scan._threading,
        "Thread",
        lambda *, target, daemon: SimpleNamespace(
            start=lambda: ui.jobs.append(target),
        ),
    )

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


def _named(items, suffix):
    return [item for item in items if item.label.endswith(suffix)]


def _assert_centered(items, bounds):
    center = (min(item.lo[0] for item in items) + max(item.hi[0] for item in items)) / 2
    assert center == pytest.approx((bounds[0] + bounds[2]) / 2, abs=1)


@pytest.mark.parametrize("scale", [1, 2])
@pytest.mark.parametrize("width", [320, 640])
@pytest.mark.parametrize("scanned", [False, True])
def test_carousel_and_one_connect_are_centred_and_fit(scan_ui, width, scale, scanned):
    """‹ card › over one primary Connect that names the stream, inside the cell."""
    if scanned:
        scan_ui.state.scanned = True
        scan_ui.state.results = [
            {"name": "scan-test", "info": "8 ch · 2048 Hz · EMG", "type": "EMG"},
            {
                "name": "An outlet with a long name " * 5,
                "info": "64 ch · 2048 Hz · EMG",
                "type": "EMG",
            },
        ]
    view = scan_ui.render(width, scale)
    for items in view.frames:
        (prev,) = _named(items, "##emg_prev")
        (step,) = _named(items, "##emg_next")
        (connect,) = _named(items, "##emg_reconnect")
        assert connect.fill == tuple(PRIMARY_FILL)
        # The label names the stream, ellipsized in a narrow cell.
        assert "Connect scan" in connect.label
        assert [item for item in items if item.kind == "button" and "Connect" in item.label] == [
            connect
        ]
        assert prev.lo[1] == pytest.approx(step.lo[1], abs=1)
        assert connect.lo[1] > prev.hi[1]
        _assert_centered([prev, step], view.bounds)
        _assert_centered([connect], view.bounds)
        for item in items:
            assert view.bounds[0] - 1 <= item.lo[0] <= item.hi[0] <= view.bounds[2] + 1, item.label
    assert view.scroll[0] == 0


def test_stepping_past_the_last_stream_scans_then_shows_the_next(scan_ui, monkeypatch):
    """› past the app's stream looks for others and lands on the next one of its kind."""
    results = [
        {"name": "scan-test", "info": "8 ch", "type": "EMG"},
        {"name": "VHI.thumb_curl", "info": "1 ch", "type": "Control"},
        {"name": "Second", "info": "16 ch", "type": "EMG"},
    ]
    monkeypatch.setattr(scan_ui.stream._source, "discover", lambda: results)
    connections = []
    monkeypatch.setattr(scan_ui.stream, "reconnect", lambda name=None: connections.append(name))
    view = scan_ui.render(frames=1)
    assert not scan_ui.jobs, "nothing scans until somebody asks"
    scan_ui.click = _named(view.items, "##emg_next")[0].label
    scan_ui.render(frames=1)
    assert scan_ui.state.busy
    scan_ui.jobs.pop()()
    view = scan_ui.render(frames=1)
    assert scan_ui.state.shown == "Second", "the Control outlet is not a stream to view"
    (connect,) = _named(view.items, "##emg_reconnect")
    assert "Connect Second" in connect.label
    scan_ui.click = connect.label
    scan_ui.render(frames=1)
    scan_ui.jobs.pop()()
    assert connections == ["Second"]
    scan_ui.click = _named(view.items, "##emg_prev")[0].label
    scan_ui.render(frames=1)
    view = scan_ui.render(frames=1)
    (connect,) = _named(view.items, "##emg_reconnect")
    assert "Connect scan-test" in connect.label
    scan_ui.click = connect.label
    scan_ui.render(frames=1)
    scan_ui.jobs.pop()()
    assert connections == ["Second", None], "the app's own stream reattaches its own source"


@pytest.mark.parametrize(
    ("stream_type", "found", "expected"),
    [
        # The app's stream was found as EMG: only EMG streams follow it.
        (None, ["a:Control", "b:EMG", "scan-test:EMG", "m:Markers", "c:EMG"], ["b", "c"]),
        # An explicit type wins over the inferred one.
        ("Control", ["a:Control", "b:EMG", "scan-test:EMG"], ["a"]),
        # The app's stream is missing, so no type: everything but control and markers.
        (None, ["a:Control", "b:EMG", "m:Markers", "u:"], ["b", "u"]),
    ],
    ids=["inferred", "explicit", "unknown"],
)
def test_the_carousel_offers_the_apps_stream_then_one_kind(stream_type, found, expected):
    results = []
    for entry in found:
        name, kind = entry.split(":")
        results.append({"name": name, "info": ""} | ({"type": kind} if kind else {}))
    stream = Stream("emg", source=LSLSource("scan-test"), window_ms=1000)
    items, own = _scan._carousel(stream, _scan._ScanState(results=results), stream_type)
    assert own == "scan-test"
    assert [item["name"] for item in items] == ["scan-test", *expected]


def test_a_failure_shows_its_first_sentence_and_keeps_the_rest_on_hover(scan_ui):
    error = "LSL stream 'scan-test' not found. Available streams: ['a', 'b', 'c']"
    scan_ui.stream.last_error = error
    view = scan_ui.render(frames=1)
    assert any(item.label == "LSL stream 'scan-test' not found." for item in view.items)
    assert error in view.tooltips
    (connect,) = _named(view.items, "##emg_reconnect")
    assert "Try again" in connect.label


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
