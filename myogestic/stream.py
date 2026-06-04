from __future__ import annotations

import asyncio
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np
from dvg_ringbuffer import RingBuffer

if TYPE_CHECKING:
    from myogestic.session import Session

# Pyodide reports sys.platform == "emscripten" and forbids OS threads
# (Thread.start raises RuntimeError). When detected, the framework
# schedules its acquire / send / predict loops as asyncio tasks on the
# browser's event loop instead. Same loop bodies; only the pacing
# primitive (time.sleep vs await asyncio.sleep) differs.
_IS_BROWSER = sys.platform == "emscripten"


@dataclass
class StreamInfo:
    """Describes the shape and dtype of a :class:`Source`'s data.

    Returned by :meth:`Source.connect`. The framework uses it to size
    the ring buffer, lay out the signal viewer, and decide how to
    serialise the stream when recording.

    Attributes:
        n_channels: Channel count. Fixed for the life of the source.
        fs: Sample rate in Hz. Used to convert ``window_seconds`` /
            ``buffer_seconds`` into sample counts.
        dtype: NumPy dtype of each sample. Defaults to ``float32``;
            most signal-processing widgets assume this.
        channel_names: Optional per-channel labels for the signal viewer
            legend. ``None`` (default) renders as ``ch0``, ``ch1``, ...
    """

    n_channels: int
    fs: float
    dtype: np.dtype = np.dtype(np.float32)
    channel_names: list[str] | None = None


class Source(Protocol):
    """Protocol every data source must implement.

    Three methods, no inheritance: ``connect`` opens the device or file
    and returns a :class:`StreamInfo` describing the data, ``read``
    polls non-blockingly for the next chunk, ``disconnect`` releases
    the device. The framework's :class:`Stream` wraps any object
    matching this Protocol and runs it on a daemon acquisition thread.

    See [Add a custom source](../how-to/add-a-source.md) for worked
    examples and the full contract.
    """

    def connect(self) -> StreamInfo:
        """Open the device / file / socket. Return a :class:`StreamInfo`."""
        ...

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Return ``(data, ts)`` where ``data`` is sample-major
        ``(n_samples, n_channels)`` and ``ts`` is ``(n_samples,)``
        float64 LSL clock timestamps. Return ``(None, None)`` if no
        new data is available.
        """
        ...

    def disconnect(self) -> None:
        """Release the device. Idempotent - may be called multiple
        times during shutdown."""
        ...


def _unwrap_ring_into(rb: RingBuffer, out: np.ndarray, cap: int) -> int:
    """Copy ring buffer contents into pre-allocated `out`. Zero allocation.

    Uses dvg-ringbuffer internals (_arr, _idx_L, is_full) to avoid
    np.array(rb) which creates a new array every call.

    Returns number of valid samples written to `out`.
    """
    n = rb.shape[0]
    if n == 0:
        return 0
    if not rb.is_full:
        out[:n] = rb._arr[:n]
    else:
        L = rb._idx_L % cap
        if L == 0:
            out[:cap] = rb._arr[:cap]
        else:
            first = cap - L
            out[:first] = rb._arr[L:cap]
            out[first:cap] = rb._arr[:L]
        n = cap
    return n


class Stream:
    """A named ring-buffered live stream backed by a :class:`Source`.

    The framework's central data primitive: pair a name (``"emg"``) with
    a source (``LSLSource("TestEMG1")``) and a window duration, register
    the stream with ``app.streams(...)``, and the rest of the framework
    can pull windows (for ML), display snapshots (for the signal
    viewer), or recorded chunks (for the session) by stream name.

    Architecture:

    - One daemon **acquisition thread** is started per Stream when
      ``App.run()`` begins. It loops ``source.read()``, appends to the
      ring buffer, refreshes the display snapshot, and (if a recording
      session is active) appends to the session's Zarr store.
    - Two consumer surfaces are then available concurrently:
      :meth:`get_window` (channels-first, exact window-seconds long,
      consumed by ``@pipeline.extract``) and :meth:`get_display`
      (min/max envelope decimated for 60 fps rendering, consumed by
      ``signal_viewer``).
    - The ring buffer holds the last ``buffer_seconds`` of samples so
      transient consumers (slow extract, momentary GUI hitches) don't
      lose data.

    Example:
        >>> from myogestic import App, Stream
        >>> from myogestic.sources import LSLSource
        >>> app = App("hello")
        >>> app.streams(
        ...     Stream("emg", source=LSLSource("TestEMG1"),
        ...            window_seconds=1.0, buffer_seconds=10),
        ... )

    See [Streams concept](../concepts/streams.md) for the buffer +
    decimation model in depth, and [Add a custom source](../how-to/add-a-source.md)
    for the matching source-side contract.
    """

    def __init__(
        self,
        name: str,
        source: Source,
        window_seconds: float,
        buffer_seconds: float = 10,
    ):
        """Live ring-buffered stream with display decimation.

        Args:
            name: Stream label (also used as the recorded zarr stream key).
            source: Anything implementing the :class:`Source` protocol.
            window_seconds: Duration in **seconds** of the window returned
                by :meth:`get_window`.
            buffer_seconds: Ring-buffer depth in seconds. Defaults to 10.
        """
        self.name = name
        self._source = source
        self._window = float(window_seconds)
        self._buffer_seconds = buffer_seconds
        self._running = False
        self._session: Session | None = None
        # Guards `_session` against the acquire loop. `stop_recording()` tears
        # the session down (and a daemon thread clears its Zarr stores) while
        # this stream's acquire thread may still be inside `session.append()`.
        # Holding this lock around both the append and attach/detach makes the
        # teardown wait for any in-flight append, so the stores are never
        # cleared mid-append. Deliberately separate from `_lock` (which guards
        # the display buffers and is read by the GUI thread) so we never block
        # rendering on Zarr disk I/O — only the rare Stop path ever waits here.
        self._session_lock = threading.Lock()
        self.status = "disconnected"
        self.last_error = ""
        self.info: StreamInfo | None = None
        self._connected = False

        # These are initialized in _connect()
        self._cap: int = 0
        self._data: RingBuffer | None = None
        self._timestamps: RingBuffer | None = None
        self._lock = threading.Lock()
        self._display_d = np.empty(0)
        self._display_t = np.empty(0)
        self._display_n: int = 0
        self._snap_interval: int = 1
        self._samples_since_snap: int = 0
        self._m4_n_pixels: int = 2000
        self._m4_t = np.empty(0, dtype=np.float64)
        self._m4_d = np.empty(0)
        self._m4_n: int = 0
        # Per-stream M4 scratch (was module globals — not thread-safe across streams)
        self._m4_downsampler: object | None = None
        self._m4_work_col: np.ndarray | None = None
        self._m4_work_idx: np.ndarray | None = None
        self._m4_work_d: np.ndarray | None = None
        self._m4_work_t: np.ndarray | None = None
        self._win_d = np.empty(0)
        self._win_t = np.empty(0)

    def _connect(self) -> bool:
        """Connect to source and allocate buffers. Returns True on success."""
        try:
            self.info = self._source.connect()
        except Exception as e:
            self.last_error = str(e)
            return False
        self._allocate_buffers()
        return True

    def _allocate_buffers(self) -> None:
        """Allocate/resize buffers for the current self.info. Called after any
        (re)connection that produced a fresh StreamInfo."""
        assert self.info is not None
        self._cap = int(self.info.fs * self._buffer_seconds)
        self._data = RingBuffer(
            capacity=self._cap,
            dtype=(self.info.dtype, self.info.n_channels),  # type: ignore[arg-type]
        )
        self._timestamps = RingBuffer(
            capacity=self._cap,
            dtype=np.float64,  # type: ignore[arg-type]
        )
        self._display_d = np.empty((self._cap, self.info.n_channels), dtype=self.info.dtype)
        self._display_t = np.empty(self._cap, dtype=np.float64)
        self._display_n = 0
        self._snap_interval = max(1, int(self.info.fs * 0.016))
        self._m4_t = np.empty(0, dtype=np.float64)
        self._m4_d = np.empty((0, self.info.n_channels), dtype=self.info.dtype)
        self._m4_n = 0
        # Reset M4 scratch — dtype/n_channels may have changed on reconnect.
        self._m4_downsampler = None
        self._m4_work_col = None
        self._m4_work_idx = None
        self._m4_work_d = None
        self._m4_work_t = None
        self._win_d = np.empty((self._cap, self.info.n_channels), dtype=self.info.dtype)
        self._win_t = np.empty(self._cap, dtype=np.float64)
        self._connected = True

    def reconnect(self, target: str | None = None) -> bool:
        """Reconnect source. Optionally switch to a different target.

        If the source implements reconnect(), uses that (preserves source-specific
        logic like LSL resolve or serial port open). Otherwise falls back to
        disconnect + connect. Either way the source is connected ONCE — buffers
        are then (re)allocated from the returned StreamInfo.

        Holds `self._lock` for the whole swap to prevent the acquire loop
        from reading through a half-torn state.
        """
        with self._lock:
            self._connected = False
            self._display_n = 0
            self._m4_n = 0
            self.status = "disconnected"

            try:
                if hasattr(self._source, "reconnect"):
                    # `reconnect` is an optional Source extension (not in the
                    # Protocol); the hasattr guard makes the call safe.
                    self.info = self._source.reconnect(target)  # type: ignore[attr-defined]
                else:
                    self._source.disconnect()
                    self.info = self._source.connect()
            except Exception as e:
                self.last_error = str(e)
                return False

            # Re-init buffers for potentially different channel count/fs
            # (no double-connect — source was already (re)connected above).
            self._allocate_buffers()
            return True

    def start(self) -> None:
        self._running = True
        if _IS_BROWSER:
            # Pyodide: no OS threads, and asyncio tasks scheduled here
            # don't dispatch (immapp.run blocks Python inside the
            # Emscripten main loop). Register one step with the
            # per-frame scheduler instead - the App's GUI callback
            # ticks it every frame.
            from myogestic._browser import register

            register(lambda: self._acquire_step() if self._running else 1.0)
        else:
            self._thread = threading.Thread(target=self._acquire_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._running = False
        try:
            self._source.disconnect()
        except Exception:
            pass

    def attach_session(self, session: Session) -> None:
        """Begin recording this stream into ``session`` (called by
        :meth:`App.start_recording`). Set under ``_session_lock`` so the
        acquire loop sees a fully-attached session atomically."""
        with self._session_lock:
            self._session = session

    def detach_session(self) -> None:
        """Stop recording this stream (called by :meth:`App.stop_recording`).

        Holding ``_session_lock`` makes this *wait for* any append currently
        in flight on the acquire thread and guarantees no further append can
        start. Once this returns, the caller may safely finalise/clear the
        session's Zarr stores without racing the acquire loop."""
        with self._session_lock:
            self._session = None

    def _acquire_step(self) -> float:
        """Run one iteration of the acquire loop body.

        Returns the number of seconds the caller should sleep before
        the next call. Pulled out of the loop so both the threaded and
        the async (browser) variants can share the work and only
        differ in how they pace themselves.
        """
        if not self._connected:
            return 0.0 if self._connect() else 1.0

        try:
            data, ts = self._source.read()
        except Exception as e:
            self.status = "disconnected"
            self.last_error = str(e)
            return 0.5

        if data is None or ts is None or len(data) == 0:
            # Source had nothing ready. Sleep briefly so we don't hot-loop.
            return 0.001

        bad = self._validate_chunk(data, ts)
        if bad is not None:
            # Shape mismatch - keep the loop alive but surface the
            # reason. Source code (or the device) is producing
            # something other than (n_samples, n_channels) with
            # n_channels matching StreamInfo.
            self.status = "disconnected"
            self.last_error = bad
            return 0.1

        if self._data is None or self._timestamps is None:
            # Shouldn't happen once connected (_connect initialises both), but
            # narrows the Optional for the type checker and is harmless defence.
            return 1.0
        with self._lock:
            self._data.extend(data)
            self._timestamps.extend(ts)
        self.status = "connected"
        self.last_error = ""

        # Update raw snapshot every chunk (cheap memcpy)
        self._update_raw_snapshot()

        # M4 decimation at ~60Hz (heavier)
        self._samples_since_snap += len(data)
        if self._samples_since_snap >= self._snap_interval:
            self._samples_since_snap = 0
            self._update_m4_snapshot()

        # Append to zarr session if recording. Hold `_session_lock` across the
        # check-and-append so `detach_session()` (called from stop_recording)
        # cannot null the session and clear its stores in the middle of an
        # append — that race surfaced as `KeyError: '<stream>'` killing this
        # acquire thread. The lock is uncontended except during teardown.
        with self._session_lock:
            if self._session is not None:
                self._session.append(self.name, data, ts)

        # More data may already be queued at the source - don't sleep.
        return 0.0

    def _acquire_loop(self) -> None:
        """Daemon-thread variant: tight loop with time.sleep pacing."""
        while self._running:
            delay = self._acquire_step()
            if delay > 0:
                time.sleep(delay)

    async def _acquire_loop_async(self) -> None:
        """Browser variant: same step body, paced with asyncio.sleep so
        the event loop can hand control back to the frame renderer."""
        while self._running:
            delay = self._acquire_step()
            # asyncio.sleep(0) still yields to the event loop, which is
            # what we want when the source has more data ready.
            await asyncio.sleep(delay)

    def _validate_chunk(self, data: np.ndarray, ts: np.ndarray) -> str | None:
        """Check that a chunk from `source.read()` matches the StreamInfo.

        Returns ``None`` when the chunk is well-formed, or an error message
        suitable for ``self.last_error`` when it is not. Keeps the loop in
        one place — callers skip the chunk and sleep briefly on error.
        Messages name the expected shape and the most likely fix.
        """
        if data.ndim == 1:
            return (
                f"source returned 1-D data (shape={data.shape}); expected 2-D "
                "(n_samples, n_channels). For a single-channel stream, return "
                "data.reshape(-1, 1) from source.read()."
            )
        if data.ndim != 2:
            return (
                f"source returned data.ndim={data.ndim} (shape={data.shape}); "
                "expected 2-D (n_samples, n_channels)."
            )
        if self.info is not None and data.shape[1] != self.info.n_channels:
            hint = ""
            if data.shape[0] == self.info.n_channels:
                hint = " — shape looks transposed; return data.T from source.read()."
            return (
                f"source returned shape={data.shape}; expected "
                f"(_, {self.info.n_channels}) per StreamInfo.{hint}"
            )
        if ts.ndim != 1:
            return (
                f"source returned timestamps.ndim={ts.ndim} (shape={ts.shape}); "
                "expected 1-D (n_samples,). Use ts.ravel() if it came back 2-D."
            )
        if len(ts) != data.shape[0]:
            return (
                f"source returned len(timestamps)={len(ts)} "
                f"!= data.shape[0]={data.shape[0]} — they must align 1:1."
            )
        return None

    def _update_raw_snapshot(self) -> None:
        """Unwrap ring buffer into display arrays. Zero alloc, every chunk."""
        if self._data is None or self._timestamps is None:
            return
        with self._lock:
            n = _unwrap_ring_into(self._data, self._display_d, self._cap)
            _unwrap_ring_into(self._timestamps, self._display_t, self._cap)
        self._display_n = n

    def _update_m4_snapshot(self) -> None:
        """Pre-compute M4 decimation. Runs at ~60Hz on acquire thread."""
        n = self._display_n
        if n < 2:
            return
        n_out = self._m4_n_pixels * 4
        if n <= n_out:
            self._m4_t = self._display_t[:n]
            self._m4_d = self._display_d[:n]
            self._m4_n = n
        else:
            t_dec, d_dec = self._m4_decimate(self._display_t[:n], self._display_d[:n], n_out)
            self._m4_t = t_dec
            self._m4_d = d_dec
            self._m4_n = len(t_dec)

    def _m4_decimate(
        self, t: np.ndarray, d: np.ndarray, n_out: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Per-stream M4 decimation via tsdownsample with pre-allocated scratch.

        Previously module-global — moved here because multiple streams running
        the acquire loop concurrently would stomp on shared scratch buffers.
        """
        if self._m4_downsampler is None:
            from tsdownsample import M4Downsampler

            self._m4_downsampler = M4Downsampler()

        n, n_ch = d.shape

        # Bind each scratch buffer to a local right after its lazy-alloc guard:
        # the type checker can't narrow an Optional *instance attribute* across
        # the loop + downsampler calls below, but it narrows a local; locals also
        # save repeated attribute lookups in this per-frame hot path.
        work_col = self._m4_work_col
        if work_col is None or work_col.shape[0] < n:
            work_col = self._m4_work_col = np.empty(n, dtype=d.dtype)

        max_idx = n_out * n_ch
        work_idx = self._m4_work_idx
        if work_idx is None or work_idx.shape[0] < max_idx:
            work_idx = self._m4_work_idx = np.empty(max_idx, dtype=np.intp)

        pos = 0
        for ch in range(n_ch):
            np.copyto(work_col[:n], d[:, ch])
            idx = self._m4_downsampler.downsample(work_col[:n], n_out=n_out)  # type: ignore[attr-defined]
            idx_len = len(idx)
            work_idx[pos : pos + idx_len] = idx
            pos += idx_len

        all_idx = np.unique(work_idx[:pos])
        n_sel = len(all_idx)

        work_d = self._m4_work_d
        if (
            work_d is None
            or work_d.shape[0] < n_sel
            or work_d.shape[1] != n_ch
        ):
            work_d = self._m4_work_d = np.empty((n_out * n_ch, n_ch), dtype=d.dtype)
        work_t = self._m4_work_t
        if work_t is None or work_t.shape[0] < n_sel:
            work_t = self._m4_work_t = np.empty(n_out * n_ch, dtype=np.float64)

        work_t[:n_sel] = t[all_idx]
        work_d[:n_sel] = d[all_idx]

        return work_t[:n_sel], work_d[:n_sel]

    def get_window(self) -> tuple[np.ndarray, np.ndarray]:
        """Return the most recent ``window_seconds`` as ``(data, ts)``.

        ``data`` is **channels-first** ``(n_channels, n_samples)`` — the
        same convention used everywhere user code touches signal data.
        Both arrays are views into a reusable per-stream buffer; copy
        explicitly if you need to retain them past the next call.
        """
        if self._data is None or self._timestamps is None or self.info is None:
            return (
                np.empty((0, 0), dtype=np.float32),
                np.empty(0, dtype=np.float64),
            )
        with self._lock:
            nd = _unwrap_ring_into(self._data, self._win_d, self._cap)
            _unwrap_ring_into(self._timestamps, self._win_t, self._cap)
        if nd == 0:
            return self._win_d[:0].T, self._win_t[:0]
        n = int(self._window * self.info.fs)
        if nd < n:
            return self._win_d[:nd].T, self._win_t[:nd]
        return self._win_d[nd - n : nd].T, self._win_t[nd - n : nd]

    def get_display(self, n_pixels: int = 800) -> tuple[np.ndarray, np.ndarray] | None:
        """Read pre-computed M4 result. Zero work on render thread.

        The acquire thread computes M4 in _update_display_snapshot.
        This just reads the result via atomic ref (GIL-safe).
        """
        # Update target resolution for next snapshot
        self._m4_n_pixels = n_pixels
        n = self._m4_n
        if n < 2:
            return None
        return self._m4_t[:n], self._m4_d[:n]

    def get_raw_snapshot(self) -> tuple[np.ndarray, np.ndarray] | None:
        """Lock-free read of the display snapshot."""
        n = self._display_n
        if n < 2:
            return None
        return self._display_t[:n], self._display_d[:n]

    def last_timestamp(self) -> float | None:
        """Most recent sample timestamp, or None if no samples yet.

        Holds `_lock` while reading `_display_t[_display_n-1]` so a concurrent
        `reconnect()` (which zeroes `_display_n` and reallocates `_display_t`)
        cannot strand the read on a torn buffer.
        """
        with self._lock:
            n = self._display_n
            if n < 1 or self._display_t.shape[0] < n:
                return None
            ts = float(self._display_t[n - 1])
        return ts if ts > 0.0 else None
