"""A reusable recorded control-following card, independent of hand hardware."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from threading import Thread
from time import monotonic
from typing import Any

from mne_lsl.lsl import local_clock
from numpy.typing import ArrayLike

from myogestic.controls import ControlLink
from myogestic.core import Context
from myogestic.session import Session
from myogestic.sources.target import PHASE_CODES
from myogestic.tracking import Sinusoid, blend_pose
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
    drive
        Called with ``(gesture_index, level)`` on a dedicated daemon thread. Push
        the operator hand's bus here; keep it separate from prediction's bus.
        Exceptions are logged once per run and subsequent steps keep running.
        Supply exactly one of ``drive`` and ``operator``.
    operator
        Link to drive directly with blended pose vectors. Its bus is read on every
        step; an unbound link is a no-op and is never bound by this card.
    aliases, poses, rest
        Operator mode's ordered aliases, gesture-name-to-pose mapping, and relaxed
        pose. Every gesture must have a finite one-dimensional pose with exactly
        one value per alias. Shapes and values are validated at construction.
    hz
        Finite, positive drive rate in Hz; defaults to 32.
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
    The operator hand runs on its own clock, independent of EMG, the GUI and
    `predict`. Give its link ``ctx=app.ctx, record_as="controls.operator"`` and
    no smoothing to record it separately. `hold` no-ops while `running`.
    Call `sync` every UI frame, even when hidden, to stop at the deadline and
    score after saving. `ui` also calls `sync`. Register `stop` in the app's
    cleanup hooks. `stop` joins the driver and, in operator mode, pushes rest before
    `on_stop`, including after an external recording stop. Lifecycle methods belong
    on the UI thread; `drive` must return and must not call lifecycle methods or GUI code.
    """

    def __init__(
        self,
        gestures: Sequence[str],
        *,
        drive: Callable[[int, float], Any] | None = None,
        operator: ControlLink | None = None,
        aliases: Sequence[str] = (),
        poses: Mapping[str, ArrayLike] | None = None,
        rest: ArrayLike | None = None,
        on_record: Callable[[], None],
        on_stop: Callable[[], None],
        hz: float = 32.0,
        trajectory: Sinusoid | None = None,
        prediction_stream: str = "controls",
        prediction_channel: str | int = "prediction",
        max_lag_s: float = 1.0,
        widget_id: str = "follow",
    ) -> None:
        if not gestures or any(not name.strip() for name in gestures):
            raise ValueError("gestures: supply at least one non-empty gesture name")
        if not math.isfinite(hz) or hz <= 0:
            raise ValueError("hz: pass a finite rate > 0")
        if not math.isfinite(max_lag_s) or max_lag_s < 0:
            raise ValueError("max_lag_s: pass finite seconds >= 0")
        if isinstance(prediction_channel, int) and prediction_channel < 0:
            raise ValueError("prediction_channel: pass a channel name or non-negative index")
        if (drive is None) == (operator is None):
            raise ValueError("supply exactly one of drive= or operator=")
        self.gestures = tuple(gestures)
        self._operator, self._aliases = operator, tuple(aliases)
        self._poses: dict[str, ArrayLike] = {}
        self._rest: ArrayLike = ()
        if operator is not None:
            if not self._aliases or poses is None or rest is None:
                raise ValueError("operator: supply aliases=, poses= and rest=")
            for name in self.gestures:
                if name not in poses:
                    raise ValueError(f"poses: supply a pose for gesture {name!r}")
                relaxed = blend_pose(rest, poses[name], 0)
                if len(relaxed) != len(self._aliases):
                    raise ValueError("poses and rest: supply one value per alias")
                self._poses[name] = blend_pose(rest, poses[name], 1)
            self._rest = relaxed
        self._drive = drive if drive is not None else self._drive_operator
        self._hz = hz
        self._on_record, self._on_stop = on_record, on_stop
        self._stream, self._channel = prediction_stream, prediction_channel
        self._max_lag_s, self._widget_id = max_lag_s, widget_id
        self._state = FollowState(trajectory or Sinusoid())
        self._finalize_hooks: list[Callable[[Session], None]] | None = None

    @property
    def running(self) -> bool:
        """Whether this card owns an active run."""
        return self._state.phase == "running"

    @property
    def target(self) -> tuple[int, float] | None:
        """Latest driver step's gesture index and fraction, or None outside a run."""
        return self._state.target

    @property
    def score(self) -> dict[str, float | None] | None:
        """Metrics read from the saved take, or None before scoring finishes."""
        return None if self._state.score is None else dict(self._state.score)

    def _push_operator(self, pose: ArrayLike) -> Mapping[str, float | str] | None:
        bus = None if self._operator is None else self._operator.bus
        if bus is None:
            return None
        return bus.push(dict(zip(self._aliases, pose, strict=True)))

    def _drive_operator(self, index: int, level: float) -> None:
        self._push_operator(blend_pose(self._rest, self._poses[self.gestures[index]], level))

    def hold(self, pose: ArrayLike | None = None) -> Mapping[str, float | str] | None:
        """Push a held pose (rest by default) on the UI thread and return its delivery.

        Return `None` while running, unbound, or using ``drive=``. Never binds a link.
        """
        if self.running:
            return None
        return self._push_operator(self._rest if pose is None else pose)

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
            s.ended = None
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
            self._finalize_hooks = ctx.finalize_hooks
            self._finalize_hooks.append(self._on_finalize)
            self._step(ctx)
            s.stop_event.clear()
            s.worker = Thread(
                target=self._run, args=(ctx,), name=f"follow-{self._widget_id}", daemon=True
            )
            s.worker.start()
        return True

    def _step(self, ctx: Context) -> tuple[int, float] | None:
        """Record one target on the LSL clock, without holding the lock during drive."""
        s = self._state
        with s.lock:
            now = local_clock()
            if not self.running or not ctx.recording or ctx.session is not s.session:
                s.target = None
                return None
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

    def _run(self, ctx: Context) -> None:
        """Drive at the requested cadence without catch-up bursts after a slow push."""
        s, warned = self._state, False
        deadline = monotonic()
        while not s.stop_event.is_set():
            target = self._step(ctx)
            if target is None:
                return
            try:
                self._drive(*target)
            except Exception as exc:
                if not warned:
                    ctx.log(f"Follow drive failed; continuing: {exc}")
                    warned = True
            deadline += 1.0 / self._hz
            now = monotonic()
            if deadline < now:
                deadline = now + 1.0 / self._hz
            s.stop_event.wait(max(0.0, deadline - now))

    def _on_finalize(self, session: Session) -> None:
        """Stamp this take's end before metadata is saved, without joining the driver."""
        s = self._state
        with s.lock:
            if session is not s.session:
                return
            # A normal Stop already chose its exact time, possibly between samples.
            if s.ended is None:
                s.ended = s.last_timestamp if math.isfinite(s.last_timestamp) else local_clock()
            meta = session.extras["follow"]
            s.ended = meta["ended"] = min(
                meta["ended"], s.ended, s.started + s.trajectory.total_duration
            )

    def stop(self, ctx: Context) -> None:
        """Close this run, save its partial interval and leave other takes alone."""
        s = self._state
        with s.lock:
            if not self.running:
                return
            if ctx.recording and ctx.session is s.session:
                s.ended = s.session.extras["follow"]["ended"] = min(
                    s.session.extras["follow"]["ended"],
                    local_clock(),
                    s.started + s.trajectory.total_duration,
                )
            s.stop_event.set()
        # A blocked push must finish before the final rest is delivered.
        if s.worker is not None:
            s.worker.join()
        with s.lock:
            s.phase, s.target = "saving", None
            owns = ctx.recording and ctx.session is s.session
        self.hold()
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
            if self._finalize_hooks is not None:
                self._finalize_hooks.remove(self._on_finalize)
                self._finalize_hooks = None
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
