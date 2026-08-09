"""Stream abstraction — ring-buffered acquisition from a Source plus windowing."""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np
from dvg_ringbuffer import RingBuffer

if TYPE_CHECKING:
    from tsdownsample import M4Downsampler

    from myogestic.session import Session

# Pyodide reports sys.platform == "emscripten" and forbids OS threads
# (Thread.start raises RuntimeError); the acquire / send / predict loops run
# on the browser's event loop instead, paced with await asyncio.sleep.
_IS_BROWSER = sys.platform == "emscripten"


#: Dtypes a [`Stream`][] / [`Source`][] may use: every LSL wire format
#: (``int8`` / ``int16`` / ``int32`` / ``int64`` / ``float32`` /
#: ``float64``) plus ``float16`` as a storage-only cast. Unsigned ints are
#: excluded.
SUPPORTED_DTYPES: tuple[np.dtype, ...] = tuple(
    np.dtype(t)
    for t in (
        np.float16,
        np.float32,
        np.float64,
        np.int8,
        np.int16,
        np.int32,
        np.int64,
    )
)


log = logging.getLogger("myogestic")


@dataclass(frozen=True)
class ChannelGrid:
    """A named electrode grid as a 2-D map of output-column indices (None = empty cell)."""

    label: str
    cells: list[list[int | None]]

    @property
    def columns(self) -> list[int]:
        """Non-``None`` cell values, row-major order."""
        return [c for row in self.cells for c in row if c is not None]


@dataclass
class StreamInfo:
    """Describes the shape and dtype of a [`Source`][]'s data.

    Returned by [`Source.connect`][]; sizes the ring buffer and lays out
    the signal viewer.

    Attributes
    ----------
    n_channels
        Channel count. Fixed for the life of the source.
    fs
        Sample rate in Hz. Used to convert ``window_ms`` /
        ``buffer_ms`` into sample counts.
    dtype
        NumPy dtype of each sample, one of `SUPPORTED_DTYPES`.
        Defaults to ``float32``. Accepts anything [`numpy.dtype`][]
        understands (``"int16"``, ``np.int16``, ``np.dtype("int16")``)
        and normalises it. A compact dtype (e.g. ``int16``) keeps the
        ring buffer and Zarr recording small; the window handed to
        ``@pipeline.extract`` is **always upcast to float32** regardless.
    channel_names
        Optional per-channel labels for the signal viewer
        legend. ``None`` (default) renders as ``ch0``, ``ch1``, ...
    channel_grids
        Optional list of `ChannelGrid` electrode topologies for
        the signal viewer's spatial channel selector. ``None``
        (default) disables the grid selector. Not validated here — a
        malformed layout must never block acquisition; the viewer
        validates it before use.

    Examples
    --------
    >>> from myogestic import StreamInfo
    >>> info = StreamInfo(8, 2048.0, dtype="int16")
    >>> (info.n_channels, info.fs, info.dtype.name)
    (8, 2048.0, 'int16')
    """

    n_channels: int
    fs: float
    dtype: np.dtype = np.dtype(np.float32)
    channel_names: list[str] | None = None
    channel_grids: list[ChannelGrid] | None = None

    def __post_init__(self) -> None:
        # Normalise str / type / np.dtype to a single np.dtype form, then validate.
        self.dtype = np.dtype(self.dtype)
        if self.dtype not in SUPPORTED_DTYPES:
            supported = ", ".join(d.name for d in SUPPORTED_DTYPES)
            raise ValueError(
                f"Unsupported dtype {self.dtype.name!r}. Supported dtypes: {supported}."
            )


class Source(Protocol):
    """Protocol every data source must implement.

    Three methods, no inheritance. [`Stream`][] wraps any object matching
    this Protocol and runs it on a daemon acquisition thread, so ``read``
    must not block.

    See [Add a custom source](../how-to/add-a-source.md) for worked
    examples and the full contract.
    """

    def connect(self) -> StreamInfo:
        """Open the device / file / socket. Return a [`StreamInfo`][]."""
        ...

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Poll for the next chunk of samples.

        Return ``(data, ts)`` where ``data`` is sample-major
        ``(n_samples, n_channels)`` and ``ts`` is ``(n_samples,)``
        float64 LSL clock timestamps. Return ``(None, None)`` if no
        new data is available.
        """
        ...

    def disconnect(self) -> None:
        """Release the device.

        Idempotent - may be called multiple times during shutdown.
        """
        ...


def _unwrap_ring_into(rb: RingBuffer, out: np.ndarray, cap: int) -> int:
    """Copy ring buffer contents into pre-allocated `out`. Zero allocation.

    Uses dvg-ringbuffer internals (_arr, _idx_L, is_full) to avoid
    np.array(rb), which allocates every call. Returns the number of valid
    samples written to `out`.
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


def _copy_ring_tail_into(rb: RingBuffer, out: np.ndarray, count: int, cap: int) -> int:
    """Copy at most the newest ``count`` ring rows into ``out`` chronologically.

    Unlike :func:`_unwrap_ring_into`, the work is bounded by the requested tail rather
    than the ring's current fill. This matters for long acquisition buffers: prediction
    and a five-second viewer must not repeatedly copy sixty seconds of history.
    """
    n = rb.shape[0]
    take = min(n, max(0, int(count)))
    if take == 0:
        return 0

    logical_start = n - take
    if not rb.is_full:
        out[:take] = rb._arr[logical_start:n]
        return take

    physical_start = (rb._idx_L + logical_start) % cap
    first = min(take, cap - physical_start)
    out[:first] = rb._arr[physical_start : physical_start + first]
    if first < take:
        out[first:take] = rb._arr[: take - first]
    return take


class Stream:
    """A named ring-buffered live stream backed by a [`Source`][].

    Pair a name (``"emg"``) with a source (``LSLSource("TestEMG1")``) and a
    window duration, register it with ``app.streams(...)``, and the rest of
    the framework addresses it by stream name.

    - **Nothing attaches on its own.** Call `reconnect` — or press the
      button in a `StreamPanel` — and the source is opened once. The
      acquire loop never opens one for you, on the first tick or after
      a source goes away, so a stream left running by an earlier
      process is never picked up behind you.
    - One daemon **acquisition thread** is started per Stream when
      ``App.run()`` begins. Once attached it loops ``source.read()``,
      appends to the ring buffer and, if a recording session is active,
      appends to the session's Zarr store. Display and prediction consumers
      copy only the bounded tail they request. Until attached it waits.
    - [`get_window`][] and [`get_display`][] are then readable
      concurrently from other threads.
    - The ring buffer holds the last ``buffer_ms`` of samples so
      transient consumers (slow extract, momentary GUI hitches) don't
      lose data.

    Examples
    --------
    >>> from myogestic import App, Stream
    >>> from myogestic.sources import LSLSource
    >>> app = App("hello")
    >>> app.streams(
    ...     Stream("emg", source=LSLSource("TestEMG1"),
    ...            window_ms=1000, buffer_ms=10000),
    ... )

    See [Streams concept](../concepts/streams.md) for the buffer +
    decimation model in depth, and [Add a custom source](../how-to/add-a-source.md)
    for the matching source-side contract.
    """

    def __init__(
        self,
        name: str,
        source: Source,
        window_ms: float,
        buffer_ms: float = 10000,
    ):
        """Live ring-buffered stream with display decimation.

        Parameters
        ----------
        name
            Stream label (also used as the recorded zarr stream key).
        source
            Anything implementing the [`Source`][] protocol.
        window_ms
            Duration in **milliseconds** of the window returned
            by [`get_window`][].
        buffer_ms
            Ring-buffer depth in milliseconds. Defaults to 10000 (10 s).
        """
        self.name = name
        self._source = source
        self._window = window_ms / 1000.0
        self._buffer_seconds = buffer_ms / 1000.0
        self._running = False
        self._session: Session | None = None
        # Guards `_session` against the acquire loop: held around both the
        # append and attach/detach, so teardown waits for any in-flight append
        # and the Zarr stores are never cleared mid-append. Separate from
        # `_lock` (display buffers, read by the GUI thread) so rendering never
        # blocks on Zarr disk I/O.
        self._session_lock = threading.Lock()
        # Held for the duration of a connection attempt. Distinct from `_lock`:
        # this one serialises *attempts*, while `_lock` guards the buffers for
        # the microseconds it takes to swap them.
        self._connect_lock = threading.Lock()
        self.status = "disconnected"
        self.last_error = ""
        self.info: StreamInfo | None = None
        self._connected = False

        # These are initialized by `_allocate_buffers`, on connect.
        self._cap: int = 0
        self._data: RingBuffer | None = None
        self._timestamps: RingBuffer | None = None
        self._lock = threading.Lock()
        self._display_d = np.empty(0)
        self._display_t = np.empty(0)
        self._display_n: int = 0
        self._m4_n_pixels: int = 2000
        self._m4_t = np.empty(0, dtype=np.float64)
        self._m4_d = np.empty(0)
        self._m4_n: int = 0
        # Per-stream M4 scratch (was module globals — not thread-safe across streams)
        self._m4_downsampler: M4Downsampler | None = None
        self._m4_work_col: np.ndarray | None = None
        self._m4_work_idx: np.ndarray | None = None
        self._m4_work_d: np.ndarray | None = None
        self._m4_work_t: np.ndarray | None = None
        self._win_d = np.empty(0)
        self._win_t = np.empty(0)
        # Buffer identity for stateful render-side consumers. `epoch` bumps on
        # every (re)allocation and `_total_seq` counts samples appended this
        # epoch (written only under `_lock`). The legacy full-display snapshot
        # is refreshed only on demand; the normal viewer reads a bounded tail
        # directly from the ring instead.
        self.epoch = 0
        self._total_seq = 0
        self._display_seq_end = 0

    def _allocate_buffers(self) -> None:
        """Allocate/resize buffers for the current self.info.

        Called after any (re)connection that produced a fresh StreamInfo.
        """
        assert self.info is not None
        self._cap = int(self.info.fs * self._buffer_seconds)
        self._data = RingBuffer(
            capacity=self._cap,
            dtype=(self.info.dtype, self.info.n_channels),  # type: ignore
        )
        self._timestamps = RingBuffer(
            capacity=self._cap,
            dtype=np.float64,  # type: ignore
        )
        self._display_d = np.empty((self._cap, self.info.n_channels), dtype=self.info.dtype)
        self._display_t = np.empty(self._cap, dtype=np.float64)
        self._display_n = 0
        # New epoch invalidates any cached filter state keyed to the old buffer.
        self.epoch += 1
        self._total_seq = 0
        self._display_seq_end = 0
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

        Uses the source's own ``reconnect()`` if it has one (preserving
        source-specific logic like LSL resolve or serial port open), else
        disconnect + connect. Either way the source is connected ONCE, then
        buffers are (re)allocated from the returned StreamInfo.

        **One attempt at a time.** A second caller while one is in flight is
        refused rather than queued: an app can offer more than one way to
        connect a stream (a device picker, a viewer's own button), and two
        attempts racing used to interleave — the queued one would wake up inside
        the lock and re-run against whatever source the first had since swapped
        in, reconnecting a live source out from under the buffers.

        **The source is connected outside `self._lock`.** That lock is taken by
        the acquire loop and by every render-side read, while an OTB
        ``accept()`` blocks for ``accept_timeout`` — 30 s by default. Holding it
        across the attempt froze the whole GUI for as long as a device took to
        answer, or to not answer. It is now taken twice and briefly: once to
        mark the stream detached, once to publish the new buffers.
        """
        if not self._connect_lock.acquire(blocking=False):
            self.last_error = "a connection attempt is already in flight"
            return False
        if self._session is not None:
            # `_allocate_buffers` would resize the ring under a session whose
            # zarr arrays are already sized for the old geometry, and the next
            # append would raise out of the acquire loop.
            self.last_error = "cannot reconnect while recording"
            self._connect_lock.release()
            return False
        try:
            with self._lock:
                self._connected = False
                self._display_n = 0
                self._m4_n = 0
                self.status = "disconnected"

            # Read once: if another thread swaps `_source` mid-attempt we still
            # connect the one this call was asked for, and publish its geometry.
            source = self._source
            try:
                if hasattr(source, "reconnect"):
                    # `reconnect` is an optional Source extension (not in the
                    # Protocol); the hasattr guard makes the call safe.
                    info = source.reconnect(target)  # type: ignore
                else:
                    source.disconnect()
                    info = source.connect()
            except Exception as e:
                self.last_error = str(e)
                return False

            # Checked again, because the whole point of connecting off-thread is
            # that it takes time: an operator can press Record during the 30 s an
            # OTB source spends waiting for a device to dial in. Publishing new
            # buffers now would resize the ring under a session already sized for
            # the old geometry.
            if self._session is not None:
                self.last_error = "cannot reconnect while recording"
                try:
                    source.disconnect()
                except Exception:
                    pass  # nothing to keep — this attempt is being abandoned
                return False

            with self._lock:
                self.info = info
                # Re-init buffers for a potentially different channel count/fs.
                self._allocate_buffers()
            return True
        finally:
            self._connect_lock.release()

    def disconnect(self) -> None:
        """Detach the source, leaving the acquire loop running and idle.

        The counterpart to [`reconnect`][]. **Not** `stop`: that ends the
        acquire thread, which `App.run` starts once and owns — a stream stopped
        that way could not be brought back from the UI.

        ``info`` is cleared along with the connection. A stream that was
        deliberately detached has no geometry, and leaving the old one behind
        makes a viewer report the connection as *lost* rather than as closed on
        purpose.
        """
        with self._lock:
            self._connected = False
            self._display_n = 0
            self._m4_n = 0
            self.status = "disconnected"
            self.info = None
            self.last_error = ""
        try:
            self._source.disconnect()
        except Exception:
            pass  # already gone, or never opened anything

    def start(self) -> None:
        """Start the acquisition loop (a daemon thread, or a per-frame task in the browser)."""
        self._running = True
        if _IS_BROWSER:
            # Pyodide: no OS threads, and asyncio tasks scheduled here don't
            # dispatch (immapp.run blocks Python inside the Emscripten main
            # loop). Register one step with the per-frame scheduler instead.
            from myogestic._browser import register

            register(lambda: self._acquire_step() if self._running else 1.0)
        else:
            self._thread = threading.Thread(target=self._acquire_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the acquisition loop and disconnect the source (errors suppressed)."""
        self._running = False
        try:
            self._source.disconnect()
        except Exception:
            pass

    def attach_session(self, session: Session) -> None:
        """Begin recording this stream into ``session``.

        Called by [`App.start_recording`][]. Set under ``_session_lock``
        so the acquire loop sees a fully-attached session atomically.
        """
        with self._session_lock:
            self._session = session

    def detach_session(self) -> None:
        """Stop recording this stream (called by [`App.stop_recording`][myogestic.App.stop_recording]).

        Waits for any append in flight on the acquire thread and blocks
        further ones, so once this returns the caller may finalise/clear the
        session's Zarr stores without racing the acquire loop.
        """
        with self._session_lock:
            self._session = None

    def _acquire_step(self) -> float:
        """Run one iteration of the acquire loop body.

        Returns the number of seconds the caller should sleep before the next
        call; the threaded and browser loops share this body and differ only
        in how they pace themselves.
        """
        if not self._connected:
            # Nothing attaches on its own — not the first time, and not after a drop.
            # This used to call `_connect()` every second forever, which is one behaviour
            # doing two jobs: it is how a stream first attached, and it is also how a
            # stream from somebody else's run got picked up seconds after you opened an
            # app, with a plausible-looking trace and no way to tell it apart from yours.
            # A source is a thing you point at deliberately, so the loop waits and
            # `reconnect` — the button — is what attaches.
            return 1.0

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
            # Shape mismatch — keep the loop alive but surface the reason.
            self.status = "disconnected"
            self.last_error = bad
            return 0.1

        if self._data is None or self._timestamps is None:
            # Unreachable once connected; narrows the Optional for the checker.
            return 1.0
        with self._lock:
            self._data.extend(data)
            self._timestamps.extend(ts)
            self._total_seq += len(data)
        self.status = "connected"
        self.last_error = ""

        # `_session_lock` spans the check-and-append so `detach_session()`
        # cannot null the session and clear its stores mid-append.
        with self._session_lock:
            if self._session is not None:
                self._session.append(self.name, data, ts)

        # More data may already be queued at the source - don't sleep.
        return 0.0

    def _acquire_loop(self) -> None:
        """Daemon-thread variant: tight loop with time.sleep pacing.

        Every step is guarded. A raise used to end this thread for the life of
        the process — `App.run` starts it once and nothing restarts it — while
        `status` stayed ``"connected"`` and ``last_error`` stayed empty. The
        result was a stream that looked healthy in every panel and recorded and
        plotted nothing, with no route back from the UI. Surviving the error and
        reporting it is the difference between a visible fault and a silent one.
        """
        while self._running:
            try:
                delay = self._acquire_step()
            except Exception as e:
                log.exception("acquire step failed for stream %r: %s", self.name, e)
                with self._lock:
                    self._connected = False
                    self.status = "disconnected"
                    self.last_error = str(e)
                delay = 0.5
            if delay > 0:
                time.sleep(delay)

    def _validate_chunk(self, data: np.ndarray, ts: np.ndarray) -> str | None:
        """Check that a chunk from `source.read()` matches the StreamInfo.

        Returns ``None`` when the chunk is well-formed, or an error message
        suitable for ``self.last_error`` when it is not.
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
        """Unwrap the full ring into legacy display arrays on demand.

        The acquisition loop deliberately never calls this method. Copying a
        growing/full history for every small source chunk makes acquisition
        progressively slower and eventually starves the source.
        """
        if self._data is None or self._timestamps is None:
            return
        with self._lock:
            n = _unwrap_ring_into(self._data, self._display_d, self._cap)
            _unwrap_ring_into(self._timestamps, self._display_t, self._cap)
            # Count and its matching newest-sequence must be set together under
            # the lock, or `get_raw_snapshot_stable` can read a count that
            # disagrees with `_total_seq`.
            self._display_n = n
            self._display_seq_end = self._total_seq

    def _update_m4_snapshot(self) -> None:
        """Compute the M4-decimated display snapshot.

        Called lazily from [`get_display`][] on the render thread, so it copies
        the display buffer under the lock before decimating.
        """
        # `get_display` is the legacy full-buffer API. Refresh its contiguous
        # snapshot here rather than burdening every acquisition chunk.
        self._update_raw_snapshot()
        with self._lock:
            n = self._display_n
            if n < 2:
                self._m4_n = 0
                return
            t = self._display_t[:n].copy()
            d = self._display_d[:n].copy()
        n_out = self._m4_n_pixels * 4
        if n <= n_out:
            self._m4_t = t
            self._m4_d = d
            self._m4_n = n
        else:
            t_dec, d_dec = self._m4_decimate(t, d, n_out)
            self._m4_t = t_dec
            self._m4_d = d_dec
            self._m4_n = len(t_dec)

    def _m4_decimate(
        self, t: np.ndarray, d: np.ndarray, n_out: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Decimate via tsdownsample's M4 using pre-allocated scratch.

        Scratch is per-stream: concurrent streams must not share it.
        """
        downsampler = self._m4_downsampler
        if downsampler is None:
            from tsdownsample import M4Downsampler

            downsampler = self._m4_downsampler = M4Downsampler()

        n, n_ch = d.shape

        # Bind each scratch buffer to a local right after its lazy-alloc guard:
        # the type checker narrows a local but not an Optional attribute, and
        # locals save attribute lookups in this per-frame hot path.
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
            idx = downsampler.downsample(work_col[:n], n_out=n_out)
            idx_len = len(idx)
            work_idx[pos : pos + idx_len] = idx
            pos += idx_len

        all_idx = np.unique(work_idx[:pos])
        n_sel = len(all_idx)

        # Size the output scratch to `n`, not `n_out * n_ch`: `all_idx` is the
        # unique union of every channel's picks, so `n_sel <= n`. Sizing by
        # `n_out * n_ch` costs ~2 GiB at 256 ch / n_out=8000 vs ~21 MB.
        work_d = self._m4_work_d
        if work_d is None or work_d.shape[0] < n_sel or work_d.shape[1] != n_ch:
            work_d = self._m4_work_d = np.empty((n, n_ch), dtype=d.dtype)
        work_t = self._m4_work_t
        if work_t is None or work_t.shape[0] < n_sel:
            work_t = self._m4_work_t = np.empty(n, dtype=np.float64)

        work_t[:n_sel] = t[all_idx]
        work_d[:n_sel] = d[all_idx]

        return work_t[:n_sel], work_d[:n_sel]

    def get_window(self) -> tuple[np.ndarray, np.ndarray]:
        """Return the most recent ``window_ms`` as ``(data, ts)``.

        ``data`` is **channels-first** ``(n_channels, n_samples)`` and
        **always float32**, whatever dtype the stream buffers in. ``ts`` is a
        view into a reusable per-stream buffer; for a float32 stream ``data``
        is a view too, otherwise a fresh float32 copy. Copy explicitly to
        retain either past the next call.
        """
        if self._data is None or self._timestamps is None or self.info is None:
            return (
                np.empty((0, 0), dtype=np.float32),
                np.empty(0, dtype=np.float64),
            )
        n = max(0, int(self._window * self.info.fs))
        with self._lock:
            nd = _copy_ring_tail_into(self._data, self._win_d, n, self._cap)
            _copy_ring_tail_into(self._timestamps, self._win_t, n, self._cap)
        if nd == 0:
            return self._win_d[:0].T.astype(np.float32, copy=False), self._win_t[:0]
        return self._win_d[:nd].T.astype(np.float32, copy=False), self._win_t[:nd]

    def get_display(self, n_pixels: int = 800) -> tuple[np.ndarray, np.ndarray] | None:
        """M4-decimated display snapshot, computed on demand on the render thread.

        Recomputed per call from the current display buffer; the acquire thread
        must not precompute it (it starves the socket read at high channel counts).
        """
        self._m4_n_pixels = n_pixels
        self._update_m4_snapshot()
        n = self._m4_n
        if n < 2:
            return None
        return self._m4_t[:n], self._m4_d[:n]

    def get_raw_snapshot(self) -> tuple[np.ndarray, np.ndarray] | None:
        """Return an on-demand full, contiguous ring snapshot.

        Prefer :meth:`get_raw_snapshot_stable` with ``duration_s`` for live
        widgets; this compatibility API necessarily copies the whole buffer.
        """
        self._update_raw_snapshot()
        n = self._display_n
        if n < 2:
            return None
        return self._display_t[:n], self._display_d[:n]

    def get_raw_snapshot_stable(
        self, duration_s: float | None = None
    ) -> tuple[int, int, float, np.ndarray, np.ndarray] | None:
        """Locked *copy* of the (tail of the) display snapshot, tagged with buffer identity.

        Like [`get_raw_snapshot`][] but returns arrays the acquire thread cannot
        overwrite, for render-side consumers carrying state across frames (the
        incremental display notch): the copy so a concurrent buffer refresh cannot
        tear the samples being filtered (a torn read poisons the IIR state
        permanently), ``(epoch, end_seq)`` to tell new samples from seen ones and
        detect a reallocation, and ``fs`` so the rate matches the copied samples —
        reading ``stream.info.fs`` separately can race a reconnect.

        ``duration_s`` copies only the newest ``duration_s`` seconds instead of the
        whole buffer (a 60 s buffer at 10 kHz is ~40 MB per frame). The trim uses the
        *locked* ``fs``. ``end_seq`` stays absolute, so the returned ``data[i]`` has
        sequence ``end_seq - len(data) + i``.

        Returns ``(epoch, end_seq, fs, ts, data)`` or ``None`` if fewer than 2 samples
        are buffered (or the stream is not connected).
        """
        with self._lock:
            if self._data is None or self._timestamps is None or self.info is None:
                return None
            n = self._data.shape[0]
            if n < 2:
                return None
            fs = self.info.fs
            if duration_s is None or not np.isfinite(fs) or fs <= 0.0:
                take = n
            else:
                take = min(n, int(duration_s * fs) + 4)
            ts = np.empty(take, dtype=np.float64)
            data = np.empty((take, self.info.n_channels), dtype=self.info.dtype)
            _copy_ring_tail_into(self._timestamps, ts, take, self._cap)
            _copy_ring_tail_into(self._data, data, take, self._cap)
            return (
                self.epoch,
                self._total_seq,
                fs,
                ts,
                data,
            )

    def last_timestamp(self) -> float | None:
        """Most recent sample timestamp, or None if no samples yet.

        Reads the ring tail under `_lock`, so a concurrent reconnect or append
        cannot strand the read on a torn buffer.
        """
        with self._lock:
            if self._timestamps is None or self._timestamps.shape[0] < 1:
                return None
            _copy_ring_tail_into(self._timestamps, self._win_t, 1, self._cap)
            ts = float(self._win_t[0])
        return ts if ts > 0.0 else None
