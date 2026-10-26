"""Stream status rows, outlet selection, and cancellable connection attempts."""

import threading
import time
from types import SimpleNamespace

import pytest
from imgui_bundle import imgui

from myogestic.stream import Stream, StreamInfo
from myogestic.widgets import StreamPanel
from myogestic.widgets.common import IDLE, SUCCESS, WARNING
from myogestic.widgets.signals import stream_panel as module


class Source:
    def connect(self):
        return StreamInfo(n_channels=4, fs=1000)

    def disconnect(self):
        pass

    def read(self):
        return None, None


def context(streams):
    return SimpleNamespace(streams=streams, state="idle", log=lambda message: None)


def stream(name="emg"):
    return Stream(name, source=Source(), window_ms=100)


@pytest.fixture
def actions(monkeypatch):
    seen, click = [], {"id": ""}
    for kind in ("button", "small_button", "selectable"):
        original = getattr(imgui, kind)

        def tracked(label, *args, original=original, kind=kind, **kwargs):
            result = original(label, *args, **kwargs)
            disabled = bool(imgui.get_item_flags() & imgui.ItemFlags_.disabled)
            seen.append((label, disabled))
            clicked = bool(click["id"] and label.endswith(click["id"]) and not disabled)
            return (clicked or result[0], result[1]) if kind == "selectable" else clicked or result

        monkeypatch.setattr(imgui, kind, tracked)
    return seen, click


@pytest.mark.parametrize("state,tone", [("idle", IDLE), ("connected", SUCCESS), ("failed", WARNING), ("mixed", WARNING)])
def test_header_reports_worst_state_and_rows_say_what_to_do(imgui_frame, monkeypatch, actions, state, tone):
    item = stream()
    if state in ("connected", "mixed"):
        assert item.reconnect()
        item.status = "connected"
    if state == "failed":
        item.last_error = "No amplifier answered"
    ctx = context({"emg": item})
    if state == "mixed":
        ctx.streams["force"] = stream("force")
    headers, words = [], []
    header, mono = module.panel_header, module.mono_text

    def tracked_header(*args, **kwargs):
        headers.append(kwargs.get("status"))
        return header(*args, **kwargs)

    def tracked_mono(text, *args):
        words.append(text)
        return mono(text, *args)

    monkeypatch.setattr(module, "panel_header", tracked_header)
    monkeypatch.setattr(module, "mono_text", tracked_mono)
    imgui_frame(lambda: StreamPanel(selectable=False).ui(ctx))
    assert headers == [tone]
    labels = [label for label, _ in actions[0]]
    assert any("sp_rescan" in label for label in labels)
    if state == "idle":
        assert any("not connected" in text for text in words)
        assert any(label.startswith("Connect##") for label in labels)
    if state == "failed":
        assert any("No amplifier answered" in text for text in words)
        assert any(label.startswith("Retry##") for label in labels)


def test_selectable_connect_opens_outlets_and_connects_the_chosen_target(imgui_frame, monkeypatch, actions):
    item = stream()
    item._source.discover = lambda: [{"name": "Lab EMG", "info": "8ch 2000Hz EMG"}]
    panel = StreamPanel(widget_id="outlets")
    ctx = context({"emg": item})
    scan = module._ScanState(results=item._source.discover())
    monkeypatch.setitem(module._scans, "emg", scan)
    monkeypatch.setattr(module, "_kickoff_scan", lambda *args: None)
    targets = []
    monkeypatch.setattr(panel, "_connect", lambda name, stream, ctx, target=None: targets.append(target))
    seen, click = actions
    click["id"] = "##sp_conn_emg"
    imgui_frame(lambda: panel.ui(ctx))
    assert targets == []
    click["id"] = "##sp_outlet_0"
    imgui_frame(lambda: panel.ui(ctx))
    assert targets == ["Lab EMG"]
    assert any("8 ch · 2000 Hz" in label for label, _ in seen)


def test_abort_discards_a_late_success_and_is_local_to_the_panel():
    entered, release = threading.Event(), threading.Event()
    item = stream()
    reconnect = item.reconnect

    def blocked(target=None):
        entered.set()
        assert release.wait(2)
        return reconnect(target)

    item.reconnect = blocked
    first = StreamPanel(widget_id="first")
    second = StreamPanel(widget_id="second")
    ctx = context({"emg": item})
    first._connect("emg", item, ctx)
    try:
        assert entered.wait(1)
        assert not second._attempts
        first._abort("emg", item, ctx)
    finally:
        release.set()
    deadline = time.monotonic() + 2
    while first._attempts["emg"].busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not first._attempts["emg"].busy
    assert item.info is None
    assert item.last_error == ""
    assert item.status == "disconnected"


@pytest.mark.parametrize("scale,width", [(1, 320), (2, 320), (2, 640)])
@pytest.mark.parametrize("state", ["idle", "connected", "failed", "connecting"])
def test_stream_rows_fit_on_one_line_in_light_theme(imgui_frame, monkeypatch, scale, width, state):
    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    item = stream()
    panel = StreamPanel(selectable=False)
    ctx = context({"a_very_long_stream_name_for_a_narrow_card": item})
    if state == "connected":
        assert item.reconnect()
        item.status = "connected"
    if state == "failed":
        item.last_error = "A long error explaining that the amplifier could not be reached"
    if state == "connecting":
        monkeypatch.setattr(module._threading.Thread, "start", lambda self: None)
        panel._connect(next(iter(ctx.streams)), item, ctx)
    rects = []
    for kind in ("button", "small_button", "text_unformatted", "text_colored"):
        original = getattr(imgui, kind)

        def tracked(*args, original=original, kind=kind, **kwargs):
            result = original(*args, **kwargs)
            lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            origin, size = imgui.get_window_pos(), imgui.get_window_size()
            rects.append((kind, lo.x, hi.x, origin.x, origin.x + size.x))
            return result

        monkeypatch.setattr(imgui, kind, tracked)

    def draw():
        imgui.begin_child("card", imgui.ImVec2(width, 350))
        before = imgui.get_cursor_pos_y()
        panel.ui(ctx)
        height = imgui.get_cursor_pos_y() - before
        assert height < imgui.get_frame_height() * 3.5
        imgui.end_child()

    imgui_frame(draw)
    assert rects and all(lo >= left and hi <= right for _, lo, hi, left, right in rects), rects


def test_retry_reuses_the_failed_target_without_reopening_discovery(imgui_frame, monkeypatch, actions):
    item = stream()
    item._source.discover = lambda: []
    item.last_error = "Source unavailable"
    panel = StreamPanel()
    calls = []
    monkeypatch.setattr(panel, "_connect", lambda *args: calls.append(args))
    actions[1]["id"] = "##sp_conn_emg"
    imgui_frame(lambda: panel.ui(context({"emg": item})))
    assert len(calls) == 1
    assert calls[0][:2] == ("emg", item)


def test_connecting_row_shows_elapsed_and_abort(imgui_frame, monkeypatch, actions):
    item = stream()
    panel = StreamPanel()
    ctx = context({"emg": item})
    monkeypatch.setattr(module._threading.Thread, "start", lambda self: None)
    panel._connect("emg", item, ctx)
    panel._attempts["emg"].started -= 12
    words, aborted = [], []
    mono = module.mono_text

    def tracked(text, *args):
        words.append(text)
        return mono(text, *args)

    monkeypatch.setattr(module, "mono_text", tracked)
    monkeypatch.setattr(panel, "_abort", lambda *args: aborted.append(args))
    actions[1]["id"] = "##sp_conn_emg"
    imgui_frame(lambda: panel.ui(ctx))
    assert "connecting… 12 s" in words
    assert len(aborted) == 1
    assert ("Abort##sp_conn_emg", False) in actions[0]


def test_connect_exception_is_visible_and_retry_can_clear_it(imgui_frame, monkeypatch):
    item = stream()
    panel = StreamPanel(selectable=False)
    ctx = context({"emg": item})
    reconnect = item.reconnect

    def failed(target=None):
        raise RuntimeError("Amplifier refused the connection")

    monkeypatch.setattr(item, "reconnect", failed)
    panel._connect("emg", item, ctx)
    deadline = time.monotonic() + 2
    while panel._attempts["emg"].busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not panel._attempts["emg"].busy
    assert item.last_error == "Amplifier refused the connection"
    monkeypatch.setattr(item, "reconnect", reconnect)
    panel._connect("emg", item, ctx)
    deadline = time.monotonic() + 2
    while panel._attempts["emg"].busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert item.info is not None
    assert item.last_error == ""


def test_header_rescan_refreshes_every_registered_source(imgui_frame, monkeypatch, actions):
    ctx = context({"emg": stream(), "force": stream("force")})
    calls = []
    monkeypatch.setattr(module, "_kickoff_scan", lambda name, stream: calls.append(name))
    actions[1]["id"] = "##sp_rescan"
    imgui_frame(lambda: StreamPanel().ui(ctx))
    assert calls == ["emg", "force"]


def test_recording_disables_connection_actions(imgui_frame, monkeypatch, actions):
    item = stream()
    panel = StreamPanel(selectable=False)
    ctx = context({"emg": item})
    ctx.state = "recording"
    ctx.recording = True
    monkeypatch.setattr(panel, "_connect", lambda *args: pytest.fail("reconnected while recording"))
    actions[1]["id"] = "##sp_conn_emg"
    imgui_frame(lambda: panel.ui(ctx))
    assert ("Connect##sp_conn_emg", True) in actions[0]


def test_multiline_error_keeps_one_line_and_full_tooltip(imgui_frame, monkeypatch):
    item = stream()
    item.last_error = "Amplifier failed\nCheck its connection"
    words, tooltips = [], []
    mono = module.mono_text

    def tracked(text, *args):
        words.append(text)
        return mono(text, *args)

    monkeypatch.setattr(module, "mono_text", tracked)
    monkeypatch.setattr(imgui, "set_item_tooltip", tooltips.append)
    imgui_frame(lambda: StreamPanel().ui(context({"emg": item})))
    assert all("\n" not in text for text in words)
    assert item.last_error in tooltips
