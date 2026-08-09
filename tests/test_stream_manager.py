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
def test_removing_from_the_row_list_does_not_mutate_during_iteration(implot_frame):
    """The rows are drawn by walking `ctx.streams`; popping mid-walk raises.

    The click has to be remembered and acted on after the loop.
    """
    app = App("test")
    app._running = True
    for name in ("emg", "force", "aux"):
        app.add_stream(Stream(name, source=SyntheticSource(n_channels=2), window_ms=100))
    manager = StreamManager(on_add=lambda n: None, on_remove=app.remove_stream)

    # Stand in for a click on every row at once — the worst case for the walk.
    original_row = StreamManager._row
    try:
        StreamManager._row = lambda self, name, stream, *, recording: True

        def draw() -> None:
            imgui.begin_child("cell", imgui.ImVec2(500, 300))
            manager.ui(app.ctx)
            imgui.end_child()

        implot_frame(draw)  # a RuntimeError here is the bug
    finally:
        StreamManager._row = original_row
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
