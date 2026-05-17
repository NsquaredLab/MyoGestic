from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from myogestic.session import open_session_store
from myogestic.stream import StreamInfo


class ReplaySource:
    """Replays a recorded session as if it were a live stream.

    Accepts either a folder-format session or a `.session.zip` archive —
    delegates to `open_session_store` so both layouts work transparently.
    """

    def __init__(self, session_path: str, stream_name: str, speed: float = 1.0):
        self._path = Path(session_path)
        self._stream_name = stream_name
        self._speed = speed
        self._pos = 0
        self._last_read_time: float | None = None
        self._chunk_size = 64

    def connect(self) -> StreamInfo:
        sess = open_session_store(self._path)
        if self._stream_name not in sess.stores:
            raise ValueError(
                f"Stream {self._stream_name!r} not in session "
                f"{self._path} (have: {list(sess.stores)})"
            )
        self._data = sess.stores[self._stream_name]
        self._ts = sess.ts_stores[self._stream_name]
        info = sess.stream_info(self._stream_name)
        self._fs = info.fs
        return info

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        now = time.perf_counter()
        if self._last_read_time is not None:
            elapsed = (now - self._last_read_time) * self._speed
            samples_due = int(elapsed * self._fs)
            if samples_due < 1:
                return None, None
        else:
            samples_due = self._chunk_size

        self._last_read_time = now
        total = self._data.shape[0]
        end = min(self._pos + samples_due, total)
        if self._pos >= end:
            self._pos = 0  # loop
            return None, None

        data = np.array(self._data[self._pos : end])
        ts = np.array(self._ts[self._pos : end])
        self._pos = end
        return data, ts

    def disconnect(self) -> None:
        self._pos = 0
