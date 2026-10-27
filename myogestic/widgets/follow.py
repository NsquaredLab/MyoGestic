"""A reusable recorded control-following card, independent of hand hardware."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import asdict

from mne_lsl.lsl import local_clock

from myogestic.core import Context
from myogestic.sources.target import PHASE_CODES
from myogestic.tracking import Sinusoid
from myogestic.widgets._follow_state import FollowState, score_take


class FollowRun:
    """Run and score a smooth relaxed-to-gesture target in a dedicated take.

    Parameters
    ----------
    gestures
        Non-empty gesture names. The exposed index addresses this exact sequence.
    on_record, on_stop
        Start and stop callbacks, usually ``app.start_recording`` and
        ``app.stop_recording``. The app may wrap these to start/stop prediction.
    trajectory
        Initial editable shape; defaults to `Sinusoid`.
    prediction_stream, prediction_channel
        Saved scalar prediction to score in the same fractional units as the target.
        A channel name or zero-based index; defaults to the delivered control bus's
        ``prediction`` alias. Apps with pose vectors should record a projected scalar
        level as an event stream and select its channel here.
    max_lag_s
        Finite, non-negative correlation search radius.
    widget_id
        Stable ImGui identity. Give each card its own ID.

    Notes
    -----
    Call `tick` on each control update, then send its target via the app's bus.
    Call `sync` every UI frame, even when the card is hidden, to stop at the deadline
    and score after saving. `ui` also calls `sync`. Call `stop` before app shutdown.
    Neither `tick` nor `target` performs GUI work. Setup and lifecycle methods belong
    on the UI thread; `tick` may run on the prediction thread.
    """

    def __init__(
        self,
        gestures: Sequence[str],
        *,
        on_record: Callable[[], None],
        on_stop: Callable[[], None],
        trajectory: Sinusoid | None = None,
        prediction_stream: str = "controls",
        prediction_channel: str | int = "prediction",
        max_lag_s: float = 1.0,
        widget_id: str = "follow",
    ) -> None:
        if not gestures or any(not name.strip() for name in gestures):
            raise ValueError("gestures: supply at least one non-empty gesture name")
        if not math.isfinite(max_lag_s) or max_lag_s < 0:
            raise ValueError("max_lag_s: pass finite seconds >= 0")
        if isinstance(prediction_channel, int) and prediction_channel < 0:
            raise ValueError("prediction_channel: pass a channel name or non-negative index")
        self.gestures = tuple(gestures)
        self._on_record, self._on_stop = on_record, on_stop
        self._stream, self._channel = prediction_stream, prediction_channel
        self._max_lag_s, self._widget_id = max_lag_s, widget_id
        self._state = FollowState(trajectory or Sinusoid())

    @property
    def running(self) -> bool:
        """Whether this card owns an active run."""
        return self._state.phase == "running"

    @property
    def target(self) -> tuple[int, float] | None:
        """Latest tick's gesture index and fraction, or None outside a run."""
        return self._state.target

    @property
    def score(self) -> dict[str, float | None] | None:
        """Metrics read from the saved take, or None before scoring finishes."""
        return None if self._state.score is None else dict(self._state.score)

    def start(self, ctx: Context) -> bool:
        """Start a new take; return False if busy or the callback refuses recording."""
        s = self._state
        if ctx.recording or s.phase in ("running", "saving"):
            return False
        self._on_record()
        if not ctx.recording or ctx.session is None:
            return False
        with s.lock:
            s.session, s.started = ctx.session, local_clock()
            s.source_path = s.session.path.resolve()
            s.elapsed, s.score, s.last_timestamp = 0.0, None, -math.inf
            s.session.extras["follow"] = {
                "gestures": list(self.gestures),
                "gesture_index": s.gesture,
                "trajectory": asdict(s.trajectory),
                "started": s.started,
                "ended": s.started + s.trajectory.total_duration,
                "prediction_stream": self._stream,
                "prediction_channel": self._channel,
                "max_lag_s": self._max_lag_s,
            }
            s.phase = "running"
            self.tick(ctx, timestamp=s.started)
        return True

    def tick(self, ctx: Context, *, timestamp: float | None = None) -> tuple[int, float] | None:
        """Record and return the current target on the shared LSL clock.

        Call before pushing the control frame. At and beyond the deadline the
        target is relaxed until `sync` saves the take on the UI thread.
        """
        s = self._state
        with s.lock:
            now = local_clock() if timestamp is None else timestamp
            if not math.isfinite(now):
                raise ValueError("timestamp: pass finite seconds on the LSL clock")
            if not self.running or not ctx.recording or ctx.session is not s.session:
                s.target = None
                return None
            if now < s.last_timestamp:
                raise ValueError("timestamp: pass non-decreasing LSL timestamps")
            s.elapsed = max(0.0, now - s.started)
            level = s.trajectory.value_at(s.elapsed)
            s.target = (s.gesture, level)
            if now > s.last_timestamp:
                s.session.append_event(
                    "follow.target",
                    [s.gesture, level, PHASE_CODES[s.trajectory.phase_at(s.elapsed)]],
                    now,
                    channel_names=["gesture_index", "level", "phase"],
                )
                s.last_timestamp = now
            return s.target

    def stop(self, ctx: Context) -> None:
        """Close this run, save its partial interval and leave other takes alone."""
        s = self._state
        with s.lock:
            if not self.running:
                return
            s.session.extras["follow"]["ended"] = min(
                local_clock(),
                s.started + s.trajectory.total_duration,
            )
            s.phase, s.target = "saving", None
            owns = ctx.recording and ctx.session is s.session
        # A callback may join the prediction thread: never hold its tick lock here.
        if owns:
            self._on_stop()

    def sync(self, ctx: Context) -> None:
        """Finish expired/interrupted runs and score only once the save completes."""
        s = self._state
        if self.running and (
            local_clock() >= s.started + s.trajectory.total_duration
            or not ctx.recording
            or ctx.session is not s.session
        ):
            self.stop(ctx)
        if s.phase == "saving" and s.source_path not in ctx.pending_saves:
            try:
                s.score = score_take(s.session.path)
                s.phase = "results"
            except Exception:
                s.phase = "error"
                ctx.log("The follow run could not be scored from its saved take.")

    def ui(self, ctx: Context, *, disabled_reason: str = "") -> None:
        """Draw the card; a visible `disabled_reason` gates new starts only."""
        from myogestic.widgets._follow_ui import draw

        self.sync(ctx)
        draw(self, ctx, disabled_reason)
