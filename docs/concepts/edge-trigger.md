# Edge trigger - fire-on-change for discrete events

A classifier emits a class index *every tick* (~30-60 Hz). If you wire that
directly to a side-effect - a gRPC RPC to the Virtual Hand, a serial write,
an audio cue - the side-effect re-fires every tick. That's wasteful at best,
and at worst it cancels animations or floods a downstream service.

`EdgeTrigger` is the one-liner that gates this: call it every tick with the
latest value, and the callback runs **only on the rising edge** - the first
tick where the value differs from the previous one.

## The pattern

```python
from myogestic.outputs import EdgeTrigger

trigger = EdgeTrigger(callback=vhi_client.set_movement)

@pipeline.predict
def predict(model, features):
    class_idx = int(np.argmax(model.predict_proba(features)))
    trigger.fire_if_changed(CLASSES[class_idx])
```

`fire_if_changed(value)` returns `True` when the callback ran, `False`
when suppressed. The return value is useful for paired effects - e.g. log
a line only when the gesture actually changed.

## `rebase()` - when another path already fired

If the user clicks a button in the UI that performs the same side-effect
the trigger would, sync the trigger so it doesn't re-fire on the next tick:

```python
def _on_gesture_button(class_idx: int) -> None:
    vhi_client.set_movement(CLASSES[class_idx])     # do the action
    trigger.rebase(CLASSES[class_idx])              # baseline matches
```

Without the `rebase`, the next `predict` tick would see the predicted class
match what the button did and fire a redundant RPC (harmless if idempotent,
disruptive if it restarts an animation).

## `n_stable_ticks` - debounce flicker

On a noisy signal the predicted class flickers tick-to-tick - and for
~100-200 ms right after a gesture, while the classifier's sliding window still
holds the *old* data, `argmax` oscillates between the old and new class. With
the default `n_stable_ticks=1` every flip is a "change", so the callback re-fires
on each one and a robot hand visibly jumps between poses before settling.

Pass `n_stable_ticks=N` to require a value to hold for **N consecutive ticks**
before it fires, swallowing sub-`N` flicker:

```python
trigger = EdgeTrigger(vhi_client.set_movement, n_stable_ticks=5)
```

It counts *calls*, not time - convert a duration with the loop rate so the
window stays correct even if you change `predict_hz`:

```python
import math

STABLE_SECONDS = 0.1
trigger = EdgeTrigger(
    vhi_client.set_movement,
    n_stable_ticks=max(1, math.ceil(STABLE_SECONDS * pipeline.predict_hz)),
)
```

`rebase()` discards any half-formed candidate, so a manual command can't be
overridden by a flicker that was mid-count.

## Generic over `T`

`EdgeTrigger[T]` is parameterized on the value type. Strings (class names),
ints (class indices), tuples, named-tuples - anything that supports `==`
works:

```python
trigger: EdgeTrigger[int] = EdgeTrigger(_on_class_change)
trigger.fire_if_changed(2)
```

Use a tuple to gate on *multiple* fields at once - for example, fire only
when the predicted class **or** the dominant DOF changes:

```python
trigger: EdgeTrigger[tuple[str, str]] = EdgeTrigger(_on_state_change)
trigger.fire_if_changed((class_name, dominant_dof))
```

## Thread-safety

The typical wiring is *one writer* (the predict thread calling
`fire_if_changed`) plus *occasional* `rebase()` from the UI thread. The whole
`(last, candidate, count)` state lives in one tuple that's replaced in a single
assignment, so it updates atomically under CPython's GIL and no lock is needed.
A race between the two paths can cause one extra suppressed-or-fired callback -
harmless for the intended uses (RPC dedup, audio gating, log lines).

If your callback itself is not thread-safe, gate it inside the callback,
not here.

## When *not* to use it

* The downstream effect is genuinely per-tick continuous - e.g. streaming
  a pose vector. Use a normal call, not an edge trigger.
* You need *tick-based* debouncing (ignore flicker shorter than N ticks) -
  that's built in now via `n_stable_ticks` (above), including a seconds-derived
  window. For true *wall-clock* hysteresis independent of the tick rate, add a
  `time.monotonic()` gate inside your callback.

## See also

* [[integrate-vhi]] - the canonical use case, gating gRPC `SetMovement`
  on the predicted class.
* [`myogestic.outputs.edge_trigger.EdgeTrigger`](../api/core.md) - full API reference.
