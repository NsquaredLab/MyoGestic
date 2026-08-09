"""The tracking target as a stream, so it lands in the recording beside the EMG.

Reconstructing what the subject was asked to do from a start time and a copy of the
task parameters means trusting two clocks to agree months after the session. Streaming
the target instead makes it a recorded signal like any other: sample-by-sample, on the
same clock, aligned by construction.

The trajectory is two channels — the level, and the phase as a number, since a stream
carries floats and not strings. `PHASE_CODES` is the key, and it is **frozen**: an
analysis script reads recordings written long before it existed, so codes are only ever
added, never renumbered. The level channel is named ``target_pct`` for the same reason:
it predates the signed trajectories and renaming it would orphan every recording made
so far. Its unit is whatever the trajectory works in — percent of MVC for `Trapezoid`,
signed control units for `Pursuit`.
"""

from __future__ import annotations

import time

import numpy as np

from myogestic.stream import StreamInfo
from myogestic.tracking import Trajectory

#: Phase name to the number carried on the ``phase`` channel. Frozen — see the module
#: docstring. Covers every phase a `Trajectory` can return.
PHASE_CODES: dict[str, int] = {
    "rest": 0,
    "ramp_up": 1,
    "hold": 2,
    "ramp_down": 3,
    "recover": 4,
    "done": 5,
    # No block running. Its own code, not "rest": both sit at 0 in `target_pct`, so
    # sharing one would hide where a block begins.
    "idle": 6,
}


class TargetSource:
    """Streams a `Trajectory` target as a recordable two-channel signal.

    Implements the same ``connect`` / ``read`` / ``disconnect`` contract as the
    amplifier sources, so a `Stream` records it exactly as it records EMG and the two
    line up sample for sample. Timestamps come from the ``mne_lsl`` ``local_clock()``
    domain, the same domain every other source stamps in — that shared clock is the
    whole point, and is what lets an offline script put target and EMG on one axis.

    The stream runs from ``connect()`` to ``disconnect()``; `start` and `stop` control
    the *task*, not the stream. While stopped it keeps emitting baseline rather than
    going quiet, because a source that stops producing leaves a hole in the recording
    exactly where the operator was setting the block up — and a hole is indistinguishable
    from a dropout at analysis time.

    ``read`` blocks until the next chunk is due, the way a real inlet's blocking pull
    does, so the acquire thread paces to `fs` instead of spinning.

    Parameters
    ----------
    trajectory
        The shape to follow — a `Trapezoid`, a `Pursuit`, or anything else matching
        `Trajectory` — or ``None`` for a source that only ever emits baseline.
    fs
        Sample rate in Hz. The target is smooth and slow, so this does not need to match
        the amplifier's rate; the timestamps are what align the two, not the rate.

    Attributes
    ----------
    trajectory
        **Live.** Assign while streaming and the next chunk follows the new shape —
        what the editing UI does as a segment is dragged. Read once per chunk, and a
        plain assignment is atomic under the GIL, so no lock is needed.

    Examples
    --------
    >>> from myogestic import Stream
    >>> from myogestic.sources.target import TargetSource
    >>> from myogestic.tracking import Trapezoid
    >>> source = TargetSource(Trapezoid(level_pct=30.0))
    >>> stream = Stream("target", source=source, window_ms=10_000)
    >>> source.start()  # begins the block; the stream records throughout either way
    """

    #: Samples per read; N / fs sets the per-chunk pacing (100 ms at 100 Hz).
    _CHUNK = 10

    def __init__(self, trajectory: Trajectory | None = None, fs: float = 100.0) -> None:
        self.trajectory = trajectory
        self._fs = fs
        self._running = False
        self._t0: float | None = None
        self._elapsed = 0.0
        self._next_tick: float | None = None

    # -- Task control ----------------------------------------------------

    def start(self) -> None:
        """Begin the block — task time restarts from zero."""
        from mne_lsl.lsl import local_clock

        # `_t0` before `_running`: `read` tests `_running` first, so publishing the flag
        # last means it can never see a running task with no start time.
        self._t0 = local_clock()
        self._elapsed = 0.0
        self._running = True

    def stop(self) -> None:
        """End the block. The stream keeps emitting baseline."""
        self._running = False
        self._elapsed = 0.0

    @property
    def running(self) -> bool:
        """Whether a block is currently under way."""
        return self._running

    @property
    def elapsed(self) -> float:
        """Task time of the newest emitted sample, in seconds. ``0.0`` while stopped.

        Reported from the sample's own timestamp rather than from a fresh clock reading,
        so it names the point on the trajectory that was actually recorded.
        """
        return self._elapsed

    # -- Source protocol -------------------------------------------------

    def connect(self) -> StreamInfo:
        """Start emitting, and report the two-channel geometry."""
        from mne_lsl.lsl import local_clock

        self._next_tick = local_clock()
        return StreamInfo(
            n_channels=2,
            fs=self._fs,
            dtype=np.dtype("float32"),
            channel_names=["target_pct", "phase"],
        )

    def read(self) -> tuple[np.ndarray, np.ndarray]:
        """Return the next chunk of target samples, blocking until it is due."""
        from mne_lsl.lsl import local_clock

        assert self._next_tick is not None
        target = self._next_tick + self._CHUNK / self._fs
        now = local_clock()
        if target > now:
            time.sleep(target - now)
        self._next_tick = target

        n = self._CHUNK
        ts = (target + (np.arange(n) - (n - 1)) / self._fs).astype(np.float64)

        # Once per chunk, so an edit landing mid-chunk cannot splice half the samples
        # onto the old ramp and half onto the new one.
        running, t0, task = self._running, self._t0, self.trajectory

        out = np.zeros((n, 2), dtype=np.float32)
        if running and task is not None:
            # Task time from each sample's own timestamp, so target and EMG recorded
            # at one instant carry that instant — no drift to correct for later.
            for i, t in enumerate(ts - t0):
                out[i] = (task.value_at(t), PHASE_CODES[task.phase_at(t)])
            self._elapsed = float(ts[-1] - t0)
            # Ended here, not in the widget: a widget only ticks while it is drawn,
            # so a block in a background tab would run past its own end.
            if self._elapsed >= task.total_duration:
                self.stop()
        else:
            out[:, 1] = PHASE_CODES["idle"]
            self._elapsed = 0.0
        return out, ts

    def disconnect(self) -> None:
        """Stop the block. Nothing to release — the generator holds no handle."""
        self.stop()


__all__ = ["PHASE_CODES", "TargetSource"]
