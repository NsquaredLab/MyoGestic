"""A fake load cell, for exercising a force task without a transducer."""

from __future__ import annotations

import time

import numpy as np

from myogestic.stream import StreamInfo


class SyntheticForceSource:
    """A synthetic force channel you drive by hand, for testing without a transducer.

    It stands in for the **transducer**, not for the subject. You are the
    subject: watch the target and move ``effort``, exactly as the person on a
    real load cell watches the plot and pushes. Nothing here tracks the target
    on its own — a channel that did would draw a tracking error nobody produced,
    and that error is the number the whole task exists to measure.

    `SyntheticSource` cannot stand in for this. Its channels are fixed sine
    waves, so there is no resting level to zero and no peak to calibrate against.

    It emits in arbitrary volts, not in % MVC, precisely so the calibration is
    not free: the resting reading is ``zero`` and a full effort is
    ``zero + span``, so capturing Zero and MVC does real work and a task run
    against a bad calibration reads wrong, exactly as it would with hardware.

    Parameters
    ----------
    fs
        Sample rate in Hz.
    zero
        Resting reading in volts, the transducer's own offset. Non-zero on
        purpose: a calibration that assumes the rest reading is 0 is the mistake
        this exists to let you make and see.
    span
        Volts between rest and a full (100 % MVC) effort.
    effort
        Live, 0..1. What you are producing, and the only thing driving the
        channel. Raise it to capture an MVC, then move it to follow the target
        once a block is running.
    noise
        Live. Gaussian noise standard deviation in volts.
    lag_s
        Live. First-order smoothing, in seconds, so dragging the slider reads as
        a contraction rather than as a step. ``0`` follows the slider exactly.

    Examples
    --------
    >>> from myogestic import Stream
    >>> from myogestic.sources import SyntheticForceSource
    >>> force = SyntheticForceSource()
    >>> force.effort = 1.0  # what capturing an MVC looks like
    >>> stream = Stream("force", source=force, window_ms=500)
    >>> stream.reconnect()
    True
    """

    #: Samples per read; N / fs sets the per-chunk pacing.
    _CHUNK = 16

    def __init__(
        self,
        *,
        fs: float = 100.0,
        zero: float = 0.30,
        span: float = 2.0,
        effort: float = 0.0,
        noise: float = 0.01,
        lag_s: float = 0.25,
    ) -> None:
        self._fs = fs
        self._zero = zero
        self._span = span
        #: Live: what you are producing, 0..1. The only thing driving the channel.
        self.effort = effort
        #: Live: Gaussian noise standard deviation, in volts.
        self.noise = noise
        #: Live: first-order smoothing on `effort`, in seconds.
        self.lag_s = lag_s
        self._state = 0.0
        self._next_tick: float | None = None

    # -- Source protocol ------------------------------------------------

    def connect(self) -> StreamInfo:
        """Start generating. One channel, in volts."""
        from mne_lsl.lsl import local_clock

        self._next_tick = local_clock()
        self._state = 0.0
        return StreamInfo(
            n_channels=1, fs=self._fs, dtype=np.dtype("float32"), channel_names=["force"]
        )

    def read(self) -> tuple[np.ndarray, np.ndarray]:
        """Return the next chunk, blocking until it is due."""
        from mne_lsl.lsl import local_clock

        assert self._next_tick is not None
        due = self._next_tick + self._CHUNK / self._fs
        now = local_clock()
        if due > now:
            time.sleep(due - now)
        self._next_tick = due

        n = self._CHUNK
        dt = 1.0 / self._fs
        # Read the live knobs once per chunk, so an edit landing from the UI
        # thread mid-chunk cannot splice one chunk across two settings.
        effort, noise, lag = self.effort, self.noise, max(self.lag_s, 0.0)

        # First-order approach to `effort`, per sample. `alpha == 1` (lag 0) is the
        # degenerate follow-the-slider-exactly case, which is why the guard is on
        # lag and not on the ratio.
        alpha = 1.0 if lag <= 0.0 else min(dt / lag, 1.0)
        out = np.empty((n, 1), dtype=np.float32)
        state = self._state
        for i in range(n):
            state += (effort - state) * alpha
            out[i, 0] = self._zero + self._span * state
        self._state = state
        if noise > 0.0:
            out += (noise * np.random.randn(n, 1)).astype(np.float32)

        ts = (due + (np.arange(n) - (n - 1)) * dt).astype(np.float64)
        return out, ts

    def disconnect(self) -> None:
        """Nothing to release — the generator holds no handle."""


__all__ = ["SyntheticForceSource"]
