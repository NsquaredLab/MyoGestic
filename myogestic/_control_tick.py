"""Pace complete control frames independently of model input availability."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from typing import Any


class ControlTicker:
    """Share an output clock between GUI frames and fresh predictions.

    Parameters
    ----------
    hz
        Finite, positive output rate in hertz, matching the control bus and its
        smoothing filter.

    Notes
    -----
    Call `run` on every GUI or output-clock tick, even without model input. Fresh
    predictions may request immediate delivery. The callback runs synchronously;
    another caller returns without waiting while it is in flight. There is no
    background thread or catch-up burst after a gap. Keep inference, connection
    attempts and blocking device I/O outside the callback.

    Send a complete frame, including the cached prediction and control target:
    `ControlBus.push` fills omitted aliases with rest. Cache explicit commands
    before calling `run`, so busy deliveries do not lose them. Compute per-frame
    targets locally; writing them back into that cache can overwrite a concurrent
    Stop or held-control command.
    """

    def __init__(self, hz: float) -> None:
        if not math.isfinite(hz) or hz <= 0:
            raise ValueError("hz: pass a finite, positive output rate")
        self._period = 1.0 / hz
        self._last = -math.inf
        self._lock = threading.Lock()

    def run(self, callback: Callable[[float], Any], *, now: float, immediate: bool = False) -> Any:
        """Deliver one due frame without waiting for another caller.

        Parameters
        ----------
        callback
            Synchronous delivery function, called with `now` only when due and
            no other callback is in flight. Exceptions propagate; the ticker
            remains available and its clock advances only on success.
        now
            Timestamp in seconds on the shared output clock. Use the LSL clock
            for `FollowRun`. A timestamp older than the last successful delivery
            is ignored, even with `immediate`.
        immediate
            Bypass the rate limit for a fresh prediction or command. A successful
            delivery starts a new interval before the next paced frame.

        Returns
        -------
        Any
            The callback's result, or ``None`` when busy, not due or older than
            the last delivery. Skipped calls are not queued.
        """
        if not self._lock.acquire(blocking=False):
            return None
        try:
            if now < self._last or (not immediate and now - self._last < self._period):
                return None
            result = callback(now)
            self._last = now
            return result
        finally:
            self._lock.release()
