"""Core tests — only idle ↔ recording. ML pipeline tests live in test_ml.py."""

import shutil
import threading
import time

import numpy as np
from mne_lsl.lsl import StreamInfo, StreamOutlet, local_clock

from myogestic.core import App, can_transition
from myogestic.sources.lsl import LSLSource
from myogestic.stream import Stream


def start_synthetic_stream(name="CoreTestEMG", n_channels=8, fs=256):
    """Start a fake LSL stream in a background thread. Returns stop function."""
    info = StreamInfo(name, "EMG", n_channels, fs, "float32", "")
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

    stream = Stream("emg", source=LSLSource("CoreTestEMG"), window_seconds=0.2)
    app = App("TestApp")
    app.streams(stream)

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

    stream = Stream("sig", source=LSLSource("NoopTestEMG"), window_seconds=0.1)
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
        app.run(mode="gui")

    # hook1 ran, cleanups ran despite hook2 raising
    assert "hook1_ok" in cleanup_calls
    assert "cleanup1" in cleanup_calls
    assert "cleanup2" in cleanup_calls
    # _running reset after failure
    assert app._running is False


def test_start_recording_skips_disconnected_streams():
    """start_recording must not attach session to a stream whose info is None —
    zarr would fail on append without init_stream."""
    stream = Stream("never_connects", source=LSLSource("NoSuchStream"), window_seconds=0.2)
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
        app.run()

    # The second cleanup hook ran even though the first one raised
    assert calls == ["after_boom"]
