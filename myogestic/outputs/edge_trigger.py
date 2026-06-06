"""Fire-on-change helper for predict→discrete-event pipelines.

Idiomatic use is "the model emits a class index every tick; only call the
side-effect (a gRPC RPC, a serial write, …) when the class actually
changes." Without that gate, the side-effect re-fires every tick, which is
fine if it's idempotent and free, but often wastes work or even re-triggers
animations.

::

    from myogestic.outputs import EdgeTrigger

    trigger = EdgeTrigger(callback=vhi_client.set_movement)

    @pipeline.predict
    def predict(model, features):
        class_idx = int(np.argmax(model.predict_proba(features)))
        trigger.fire_if_changed(CLASSES[class_idx])

    def _on_gesture(i):
        # User clicked a button — sync the trigger so the next predict tick
        # doesn't re-fire the same movement on top of the manual action.
        trigger.rebase(CLASSES[i])
"""

from __future__ import annotations

from collections.abc import Callable


class EdgeTrigger[T]:
    """Calls ``callback(value)`` only when ``value`` differs from the last fire.

    Parameters
    ----------
    callback
        Invoked with the new value when an edge fires.
    stable_ticks
        Debounce: the new value must hold for this many *consecutive*
        :meth:`fire_if_changed` calls before firing. ``1`` (default) fires
        immediately on the first changed value — i.e. dedupe only. Use ``>1`` to
        swallow tick-to-tick flicker (e.g. a classifier's ``argmax`` oscillating
        during a sliding-window transition) so the side effect isn't re-fired on
        every flip. It counts *calls*, not time — convert a duration with the
        loop rate: ``stable_ticks=math.ceil(seconds * predict_hz)``.

    Notes
    -----
    Thread-safety: the typical pattern is "one writer (predict thread) +
    occasional ``rebase()`` from the UI thread". The whole ``(last, candidate,
    count)`` state is held in one tuple replaced in a single assignment, so under
    CPython's GIL no lock is needed; a race between the two callers can at worst
    cost one extra suppressed-or-fired callback — harmless for the intended uses
    (RPC dedup, audio-cue gating, robot-movement commands).
    """

    __slots__ = ("_callback", "_stable_ticks", "_state")

    def __init__(self, callback: Callable[[T], None], *, stable_ticks: int = 1) -> None:
        if stable_ticks < 1:
            raise ValueError(f"stable_ticks must be >= 1 (got {stable_ticks})")
        self._callback = callback
        self._stable_ticks = stable_ticks
        # (last_fired, pending_candidate, candidate_count) — replaced atomically.
        self._state: tuple[T | None, T | None, int] = (None, None, 0)

    def fire_if_changed(self, value: T) -> bool:
        """Fire iff ``value`` differs from the last fired value and (when
        ``stable_ticks > 1``) has held for ``stable_ticks`` consecutive calls.

        Returns ``True`` when the callback ran, ``False`` when suppressed.
        """
        last, candidate, count = self._state
        if value == last:
            # Back to the current value — drop any half-formed candidate.
            if candidate is not None:
                self._state = (last, None, 0)
            return False
        count = count + 1 if value == candidate else 1
        if count >= self._stable_ticks:
            self._state = (value, None, 0)
            self._callback(value)
            return True
        self._state = (last, value, count)
        return False

    def rebase(self, value: T) -> None:
        """Set the "last fired" value without firing, discarding any pending
        debounce candidate.

        Use when another code path already performed the equivalent action; the
        next *different* value must then earn the full ``stable_ticks`` count, so
        a flicker candidate in progress can't complete on top of the manual one.
        """
        self._state = (value, None, 0)

    @property
    def last(self) -> T | None:
        """The most recently fired (or rebased) value; ``None`` before first fire."""
        return self._state[0]


__all__ = ["EdgeTrigger"]
