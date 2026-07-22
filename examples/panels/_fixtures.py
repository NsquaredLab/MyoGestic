"""Shared dummy fixtures for the per-panel examples.

Only the paced synthetic Stream source lives here — it's reused by every
stream-backed example (``signal_viewer``, ``raw_signal_viewer``,
``stream_panel``, ``recording_controls``, ``pipeline_panel``). One-off
dummy data (arrays, mock sessions, fake pipeline) stays inline in each
example so the file reads standalone.

Not a public API — just enough to make the panels light up without
hardware. Underscore-prefixed so ``examples/panels/*.py`` globs skip it.
"""

from __future__ import annotations

import time

import numpy as np

from myogestic import StreamInfo


class SyntheticSource:
    """In-process synthetic EMG source — sine waves + noise, wall-clock paced.

    Same ``connect``/``read``/``disconnect`` contract as the real sources,
    plus the optional ``discover``/``reconnect`` extensions so
    ``stream_panel``'s Scan → Connect flow works. Timestamps use the
    ``mne_lsl`` ``local_clock()`` domain (not a relative counter) so the
    viewers' "now" and ``stream_panel``'s "last sample age" read correctly.

    Parameters
    ----------
    n_channels
        Channel count the ``StreamInfo`` advertises.
    fs
        Sample rate in Hz.
    require_target
        When ``True`` the source starts with **no** target selected, so
        ``connect()`` raises until a target is chosen via ``reconnect()``.
        This makes a fresh stream present as *disconnected* — the state
        ``stream_panel`` needs to render its Scan/Connect buttons. When
        ``False`` (default) the source connects immediately.
    """

    #: Samples per read; N / fs sets the per-chunk pacing (~31 ms at 2048 Hz).
    _CHUNK = 64

    def __init__(
        self, n_channels: int = 8, fs: float = 2048.0, *, require_target: bool = False
    ) -> None:
        self._n = n_channels
        self._fs = fs
        self._target: str | None = None if require_target else "Synthetic EMG"
        self._pos = 0
        self._next_tick: float | None = None

    # -- Source protocol ------------------------------------------------

    def connect(self) -> StreamInfo:
        if self._target is None:
            raise ConnectionError("No device selected — Scan, then Connect.")
        from mne_lsl.lsl import local_clock

        self._next_tick = local_clock()
        return StreamInfo(n_channels=self._n, fs=self._fs, dtype=np.dtype("float32"))

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        from mne_lsl.lsl import local_clock

        # Block until the next chunk is due, so the acquire thread paces to
        # `fs` instead of spinning and squashing thousands of chunks onto one
        # x-position. Mirrors a real LSL inlet's blocking pull_chunk.
        assert self._next_tick is not None
        target = self._next_tick + self._CHUNK / self._fs
        now = local_clock()
        if target > now:
            time.sleep(target - now)
        self._next_tick = target

        n = self._CHUNK
        t = (self._pos + np.arange(n)) / self._fs
        self._pos += n
        # One distinct sine (5..5+n_channels Hz) + noise per channel, plus a
        # shared 50 Hz mains hum on every channel so the viewer's Notch control
        # has something to remove.
        freqs = 5.0 + np.arange(self._n)
        hum = 0.35 * np.sin(2 * np.pi * 50.0 * t)[:, None]
        data = (
            np.sin(2 * np.pi * np.outer(t, freqs)) + hum + 0.12 * np.random.randn(n, self._n)
        ).astype(np.float32)
        # Chunk of `n` samples ending at the wall clock we just paced to.
        ts = (target + (np.arange(n) - (n - 1)) / self._fs).astype(np.float64)
        return data, ts

    def disconnect(self) -> None:
        pass

    # -- Optional extensions used by stream_panel -----------------------

    def discover(self) -> list[dict[str, str]]:
        return [{"name": "Synthetic EMG", "info": f"{self._n} ch · {self._fs:.0f} Hz"}]

    def reconnect(self, target: str | None = None) -> StreamInfo:
        if target is not None:
            self._target = target
        return self.connect()
