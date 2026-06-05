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
`fire_if_changed`) plus *occasional* `rebase()` from the UI thread. Both
assignments to the internal `_last` slot are atomic under CPython's GIL, so
no lock is needed. A race between the two paths can cause one extra
suppressed-or-fired callback - harmless for the intended uses (RPC dedup,
audio gating, log lines).

If your callback itself is not thread-safe, gate it inside the callback,
not here.

## When *not* to use it

* The downstream effect is genuinely per-tick continuous - e.g. streaming
  a pose vector. Use a normal call, not an edge trigger.
* You need *time-based* debouncing (e.g. ignore changes faster than 100 ms).
  `EdgeTrigger` is purely value-based; combine it with a `time.monotonic()`
  check or a state machine for hysteresis.

## See also

* [[integrate-vhi]] - the canonical use case, gating gRPC `SetMovement`
  on the predicted class.
* [`myogestic.outputs.edge_trigger.EdgeTrigger`](../api/core.md) - full API reference.
