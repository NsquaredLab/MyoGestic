"""Adding and removing streams while the app runs.

`App.run` starts each registered stream exactly once on the way in, and
`start_recording` sizes one Zarr array per stream. Both facts constrain what may
happen to `ctx.streams` afterwards, and this is where those constraints live.
"""

import pytest
from imgui_bundle import imgui

from myogestic.core import App, AppState
from myogestic.sources import SyntheticSource
from myogestic.stream import Stream, StreamInfo
from myogestic.widgets import StreamManager
from myogestic.widgets.panels.stream_manager import _clean_name


class _FakeSource:
    def __init__(self, n_channels: int = 4) -> None:
        self.n_channels = n_channels
        self.disconnects = 0

    def connect(self) -> StreamInfo:
        return StreamInfo(n_channels=self.n_channels, fs=100.0)

    def read(self):
        return None, None

    def disconnect(self) -> None:
        self.disconnects += 1


def _stream(name: str = "force") -> Stream:
    return Stream(name, source=_FakeSource(), window_ms=100)


# --- the name reaches disk as <name>.zarr, so it is a trust boundary ---------
@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("force", "force"),
        ("  Force  ", "force"),
        ("aux 1", "aux1"),
        ("../../etc/passwd", "etcpasswd"),
        ("...", ""),
        ("a" * 80, "a" * 32),
    ],
)
def test_a_typed_stream_name_cannot_escape_the_session_folder(typed, expected):
    assert _clean_name(typed) == expected


# --- lifecycle ---------------------------------------------------------------
def test_a_stream_added_before_run_is_not_started_twice():
    """`run` starts every registered stream. Starting here as well would give it
    two acquire threads on the same buffers."""
    app = App("test")
    stream = _stream()
    assert app.add_stream(stream) is True
    assert stream._running is False, "started before the app was running"
    assert app.ctx.streams["force"] is stream


def test_a_stream_added_after_run_is_started_here():
    """Nothing else will: `run` has already been past."""
    app = App("test")
    app._running = True  # as `App.run` leaves it
    stream = _stream()
    try:
        assert app.add_stream(stream) is True
        assert stream._running is True, "the acquire loop was never started"
    finally:
        stream.stop()


def test_removing_a_stream_stops_it_and_closes_its_source():
    app = App("test")
    app._running = True
    stream = _stream()
    app.add_stream(stream)
    source = stream._source

    assert app.remove_stream("force") is True

    assert "force" not in app.ctx.streams
    assert stream._running is False, "the acquire thread was left running"
    assert source.disconnects >= 1


def test_a_duplicate_name_is_refused_rather_than_overwriting():
    """Overwriting would strand the running acquire thread of what it replaced."""
    app = App("test")
    first = _stream()
    app.add_stream(first)

    assert app.add_stream(_stream()) is False
    assert "already exists" in app.ctx.status_message
    assert app.ctx.streams["force"] is first


def test_removing_a_stream_that_is_not_there_is_refused_quietly():
    assert App("test").remove_stream("nope") is False


# --- the recording guard -----------------------------------------------------
def test_streams_cannot_be_added_or_removed_while_recording(tmp_path):
    """A session sizes one Zarr array per stream when recording starts.

    A stream appearing afterwards has nowhere to write; one vanishing mid-take
    keeps the session attached and is never finalised.
    """
    app = App("test")
    existing = Stream("emg", source=_FakeSource(), window_ms=100)
    app.streams(existing)
    assert existing.reconnect()
    app.start_recording(str(tmp_path / "sessions"))
    assert app.ctx.state == AppState.RECORDING
    try:
        assert app.add_stream(_stream()) is False
        assert "while recording" in app.ctx.status_message
        assert app.remove_stream("emg") is False
        assert "emg" in app.ctx.streams
    finally:
        app.discard_recording()


# --- the widget --------------------------------------------------------------
def test_removing_from_the_row_list_does_not_mutate_during_iteration(implot_frame, monkeypatch):
    """The rows are drawn by walking `ctx.streams`; popping mid-walk raises.

    The click has to be remembered and acted on after the loop.
    """
    app = App("test")
    app._running = True
    for name in ("emg", "force", "aux"):
        app.add_stream(Stream(name, source=SyntheticSource(n_channels=2), window_ms=100))
    manager = StreamManager(on_add=lambda n: None, on_remove=app.remove_stream)

    from myogestic.widgets.panels import stream_manager as module

    # Stand in for simultaneous chip events; apply only one deferred removal.
    monkeypatch.setattr(module, "stream_chip", lambda *args, **kwargs: (False, True))
    try:
        def draw() -> None:
            imgui.begin_child("cell", imgui.ImVec2(500, 300))
            manager.ui(app.ctx)
            imgui.end_child()

        implot_frame(draw)
    finally:
        for s in list(app.ctx.streams.values()):
            s.stop()

    assert len(app.ctx.streams) == 2, "more than one removal was applied in one frame"


def test_the_manager_renders_with_no_streams_at_all(implot_frame):
    """The state an app starts in when it declares none up front."""
    app = App("test")
    manager = StreamManager(on_add=lambda n: None, on_remove=lambda n: None)

    def draw() -> None:
        imgui.begin_child("cell", imgui.ImVec2(500, 300))
        manager.ui(app.ctx)
        imgui.end_child()

    implot_frame(draw)


@pytest.fixture
def manager_actions(monkeypatch):
    seen, click = [], {"id": ""}
    button = imgui.button

    def tracked(label, *args):
        result = button(label, *args)
        disabled = bool(imgui.get_item_flags() & imgui.ItemFlags_.disabled)
        seen.append((label, disabled))
        return result or bool(click["id"] and label.endswith(click["id"]) and not disabled)

    monkeypatch.setattr(imgui, "button", tracked)
    return seen, click


def test_chips_select_then_remove_after_iteration(imgui_frame, manager_actions):
    app = App("test")
    for name in ("emg", "force", "aux"):
        app.add_stream(_stream(name))
    manager = StreamManager(on_add=lambda name: None, on_remove=app.remove_stream)
    seen, click = manager_actions
    click["id"] = "##sm_stream_force"
    imgui_frame(lambda: manager.ui(app.ctx))
    assert manager._selected == "force"
    seen.clear()
    click["id"] = "##sm_remove_force"
    imgui_frame(lambda: manager.ui(app.ctx))
    assert "force" not in app.ctx.streams
    assert manager._selected == "aux"
    assert len([label for label, _ in seen if "sm_remove" in label]) == 1


def test_plus_opens_name_field_and_add_cleans_then_selects(imgui_frame, manager_actions, monkeypatch):
    app = App("test")
    manager = StreamManager(on_add=lambda name: app.add_stream(_stream(name)), on_remove=app.remove_stream)
    _, click = manager_actions
    click["id"] = "##sm_add_open"
    imgui_frame(lambda: manager.ui(app.ctx))
    assert manager._adding
    monkeypatch.setattr(imgui, "input_text_with_hint", lambda *args: (True, " F/o.rce_2 "))
    click["id"] = "##sm_add"
    imgui_frame(lambda: manager.ui(app.ctx))
    assert list(app.ctx.streams) == ["force_2"]
    assert manager._selected == "force_2"
    assert not manager._adding


def test_recording_dims_chips_and_explains_lock(imgui_frame, manager_actions, monkeypatch):
    from myogestic.widgets.panels import stream_manager as module

    app = App("test")
    app.streams(_stream("emg"), _stream("force"))
    app.ctx.state = AppState.RECORDING
    app.ctx.recording = True
    manager = StreamManager(on_add=lambda name: pytest.fail(name), on_remove=lambda name: pytest.fail(name))
    words = []
    text = imgui.text_wrapped

    def tracked(value):
        words.append(value)
        return text(value)

    monkeypatch.setattr(module.imgui, "text_wrapped", tracked)
    seen, click = manager_actions
    click["id"] = "##sm_add_open"
    imgui_frame(lambda: manager.ui(app.ctx))
    assert all(disabled for label, disabled in seen if "##sm_" in label)
    assert "Stop the recording to add or remove streams." in words
    assert not manager._adding


@pytest.mark.parametrize("scale,width", [(1, 320), (2, 320), (2, 640)])
def test_manager_chips_and_inline_add_fit_light_narrow_cells(imgui_frame, monkeypatch, scale, width):
    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    app = App("test")
    app.streams(_stream("emg"), _stream("very_long_stream_name_for_wrapping"))
    manager = StreamManager(on_add=lambda name: None, on_remove=lambda name: None)
    manager._adding = True
    items = []
    for kind in ("button", "input_text_with_hint"):
        original = getattr(imgui, kind)

        def tracked(*args, original=original):
            result = original(*args)
            lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            origin, size = imgui.get_window_pos(), imgui.get_window_size()
            items.append((args[0], lo.x >= origin.x, hi.x <= origin.x + size.x))
            return result

        monkeypatch.setattr(imgui, kind, tracked)

    def draw():
        imgui.begin_child("manager-card", imgui.ImVec2(width, 350))
        manager.ui(app.ctx)
        imgui.end_child()

    imgui_frame(draw)
    assert items and all(left and right for _, left, right in items), items


@pytest.mark.parametrize("typed", ["...", " EMG "])
def test_manager_rejects_empty_or_duplicate_names(imgui_frame, manager_actions, monkeypatch, typed):
    app = App("test")
    app.streams(_stream("emg"))
    manager = StreamManager(on_add=lambda name: pytest.fail(name), on_remove=lambda name: None)
    manager._adding = True
    monkeypatch.setattr(imgui, "input_text_with_hint", lambda *args: (True, typed))
    seen, click = manager_actions
    click["id"] = "##sm_add"
    imgui_frame(lambda: manager.ui(app.ctx))
    assert ("Add##sm_add", True) in seen


def test_cancel_clears_only_its_own_manager(imgui_frame, manager_actions):
    app = App("test")
    first = StreamManager(on_add=lambda name: None, on_remove=lambda name: None, widget_id="one")
    second = StreamManager(on_add=lambda name: None, on_remove=lambda name: None, widget_id="two")
    first._adding = second._adding = True
    first._typed, second._typed = "force", "emg"
    manager_actions[1]["id"] = "##sm_add_cancel"
    imgui_frame(lambda: first.ui(app.ctx))
    assert not first._adding and not first._typed
    assert second._adding and second._typed == "emg"


def test_the_last_stream_cannot_be_removed(imgui_frame, manager_actions):
    app = App("test")
    app.streams(_stream("emg"))
    manager = StreamManager(on_add=lambda name: None, on_remove=lambda name: pytest.fail(name))
    manager_actions[1]["id"] = "##sm_remove_emg"
    imgui_frame(lambda: manager.ui(app.ctx))
    assert not any("sm_remove" in label for label, _ in manager_actions[0])
