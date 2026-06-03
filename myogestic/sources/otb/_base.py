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
    ``read`` for non-blocking recv.
    """

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._info: StreamInfo | None = None
        self._frame_nbytes: int = 0

    # --- subclass hooks -----------------------------------------------------
    def _open(self) -> StreamInfo:
        raise NotImplementedError

    def _send_start(self) -> None:
        raise NotImplementedError

    def _send_stop(self) -> None:
        raise NotImplementedError

    def _decode(self, frame: bytes) -> np.ndarray:
        raise NotImplementedError

    # --- Source protocol ----------------------------------------------------
    def connect(self) -> StreamInfo:
        self._buf.clear()
        info = self._open()
        self._info = info
        self._send_start()
        return info

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        if self._sock is not None:
            try:
                chunk = self._sock.recv(65536)
                if chunk:
                    self._buf.extend(chunk)
            except BlockingIOError:
                pass
            except OSError:
                return None, None
        return self._drain()

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
    def _drain(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Slice all complete frames out of the buffer, decode, timestamp."""
        if self._frame_nbytes <= 0 or len(self._buf) < self._frame_nbytes:
            return None, None
        n_frames = len(self._buf) // self._frame_nbytes
        take = n_frames * self._frame_nbytes
        raw = bytes(self._buf[:take])
        del self._buf[:take]
        data = self._decode(raw)
        n = data.shape[0]
        fs = float(self._info.fs)
        end = local_clock()
        ts = end - (np.arange(n - 1, -1, -1, dtype=np.float64) / fs)
        return data, ts
