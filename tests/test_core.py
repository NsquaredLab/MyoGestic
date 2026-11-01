"""Core tests — only idle ↔ recording. ML pipeline tests live in test_ml.py."""

import ctypes
import json
import shutil
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from mne_lsl.lsl import StreamInfo as LSLStreamInfo
from mne_lsl.lsl import StreamOutlet, local_clock

from myogestic import _browser, core
from myogestic.core import App, can_transition
from myogestic.sources.lsl import LSLSource
from myogestic.stream import Stream, StreamInfo


def start_synthetic_stream(name="CoreTestEMG", n_channels=8, fs=256):
    """Start a fake LSL stream in a background thread. Returns stop function."""
    info = LSLStreamInfo(name, "EMG", n_channels, fs, "float32", "")
    outlet = StreamOutlet(info)
    running = [True]

    def _push():
        chunk_size = 32
        interval = chunk_size / fs
        while running[0]:
            chunk = np.random.randn(chunk_size, n_channels).astype(np.float32)
            for sample in chunk:
                outlet.push_sample(sample)
            time.sleep(interval)

    threading.Thread(target=_push, daemon=True).start()
    return lambda: running.__setitem__(0, False)


def test_can_transition():
    """Verify the core state transition table (idle ↔ recording only)."""
    assert can_transition("idle", "recording")
    assert can_transition("recording", "idle")
    # ML states are not core — can_transition returns False for them
    assert not can_transition("idle", "training")
    assert not can_transition("idle", "predicting")
    assert not can_transition("recording", "predicting")


def test_recording_transitions():
    """idle → recording → idle using a live LSL stream."""
    stop_lsl = start_synthetic_stream("CoreTestEMG", n_channels=4, fs=128)
    time.sleep(0.5)

    stream = Stream("emg", source=LSLSource("CoreTestEMG"), window_ms=200)
    app = App("TestApp")
    app.streams(stream)

    stream.reconnect()  # the loop never attaches on its own
    stream.start()
    time.sleep(1.0)

    assert app.ctx.state == "idle"
    session_path = "/tmp/myogestic_test_sessions"
    app.start_recording(base_path=session_path)
    assert app.ctx.state == "recording"
    assert app.ctx.session is not None
    assert stream._session is app.ctx.session

    time.sleep(1.0)
    app.ctx.session.add_label(0, timestamp=local_clock())
    time.sleep(0.5)
    app.ctx.session.add_label(1, timestamp=local_clock())

    app.stop_recording()
    assert app.ctx.state == "idle"
    assert stream._session is None
    assert len(app.ctx.session.label_track) == 2

    stream.stop()
    stop_lsl()
    shutil.rmtree(session_path, ignore_errors=True)


def test_invalid_transitions_are_noop():
    """Calling start_recording while already recording does nothing."""
    stop_lsl = start_synthetic_stream("NoopTestEMG", n_channels=2, fs=64)
    time.sleep(0.5)

    stream = Stream("sig", source=LSLSource("NoopTestEMG"), window_ms=100)
    app = App("NoopTest")
    app.streams(stream)
    stream.start()
    time.sleep(0.5)

    app.start_recording(base_path="/tmp/myogestic_noop_test")
    assert app.ctx.state == "recording"
    first_session = app.ctx.session

    app.start_recording(base_path="/tmp/myogestic_noop_test2")
    assert app.ctx.session is first_session  # unchanged
    # Refusal must surface a status message (was silent before Phase 4)
    assert "Cannot start recording" in app.ctx.status_message

    app.stop_recording()
    assert app.ctx.state == "idle"

    # stop_recording from idle now also surfaces a status message
    app.stop_recording()
    assert "Cannot stop recording" in app.ctx.status_message

    stream.stop()
    stop_lsl()
    shutil.rmtree("/tmp/myogestic_noop_test", ignore_errors=True)


def test_run_is_not_reentrant():
    """Calling run() while already running raises."""
    app = App("Reentrant")
    app._running = True
    import pytest

    with pytest.raises(RuntimeError, match="not re-entrant"):
        app.run()
    app._running = False


def test_run_unknown_mode_raises_before_startup():
    """Bad mode must fail loudly before any threads start."""
    import pytest

    app = App("UnknownMode")
    with pytest.raises(ValueError, match="unknown mode"):
        app.run(mode="banana")
    assert app._running is False  # didn't even enter the run body


def test_before_run_hooks_registered():
    """Extensions can register startup hooks without subclassing."""
    app = App("Hooks")
    called = []
    app.before_run_hooks.append(lambda a: called.append("before"))
    app.cleanup_hooks.append(lambda a: called.append("cleanup"))
    assert len(app.before_run_hooks) == 1
    assert len(app.cleanup_hooks) == 1


def test_run_cleanup_fires_on_before_run_hook_failure(capsys):
    """If a before_run hook raises, cleanup hooks must still run (try/finally)."""
    app = App("CleanupOnFail")

    # Register UI so run() doesn't bail on missing _ui_fn
    @app.ui
    def _ui(ctx):
        pass

    cleanup_calls: list[str] = []
    app.before_run_hooks.append(lambda a: cleanup_calls.append("hook1_ok"))
    app.before_run_hooks.append(lambda a: (_ for _ in ()).throw(RuntimeError("hook2 boom")))
    app.cleanup_hooks.append(lambda a: cleanup_calls.append("cleanup1"))
    app.cleanup_hooks.append(lambda a: cleanup_calls.append("cleanup2"))

    import pytest

    with pytest.raises(RuntimeError, match="hook2 boom"):
        app.run(mode="headless")

    # hook1 ran, cleanups ran despite hook2 raising
    assert "hook1_ok" in cleanup_calls
    assert "cleanup1" in cleanup_calls
    assert "cleanup2" in cleanup_calls
    # _running reset after failure
    assert app._running is False


def test_start_recording_skips_disconnected_streams():
    """start_recording must not attach session to a stream whose info is None —
    zarr would fail on append without init_stream."""
    stream = Stream("never_connects", source=LSLSource("NoSuchStream"), window_ms=200)
    app = App("RecordingSkipDisconnected")
    app.streams(stream)

    # Don't start() the stream — info stays None
    assert stream.info is None

    app.start_recording(base_path="/tmp/myogestic_disconn_test")
    assert stream._session is None  # skipped
    assert app.ctx.state == "recording"
    assert "No connected streams" in app.ctx.status_message

    app.stop_recording()
    import shutil

    shutil.rmtree("/tmp/myogestic_disconn_test", ignore_errors=True)


def test_run_cleanup_continues_on_cleanup_hook_failure():
    """A cleanup hook that raises must not prevent later cleanup hooks."""
    app = App("CleanupChain")

    @app.ui
    def _ui(ctx):
        pass

    calls: list[str] = []
    # Force run to complete immediately by failing in a before_run hook
    # (simulates a startup error but lets us observe cleanup behavior).
    app.before_run_hooks.append(lambda a: (_ for _ in ()).throw(RuntimeError("fail")))
    app.cleanup_hooks.append(lambda a: (_ for _ in ()).throw(Exception("cleanup boom")))
    app.cleanup_hooks.append(lambda a: calls.append("after_boom"))

    import pytest

    with pytest.raises(RuntimeError):
        app.run(mode="headless")

    # The second cleanup hook ran even though the first one raised
    assert calls == ["after_boom"]


# --- Pyodide: no threads exist there -----------------------------------------
#
# Every `threading.Thread(...).start()` on a path the browser playground reaches raises
# `RuntimeError: can't start new thread`. That is how the playground broke: the GLFW
# stderr filter started a pump thread before the first frame, so `App.run()` died on the
# boot path with a traceback instead of a window.


def test_the_glfw_stderr_filter_starts_no_thread_in_the_browser(monkeypatch):
    """It is a no-op there: Pyodide has no threads, and the warning it collapses is a
    macOS multi-monitor artefact that cannot arise in a browser anyway."""
    import myogestic._browser
    from myogestic.core import _collapse_glfw_monitor_spam

    monkeypatch.setattr(myogestic._browser, "IS_BROWSER", True)

    def _no_threads(*a, **k):
        raise AssertionError("started a thread in the browser")

    monkeypatch.setattr(threading, "Thread", _no_threads)

    with _collapse_glfw_monitor_spam():
        pass  # must enter and exit cleanly


# --- recording as a flag beside the state ------------------------------------------


class _FakeSource:
    def connect(self) -> StreamInfo:
        return StreamInfo(n_channels=4, fs=100.0)

    def read(self):
        return None, None

    def disconnect(self) -> None:
        pass


def _connected_app() -> tuple[App, Stream]:
    app = App("flag-test")
    stream = Stream("emg", source=_FakeSource(), window_ms=100)
    app.streams(stream)
    assert stream.reconnect()
    return app, stream


def _only_zip(folder: Path) -> Path:
    zips = list(folder.glob("*.session.zip"))
    assert len(zips) == 1, zips
    return zips[0]


def test_recording_while_predicting_leaves_the_state_alone(tmp_path, recordable_predicting):
    app, stream = _connected_app()
    app.ctx.state = "predicting"
    app.start_recording(str(tmp_path))
    assert app.ctx.recording is True
    assert app.ctx.state == "predicting"
    assert stream._session is app.ctx.session
    app.stop_recording(wait=True)
    assert app.ctx.recording is False
    assert app.ctx.state == "predicting"
    assert stream._session is None
    assert _only_zip(tmp_path).exists()


def test_recording_from_idle_still_shows_the_recording_state(tmp_path):
    app, _ = _connected_app()
    app.start_recording(str(tmp_path))
    assert (app.ctx.recording, app.ctx.state) == (True, "recording")
    app.stop_recording(wait=True)
    assert (app.ctx.recording, app.ctx.state) == (False, "idle")


def test_start_recording_is_refused_outside_recordable_states(tmp_path):
    app, _ = _connected_app()
    app.ctx.state = "training"
    app.start_recording(str(tmp_path))
    assert app.ctx.recording is False
    assert "Cannot start recording" in app.ctx.status_message
    assert not list(tmp_path.iterdir())
    # Plain state names, not enum reprs (StrEnum's repr is "<AppState.IDLE: 'idle'>").
    assert "'idle'" in app.ctx.status_message and "<" not in app.ctx.status_message


def test_finalize_hooks_run_after_freeze_and_before_meta(tmp_path):
    app, _ = _connected_app()
    seen = {}

    def hook(session):
        seen["event_streams"] = session.event_streams
        session.extras["hook"] = "ran"
        session.append_event("late", [1.0], 0.0)  # must be dropped: the session is frozen

    app.finalize_hooks.append(hook)
    app.start_recording(str(tmp_path))
    app.ctx.session.append_event("prediction.x", [1.0], 0.0)
    app.stop_recording(wait=True)
    with zipfile.ZipFile(_only_zip(tmp_path)) as zf:
        meta = json.loads(zf.read("meta.json"))
        names = zf.namelist()
    assert seen["event_streams"] == ("prediction.x",)
    assert meta["extras"]["hook"] == "ran"
    assert "late" not in meta["streams"] and not any(n.startswith("late.zarr") for n in names)


def test_a_failing_finalize_hook_does_not_lose_the_take(tmp_path):
    app, _ = _connected_app()
    app.finalize_hooks.append(lambda session: 1 / 0)
    app.start_recording(str(tmp_path))
    app.stop_recording(wait=True)
    assert _only_zip(tmp_path).exists()
    assert any("Finalize hook failed" in line for line in app.ctx.logs)


def test_discard_while_predicting_runs_no_hook(tmp_path, recordable_predicting):
    app, _ = _connected_app()
    app.finalize_hooks.append(lambda session: pytest.fail("hook ran on discard"))
    app.ctx.state = "predicting"
    app.start_recording(str(tmp_path))
    app.discard_recording()
    assert (app.ctx.recording, app.ctx.state, app.ctx.session) == (False, "predicting", None)
    assert not list(tmp_path.iterdir())


def test_cleanup_finalises_an_open_take(tmp_path):
    app, _ = _connected_app()
    app.start_recording(str(tmp_path))
    app._cleanup()
    assert app.ctx.recording is False
    assert _only_zip(tmp_path).exists()


@pytest.mark.parametrize("take_count", [1, 2])
def test_cleanup_waits_for_takes_stopped_by_a_hook(tmp_path, monkeypatch, take_count):
    app, stream = _connected_app()
    release = threading.Event()
    all_finalizing = threading.Event()
    cleanup_done = threading.Event()
    finalizers = []

    def hold_finalization(session):
        finalizers.append(threading.current_thread())
        if len(finalizers) == take_count:
            all_finalizing.set()
        assert release.wait(5), "test did not release finalization"

    app.finalize_hooks.append(hold_finalization)
    for _ in range(take_count - 1):
        app.start_recording(str(tmp_path))
        app.stop_recording()
    app.start_recording(str(tmp_path))
    app.cleanup_hooks.append(lambda app: app.stop_recording())
    pending_at_stream_stop = []
    stop_stream = stream.stop

    def stop():
        pending_at_stream_stop.extend(app.ctx.pending_saves)
        stop_stream()

    monkeypatch.setattr(stream, "stop", stop)

    def cleanup():
        try:
            app._cleanup()
        finally:
            cleanup_done.set()

    cleanup_thread = threading.Thread(target=cleanup)
    cleanup_thread.start()
    try:
        assert all_finalizing.wait(5)
        assert not cleanup_done.wait(0.05), "cleanup returned before finalization"
    finally:
        release.set()
        cleanup_thread.join(5)
        for thread in finalizers:
            thread.join(5)

    assert not cleanup_thread.is_alive()
    assert not app.ctx.recording
    assert not app.ctx.pending_saves
    assert pending_at_stream_stop == []
    archives = list(tmp_path.glob("*.session.zip"))
    assert len(archives) == take_count
    for archive in archives:
        with zipfile.ZipFile(archive) as saved:
            assert json.loads(saved.read("meta.json"))["app_name"] == app.name


def test_cleanup_logs_a_save_timeout_and_finishes_teardown(tmp_path, monkeypatch, caplog):
    app = App("save timeout")
    app._running = True
    app.ctx.pending_saves.add(tmp_path)
    stopped = []
    app.ctx.streams["emg"] = SimpleNamespace(stop=lambda: stopped.append("stream"))
    app.ctx.bridges["hand"] = SimpleNamespace(stop=lambda: stopped.append("bridge"))
    monkeypatch.setattr(core, "_FINALIZE_TIMEOUT_S", 0.01)

    app._cleanup()

    assert stopped == ["stream", "bridge"]
    assert app._running is False
    assert app.ctx.pending_saves == {tmp_path}
    assert "waiting for 1 recording save(s) at exit" in caplog.text
    assert "Timed out" in caplog.text


def test_add_stream_is_refused_while_a_take_is_open_under_predicting(
    tmp_path, recordable_predicting
):
    app, _ = _connected_app()
    app.ctx.state = "predicting"
    app.start_recording(str(tmp_path))
    assert app.add_stream(Stream("imu", source=_FakeSource(), window_ms=100)) is False
    assert "Cannot add a stream while recording" in app.ctx.status_message
    assert "imu" not in app.ctx.streams
    app.stop_recording(wait=True)
    assert app.add_stream(Stream("imu", source=_FakeSource(), window_ms=100)) is True


def test_remove_stream_is_refused_while_a_take_is_open_under_predicting(
    tmp_path, recordable_predicting
):
    app, _ = _connected_app()
    app.ctx.state = "predicting"
    app.start_recording(str(tmp_path))
    assert app.remove_stream("emg") is False
    assert "emg" in app.ctx.streams
    app.stop_recording(wait=True)
    assert app.remove_stream("emg") is True


# --- Starting with a locked or sleeping display ---


@pytest.fixture
def startup(monkeypatch):
    """Record startup and cleanup without opening a native window or stream."""
    monkeypatch.setattr(core.sys, "platform", "darwin")
    monkeypatch.setattr(_browser, "IS_BROWSER", False)
    app = core.App("Display startup")
    events = []
    app.ctx.streams["test"] = SimpleNamespace(
        start=lambda: events.append("stream start"),
        stop=lambda: events.append("stream stop"),
    )
    app.before_run_hooks.append(lambda app: events.append("before run"))
    app.cleanup_hooks.append(lambda app: events.append("cleanup"))
    monkeypatch.setattr(app, "_gui_loop", lambda **kwargs: events.append(("gui", kwargs)))
    monkeypatch.setattr(app, "_headless_loop", lambda: events.append("headless"))
    return app, events


@pytest.mark.parametrize("fullscreen", [False, True])
def test_waits_for_display_before_starting_streams_or_hooks(
    startup, monkeypatch, capsys, fullscreen
):
    app, events = startup
    counts = iter([0, 0, 1])

    def query():
        events.append("query")
        assert not app._running
        return next(counts)

    def sleep(seconds):
        events.append(("sleep", seconds))
        assert not app._running
        assert "stream start" not in events

    monkeypatch.setattr(core, "_active_display_count", query, raising=False)
    monkeypatch.setattr(core.time, "sleep", sleep)

    app.run(window_size=(960, 640), fullscreen=fullscreen)

    assert events == [
        "query",
        ("sleep", 1.0),
        "query",
        ("sleep", 1.0),
        "query",
        "stream start",
        "before run",
        ("gui", {"window_size": (960, 640), "fullscreen": fullscreen}),
        "cleanup",
        "stream stop",
    ]
    assert not app._running
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "waiting for a display — the screen is locked or asleep" in lines[0]
    assert "continuing" in lines[1]


def test_active_display_starts_immediately_without_wait_messages(startup, monkeypatch, capsys):
    app, events = startup
    monkeypatch.setattr(core, "_active_display_count", lambda: 1, raising=False)
    monkeypatch.setattr(core.time, "sleep", lambda _: pytest.fail("unexpected wait"))
    app.run()
    assert events[:2] == ["stream start", "before run"]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("interrupt_at", ["query", "sleep"])
def test_ctrl_c_during_wait_exits_without_starting_resources(startup, monkeypatch, interrupt_at):
    app, events = startup

    def interrupt(*args):
        raise KeyboardInterrupt

    query = interrupt if interrupt_at == "query" else lambda: 0
    monkeypatch.setattr(core, "_active_display_count", query, raising=False)
    monkeypatch.setattr(core.time, "sleep", interrupt)

    app.run()

    assert events == []
    assert not app._running
    # An interrupted wait must not leave the app marked as already running.
    monkeypatch.setattr(core, "_active_display_count", lambda: 1)
    app.run()
    assert events[:2] == ["stream start", "before run"]


@pytest.mark.parametrize(
    "platform,browser,mode",
    [
        ("linux", False, "gui"),
        ("win32", False, "gui"),
        ("emscripten", True, "gui"),
        ("darwin", True, "gui"),
        ("darwin", False, "headless"),
    ],
)
def test_other_platforms_browser_and_headless_do_not_query_displays(
    startup, monkeypatch, platform, browser, mode
):
    app, events = startup
    monkeypatch.setattr(core.sys, "platform", platform)
    monkeypatch.setattr(_browser, "IS_BROWSER", browser)
    monkeypatch.setattr(
        core,
        "_active_display_count",
        lambda: pytest.fail("unexpected display query"),
        raising=False,
    )
    app.run(mode=mode)
    assert events[:2] == ["stream start", "before run"]
    assert ("cleanup" in events) is not browser


@pytest.mark.parametrize("count", [0, 1, 3])
def test_display_count_uses_coregraphics_without_pyobjc(monkeypatch, count):
    def get_active_display_list(max_displays, displays, count_pointer):
        assert max_displays == 0
        assert displays is None
        ctypes.cast(count_pointer, ctypes.POINTER(ctypes.c_uint32))[0] = count
        return 0

    library = SimpleNamespace(CGGetActiveDisplayList=get_active_display_list)
    monkeypatch.setattr(ctypes, "CDLL", lambda path: library)

    assert core._active_display_count() == count


def test_failed_display_query_does_not_start_native_gui(startup, monkeypatch):
    app, events = startup
    library = SimpleNamespace(CGGetActiveDisplayList=lambda *args: 1000)
    monkeypatch.setattr(ctypes, "CDLL", lambda path: library)

    with pytest.raises(OSError, match="CGGetActiveDisplayList.*1000"):
        app.run()

    assert events == []
    assert not app._running
