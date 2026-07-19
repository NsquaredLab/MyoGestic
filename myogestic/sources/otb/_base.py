"""Shared base for OTB socket sources.

Owns the pull-side machinery common to every OTB device: a byte accumulator
fed from the socket, complete-frame slicing, decode dispatch, and per-frame
timestamping. Subclasses implement the socket/protocol specifics.
"""
from __future__ import annotations

import socket

import numpy as np
from mne_lsl.lsl import local_clock

from myogestic.stream import StreamInfo


class _OTBSource:
    """Base class for OTB device sources (Muovi, Quattrocento).

    Subclasses must set ``self._info`` (StreamInfo) and ``self._frame_nbytes``
    in ``_open()``, and implement ``_open``/``_send_start``/``_send_stop``/
    ``_decode``. ``self._sock`` is the connected/accepted socket used by
    ``read`` for non-blocking recv. Call ``_prepare_stream()`` at the top of
    ``_open()`` to reset per-connection buffering/timestamp/closure state.
    """

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._info: StreamInfo | None = None
        self._frame_nbytes: int = 0
        # last emitted timestamp, for cross-batch monotonicity
        self._last_ts: float | None = None
        # set when the device drops the connection (empty recv / OSError)
        self._peer_closed: bool = False

    # --- subclass hooks -----------------------------------------------------
    def _open(self) -> StreamInfo:
        raise NotImplementedError

    def _send_start(self) -> None:
        raise NotImplementedError

    def _send_stop(self) -> None:
        raise NotImplementedError

    def _decode(self, frame: bytes) -> np.ndarray:
        raise NotImplementedError

    def _apply_target(self, target: str) -> None:
        """Update the connection target before a reconnect.

        Subclasses override (e.g. Quattrocento sets the device IP); base does
        nothing.
        """

    def _prepare_stream(self) -> None:
        """Reset per-connection state (buffer, timestamp anchor, closure flag)."""
        self._buf.clear()
        self._last_ts = None
        self._peer_closed = False

    # --- Source protocol ----------------------------------------------------
    def connect(self) -> StreamInfo:
        self._prepare_stream()
        info = self._open()
        self._info = info
        try:
            self._send_start()
        except Exception:
            self.disconnect()  # don't leak the opened socket on a failed start
            raise
        return info

    def reconnect(self, target: str | None = None) -> StreamInfo:
        """Drop the current connection and re-establish it (re-open + restart).

        Optional ``target`` retargets the source first (device IP for
        Quattrocento, bind IP for Muovi). Probed by ``Stream.reconnect``.
        """
        self.disconnect()
        if target is not None:
            self._apply_target(target)
        return self.connect()

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        sock = self._sock  # local so the type checker keeps the None-narrowing
        if sock is not None:
            try:
                chunk = sock.recv(65536)
                if chunk:
                    self._buf.extend(chunk)
                else:
                    # Empty recv = peer closed the connection.
                    self._on_peer_gone(sock)
            except BlockingIOError:
                pass
            except OSError:
                # Device reset / unplugged.
                self._on_peer_gone(sock)
        data, ts = self._drain()
        if data is not None:
            return data, ts  # flush whatever whole frames were already buffered
        if self._peer_closed:
            # Nothing left to flush and the device is gone: surface it so the
            # Stream marks the source disconnected (its read() except path)
            # instead of idling forever as "connected".
            raise ConnectionError("OTB device closed the connection")
        return None, None

    def disconnect(self) -> None:
        if self._sock is not None:
            try:
                self._send_stop()
            except OSError:
                pass
            try:
                self._sock.close()
            finally:
                self._sock = None
        self._buf.clear()

    # --- internals ----------------------------------------------------------
    def _on_peer_gone(self, sock: socket.socket) -> None:
        """Drop a dead socket but keep any buffered frames for a final flush."""
        try:
            sock.close()
        finally:
            self._sock = None
            self._peer_closed = True

    def _drain(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Slice all complete frames out of the buffer, decode, timestamp."""
        if self._frame_nbytes <= 0 or len(self._buf) < self._frame_nbytes:
            return None, None
        assert self._info is not None  # set by connect() alongside _frame_nbytes
        n_frames = len(self._buf) // self._frame_nbytes
        take = n_frames * self._frame_nbytes
        raw = bytes(self._buf[:take])
        del self._buf[:take]
        data = self._decode(raw)
        n = data.shape[0]
        fs = float(self._info.fs)
        # Anchor the batch's end to the LSL clock, but never overlap the previous
        # batch — viewers (and label alignment) assume strictly increasing
        # timestamps, and per-batch back-dating can otherwise cross under jitter.
        end = local_clock()
        first = end - (n - 1) / fs
        if self._last_ts is not None:
            first = max(first, self._last_ts + 1.0 / fs)
        ts = first + np.arange(n, dtype=np.float64) / fs
        self._last_ts = float(ts[-1])
        return data, ts
