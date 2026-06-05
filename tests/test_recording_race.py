"""Regression tests for the stop-recording / acquire-loop append race.

Background
----------
``App.stop_recording()`` nulls each stream's session and then, on a daemon
thread, calls ``Session.pack_to_zip()`` which clears the session's Zarr
``stores`` / ``ts_stores``. The per-stream acquire thread may still be inside
``Session.append()`` (its ``if self._session is not None`` check already
passed), so the trailing chunk used to land *after* the stores were cleared →
``KeyError: '<stream>'`` killed the acquire thread.

The fix makes session attach/detach atomic with the acquire loop via
``Stream._session_lock``: ``detach_session()`` waits for any in-flight append,
so once it returns no append can be running and clearing the stores is safe.
"""

from __future__ import annotations

import tempfile
import threading
import time

import numpy as np

from myogestic.session import Session
from myogestic.stream import Stream, StreamInfo


class _FixedSource:
    """Source protocol stub: hands back one small, well-formed chunk per read."""

    def __init__(self, n_channels: int = 2, fs: float = 1000.0) -> None:
        self._info = StreamInfo(n_channels=n_channels, fs=fs, dtype=np.dtype("float32"))

    def connect(self) -> StreamInfo:
        return self._info

    def read(self):
        n = 4
        data = np.zeros((n, self._info.n_channels), dtype=np.float32)
        ts = np.arange(n, dtype=np.float64)
        return data, ts

    def disconnect(self) -> None:
        pass


def _connect_stream(stream: Stream) -> None:
    """Drive one acquire step so the stream connects + allocates buffers
    (the first step connects and returns without reading)."""
    stream._acquire_step()
    assert stream._connected


def test_detach_session_waits_for_inflight_append():
    """``detach_session()`` must not return while an append is in flight —
    that mutual exclusion is what stops ``pack_to_zip()``'s ``clear()`` from
    racing the acquire loop."""
    stream = Stream("emg", source=_FixedSource(), window_seconds=0.1, buffer_seconds=2)
    _connect_stream(stream)

    entered = threading.Event()
    proceed = threading.Event()
    order: list[str] = []

    class _GatedSession:
        """Stands in for Session; its append blocks until released so we can
        observe whether detach_session() waits."""

        def append(self, name, data, timestamps):  # noqa: ANN001
            order.append("append_enter")
            entered.set()
            assert proceed.wait(2.0), "append was never released"
            order.append("append_exit")

    stream.attach_session(_GatedSession())  # type: ignore[arg-type]

    # Run one acquire step on a worker thread; it will enter the gated append
    # and block there, holding _session_lock.
    step = threading.Thread(target=stream._acquire_step, daemon=True)
    step.start()
    assert entered.wait(2.0), "acquire step never reached session.append"

    # While the append is in flight, detach must block on _session_lock.
    detached = threading.Event()

    def _detach():
        stream.detach_session()
        order.append("detach_done")
        detached.set()

    detach_thread = threading.Thread(target=_detach, daemon=True)
    detach_thread.start()

    # Give detach a chance to (wrongly) complete; it must still be blocked.
    assert not detached.wait(0.3), "detach_session() returned mid-append (race!)"
    assert stream._session is not None  # not yet detached

    # Release the append; now detach can proceed.
    proceed.set()
    assert detached.wait(2.0), "detach_session() never completed after append"
    step.join(timeout=2.0)

    assert stream._session is None
    # The append finished strictly before detach returned.
    assert order == ["append_enter", "append_exit", "detach_done"]


def test_clear_after_detach_does_not_crash_acquire_loop():
    """Stress complement to the deterministic test above: a real acquire
    thread streams into a session under load while we repeatedly tear it down
    in the App's order (detach → clear). The acquire thread must never die.

    The hard guarantee lives in ``test_detach_session_waits_for_inflight_append``;
    this exercises the same invariant against the real threaded loop."""
    errors: list[BaseException] = []
    prev_hook = threading.excepthook
    threading.excepthook = lambda args: errors.append(args.exc_value)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            stream = Stream("emg", source=_FixedSource(), window_seconds=0.1, buffer_seconds=2)
            stream.start()
            time.sleep(0.05)  # let it connect + stream
            assert stream.info is not None

            for _ in range(30):
                session = Session(base_path=tmp)
                session.init_stream("emg", stream.info)
                stream.attach_session(session)
                time.sleep(0.003)
                # Teardown order mirrors App.stop_recording(): detach first
                # (waits for in-flight append), then clear the stores.
                stream.detach_session()
                session.stores.clear()
                session.ts_stores.clear()
            stream.stop()
            # Join the acquire thread so a late crash can't slip past the
            # assertion below (and so excepthook is restored only after it
            # has fully stopped).
            acq = getattr(stream, "_thread", None)
            if acq is not None:
                acq.join(timeout=2.0)
                assert not acq.is_alive(), "acquire thread did not stop"
    finally:
        threading.excepthook = prev_hook

    assert not errors, f"acquire thread raised: {errors!r}"
