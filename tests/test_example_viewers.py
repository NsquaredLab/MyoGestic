"""Signal viewer controls and guidance fit small tiles at double scale."""

import pytest


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
