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

    Thread-safety: the typical pattern is "one writer (predict thread) +
    occasional ``rebase()`` from the UI thread". Both assignments to
    ``self._last`` are atomic under CPython's GIL, so no explicit lock is
    needed; the cost is that a race between the two callers can result in
    one extra suppressed-or-fired callback, which is harmless for the
    intended use cases (RPC dedup, audio cue gating, etc.).
    """

    __slots__ = ("_callback", "_last")

    def __init__(self, callback: Callable[[T], None]) -> None:
        self._callback = callback
        self._last: T | None = None

    def fire_if_changed(self, value: T) -> bool:
        """Fire iff ``value`` differs from the last fired value.

        Returns ``True`` when the callback ran, ``False`` when suppressed.
        """
        if value == self._last:
            return False
        self._last = value
        self._callback(value)
        return True

    def rebase(self, value: T) -> None:
        """Set the "last fired" value without firing.

        Use when another code path already performed the equivalent action
        and the trigger should treat that as the new baseline.
        """
        self._last = value

    @property
    def last(self) -> T | None:
        """The most recently fired (or rebased) value; ``None`` before first fire."""
        return self._last


__all__ = ["EdgeTrigger"]
