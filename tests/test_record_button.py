"""Naming and discarding a recording: `RecordButton`, `Session.name`, `discard_recording`.

The dialog itself needs a GUI, so what is covered here is everything it drives:
the name reaching ``meta.json`` and the archive filename, the slug refusing to
become a path, capture ending at the Stop click rather than at Save, and a
discarded take leaving nothing behind.
"""

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from myogestic.core import App, AppState
from myogestic.session._core import Session, _slug
from myogestic.stream import Stream, StreamInfo
from myogestic.widgets.panels.recording import RecordButton, _elapsed_str


class _FakeSource:
    """A source that hands over one fixed chunk, then nothing."""

    def __init__(self, n_channels: int = 4) -> None:
        self.n_channels = n_channels

    def connect(self) -> StreamInfo:
        return StreamInfo(n_channels=self.n_channels, fs=100.0)

    def read(self):
        return None, None

    def disconnect(self) -> None:
        pass


def _recorded_app(tmp_path: Path) -> tuple[App, Stream]:
    """An App with one connected stream, mid-recording, with samples in it."""
    app = App("test")
    stream = Stream("emg", source=_FakeSource(4), window_ms=100)
    app.streams(stream)
    assert stream.reconnect()
    app.start_recording(str(tmp_path / "sessions"))
    assert app.ctx.session is not None
    app.ctx.session.append("emg", np.zeros((10, 4), dtype=np.float32), np.arange(10.0))
    return app, stream


# --- the slug is a filename, so it is a trust boundary ----------------------
@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("fist day 2", "fist-day-2"),
        ("my_run-3", "my_run-3"),
        ("../../etc/passwd", "etc-passwd"),  # separators and .. cannot survive
        ("  ", ""),
        ("...", ""),
        ("a" * 80, "a" * 40),  # capped
    ],
)
def test_a_typed_name_becomes_a_safe_filename_fragment(typed, expected):
    assert _slug(typed) == expected


def test_a_slug_never_contains_a_path_separator():
    """Whitelist, not blacklist — the property that makes the above exhaustive."""
    hostile = "../a/b\\c\0d:e*f?g\"h<i>j|k"
    assert set(_slug(hostile)) <= set("abcdefghijk-_")


# --- the name reaches disk ---------------------------------------------------
def test_the_name_lands_in_meta_and_in_the_archive_filename(tmp_path):
    app, _ = _recorded_app(tmp_path)
    app.ctx.session.name = "subject 03 fist"
    app.stop_recording()

    zips = list((tmp_path / "sessions").glob("*.session.zip"))
    # stop_recording packs on a daemon thread; wait for it rather than sleeping.
    for _ in range(200):
        zips = list((tmp_path / "sessions").glob("*.session.zip"))
        if zips:
            break
        import time

        time.sleep(0.05)
    assert zips, "session was never packed"
    assert "subject-03-fist" in zips[0].name
    with zipfile.ZipFile(zips[0]) as zf:
        meta = json.loads(zf.read("meta.json"))
    assert meta["name"] == "subject 03 fist"


def test_an_unnamed_recording_still_packs_and_omits_the_key(tmp_path):
    """Naming is optional; the timestamp always identifies the session."""
    session = Session(str(tmp_path))
    session.init_stream("emg", StreamInfo(n_channels=4, fs=100.0))
    session.save_meta("test")
    meta = json.loads((session.path / "meta.json").read_text())
    assert "name" not in meta

    stem = session.path.name
    assert session.pack_to_zip().name == f"{stem}.session.zip"


def test_a_session_with_no_connected_stream_still_packs(tmp_path):
    """Record-before-Connect makes exactly this session, and Stop must not fail.

    A `ZipStore` that never opened an array raises ``AttributeError: _lock`` on
    close, so the verification pass has to be skipped when there is nothing to
    verify.
    """
    session = Session(str(tmp_path))
    session.save_meta("test")

    zip_path = session.pack_to_zip()

    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        assert "meta.json" in zf.namelist()


# --- discard -----------------------------------------------------------------
def test_discarding_a_recording_deletes_it_and_returns_to_idle(tmp_path):
    app, _ = _recorded_app(tmp_path)
    folder = app.ctx.session.path
    assert folder.exists()

    app.discard_recording()

    assert not folder.exists(), "discarded recording left its folder behind"
    assert list((tmp_path / "sessions").glob("*.session.zip")) == []
    assert app.ctx.state == AppState.IDLE
    assert app.ctx.session is None


def test_discarding_when_not_recording_is_refused(tmp_path):
    app = App("test")
    app.discard_recording()
    assert "Cannot discard" in app.ctx.status_message


# --- capture ends at the click, not at Save ----------------------------------
def test_stop_detaches_the_streams_before_the_dialog_opens(tmp_path):
    """The whole reason `_stop` exists separately from `on_stop`.

    Whatever the operator does while the naming dialog is open — including
    taking their hand off the electrodes — must not reach the recording.
    """
    app, stream = _recorded_app(tmp_path)
    recorder = RecordButton(on_record=lambda: None, on_stop=lambda: None)
    recorder._started = 0.0

    recorder._stop(app.ctx)

    assert stream._session is None, "stream still recording while naming"
    assert recorder._naming is True
    # Data appended after the click must not be captured.
    before = app.ctx.session.stores["emg"].shape[0]
    stream._acquire_step()
    assert app.ctx.session.stores["emg"].shape[0] == before


def test_saving_attaches_the_typed_name_to_the_live_session(tmp_path):
    app, _ = _recorded_app(tmp_path)
    stopped: list[bool] = []
    recorder = RecordButton(on_record=lambda: None, on_stop=lambda: stopped.append(True))
    recorder._naming = True
    recorder._name = "  trailing space  "

    recorder._save(app.ctx)

    assert app.ctx.session.name == "trailing space"
    assert stopped == [True], "the App was never asked to finalise the session"
    assert recorder._naming is False


def test_the_dialog_clears_itself_if_something_else_stops_the_recording():
    """A protocol script calling stop_recording leaves nothing to name."""
    recorder = RecordButton(on_record=lambda: None, on_stop=lambda: None)
    recorder._naming = True

    recorder._sync(recording=False)

    assert recorder._naming is False


def test_discard_without_a_handler_still_leaves_the_widget_usable():
    """`on_discard` is optional; the dialog hides the button but the path is safe."""
    recorder = RecordButton(on_record=lambda: None, on_stop=lambda: None)
    recorder._naming = True
    recorder._name = "x"

    recorder._discard()

    assert recorder._naming is False
    assert recorder._name == ""


@pytest.mark.parametrize(
    ("seconds", "shown"), [(0, "0:00"), (9.9, "0:09"), (61, "1:01"), (600, "10:00")]
)
def test_elapsed_reads_like_a_stopwatch(seconds, shown):
    assert _elapsed_str(seconds) == shown


def test_session_extras_round_trip_through_the_archive(tmp_path):
    """A widget's contribution has to survive packing, or it was never recorded.

    `extras` is where a force calibration lands — the numbers relating a force
    recorded in device counts to a target recorded in %MVC.
    """
    from myogestic.session import open_session_store

    session = Session(str(tmp_path))
    session.init_stream("emg", StreamInfo(n_channels=4, fs=100.0))
    session.extras["force_tracking"] = [{"zero": 0.25, "mvc": 3.75, "channel": 64}]
    session.save_meta("test")
    zip_path = session.pack_to_zip()

    reopened = open_session_store(zip_path)
    try:
        blocks = reopened.extras["force_tracking"]
        assert blocks[0]["mvc"] == 3.75
        assert blocks[0]["channel"] == 64
    finally:
        reopened.close()


def test_the_name_the_operator_typed_survives_the_archive(tmp_path):
    """`name` is written to meta.json for one reason: to be read back out again.

    `open_session_store` builds its Session with `__new__`, so an attribute it forgets
    is not empty on the way back — it raises `AttributeError` on the public API.
    """
    from myogestic.session import open_session_store

    session = Session(str(tmp_path))
    session.init_stream("emg", StreamInfo(n_channels=4, fs=100.0))
    session.name = "subject-03 fist"
    session.save_meta("test")

    reopened = open_session_store(session.pack_to_zip())
    try:
        assert reopened.name == "subject-03 fist"
    finally:
        reopened.close()


def test_an_unnamed_session_reopens_with_an_empty_name(tmp_path):
    """No name typed, no `name` key in meta.json — and still not an AttributeError."""
    from myogestic.session import open_session_store

    session = Session(str(tmp_path))
    session.init_stream("emg", StreamInfo(n_channels=4, fs=100.0))
    session.save_meta("test")

    reopened = open_session_store(session.pack_to_zip())
    try:
        assert reopened.name == ""
    finally:
        reopened.close()


def test_a_session_with_no_extras_writes_no_extras_key():
    """Nothing contributed, nothing claimed."""
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        session = Session(tmp)
        session.init_stream("emg", StreamInfo(n_channels=4, fs=100.0))
        session.save_meta("test")
        meta = json.loads((session.path / "meta.json").read_text())
    assert "extras" not in meta
