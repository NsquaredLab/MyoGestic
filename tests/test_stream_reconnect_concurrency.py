"""Two UI paths can ask one `Stream` to connect. Only one attempt may run.

`force_ramps` shows both a device picker and — while nothing is attached — the
signal viewer's own Connect button. Pressing one and then the other used to
interleave: the second queued on the buffer lock, woke up inside it, and re-ran
against whatever source the first had since swapped in.
"""

import threading
import time

import pytest

from myogestic.stream import Stream, StreamInfo


class _BlockingSource:
    """A device that answers only when told to — an OTB probe left switched off."""

    def __init__(self, n_channels: int = 4) -> None:
        self.n_channels = n_channels
        self.entered = threading.Event()
        self.release = threading.Event()
        self.connects = 0
        self.inside = 0
        self.max_inside = 0

    def connect(self) -> StreamInfo:
        self.connects += 1
        self.inside += 1
        self.max_inside = max(self.max_inside, self.inside)
        self.entered.set()
        try:
            self.release.wait(timeout=5.0)
            return StreamInfo(n_channels=self.n_channels, fs=100.0)
        finally:
            self.inside -= 1

    def read(self):
        return None, None

    def disconnect(self) -> None:
        pass


def test_a_second_attempt_while_one_is_in_flight_is_refused_not_queued():
    source = _BlockingSource()
    stream = Stream("emg", source=source, window_ms=100)
    results: list[bool] = []

    first = threading.Thread(target=lambda: results.append(stream.reconnect()), daemon=True)
    first.start()
    assert source.entered.wait(timeout=2.0), "first attempt never reached connect()"

    # The second caller must come straight back, not block behind the first.
    started = time.monotonic()
    assert stream.reconnect() is False
    assert time.monotonic() - started < 0.5, "the second attempt queued instead of refusing"
    assert "already in flight" in stream.last_error

    source.release.set()
    first.join(timeout=5.0)
    assert results == [True]
    assert source.connects == 1, "the device was connected twice for one request"


def test_the_gui_can_still_read_the_stream_while_a_device_is_answering():
    """`accept_timeout` is 30 s; the render thread must not wait it out.

    Every frame reads `last_timestamp`, which takes the buffer lock. Holding
    that lock across the connect froze the whole app until the device replied.
    """
    source = _BlockingSource()
    stream = Stream("emg", source=source, window_ms=100)
    threading.Thread(target=stream.reconnect, daemon=True).start()
    assert source.entered.wait(timeout=2.0)

    started = time.monotonic()
    stream.last_timestamp()
    stream.get_display(64)
    elapsed = time.monotonic() - started

    assert elapsed < 0.5, f"render-side reads blocked for {elapsed:.2f}s during a connect"
    source.release.set()


def test_a_completed_reconnect_still_publishes_its_geometry():
    """The buffers must end up sized for the source that was actually connected."""
    source = _BlockingSource(n_channels=7)
    source.release.set()
    stream = Stream("emg", source=source, window_ms=100)

    assert stream.reconnect() is True
    assert stream.info is not None
    assert stream.info.n_channels == 7
    assert stream._connected is True


def test_a_refused_attempt_leaves_the_running_connection_alone():
    source = _BlockingSource()
    source.release.set()
    stream = Stream("emg", source=source, window_ms=100)
    assert stream.reconnect()
    info_before = stream.info

    stream._connect_lock.acquire()          # stand in for an attempt in flight
    try:
        assert stream.reconnect() is False
    finally:
        stream._connect_lock.release()

    assert stream.info is info_before, "a refused attempt disturbed the live stream"


@pytest.mark.parametrize("n_callers", [2, 5, 12])
def test_no_two_attempts_are_ever_inside_the_source_at_once(n_callers):
    """The property that matters.

    Not "only one ever succeeds" — attempts that arrive *after* one finishes are
    perfectly legitimate. What must never happen is two of them inside
    ``connect()`` together, reconnecting a source out from under the buffers.
    """
    source = _BlockingSource()
    stream = Stream("emg", source=source, window_ms=100)
    results: list[bool] = []
    barrier = threading.Barrier(n_callers)

    def attempt() -> None:
        barrier.wait(timeout=5.0)
        results.append(stream.reconnect())

    threads = [threading.Thread(target=attempt, daemon=True) for _ in range(n_callers)]
    for t in threads:
        t.start()
    assert source.entered.wait(timeout=3.0)
    source.release.set()
    for t in threads:
        t.join(timeout=5.0)

    assert source.max_inside == 1, f"{source.max_inside} attempts overlapped inside connect()"
    assert any(results), "every attempt was refused"


class _SwitchesGeometry(_BlockingSource):
    """A device that comes back with a different channel count than last time."""

    def connect(self) -> StreamInfo:
        info = super().connect()
        self.n_channels += 4
        return info


def test_the_acquire_thread_survives_a_raising_step():
    """A raise here used to end the thread for the life of the process.

    `App.run` starts it once, so nothing restarts it — and `status` stayed
    "connected" with `last_error` empty, so every panel showed a healthy stream
    that recorded and plotted nothing.
    """

    class _Exploding(_BlockingSource):
        def read(self):
            raise RuntimeError("device fell over")

    source = _Exploding()
    source.release.set()
    stream = Stream("emg", source=source, window_ms=100)
    assert stream.reconnect()

    stream._running = True
    threading.Thread(target=stream._acquire_loop, daemon=True).start()
    deadline = time.monotonic() + 3.0
    while stream.status == "connected" and time.monotonic() < deadline:
        time.sleep(0.01)
    stream._running = False

    assert stream.status == "disconnected", "the fault never surfaced"
    assert "device fell over" in stream.last_error


def test_reconnecting_is_refused_while_a_recording_is_attached():
    """Re-allocating the ring under a live session corrupts the take.

    The session's zarr arrays are sized once, from the geometry at
    `start_recording`. A reconnect that publishes a different channel count
    makes the next append raise — out of the acquire loop, killing it.
    """
    source = _SwitchesGeometry(n_channels=8)
    source.release.set()
    stream = Stream("emg", source=source, window_ms=100)
    assert stream.reconnect()

    stream._session = object()  # stands in for an attached session
    try:
        assert stream.reconnect() is False
        assert "while recording" in stream.last_error
        assert stream.info is not None
        assert stream.info.n_channels == 8, "the geometry moved under the session"
    finally:
        stream._session = None


def test_a_recording_that_starts_mid_connect_still_blocks_the_swap():
    """The window the guard exists for.

    An OTB source waits up to 30 s for a device to dial in. Pressing Record
    during that wait must not be overtaken by the connect completing.
    """
    source = _SwitchesGeometry(n_channels=8)
    stream = Stream("emg", source=source, window_ms=100)
    assert stream.reconnect()
    before = stream.info.n_channels

    result: list[bool] = []
    threading.Thread(target=lambda: result.append(stream.reconnect()), daemon=True).start()
    assert source.entered.wait(timeout=2.0)
    stream._session = object()  # the operator presses Record mid-connect
    source.release.set()

    deadline = time.monotonic() + 3.0
    while not result and time.monotonic() < deadline:
        time.sleep(0.01)
    stream._session = None

    assert result == [False]
    assert stream.info.n_channels == before, "buffers were republished under the session"
