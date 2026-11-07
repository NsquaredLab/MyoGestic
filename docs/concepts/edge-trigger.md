---
title: "Edge trigger - fire-on-change for discrete events"
---
A classifier emits a class index every tick at ~30-60 Hz. Calling a gRPC RPC,
serial write or audio cue on each tick can restart animations or flood a
downstream service.

Call `EdgeTrigger` every tick with the latest value. It runs the callback only when
the value changes from the last fired value and holds for the configured
number of stable ticks.

!!! tip "For a Virtual Hand, prefer a discrete DOF"
    `EdgeTrigger` is the primitive; you rarely need it directly. Declaring a
    discrete DOF with `debounce_s` gets the same gating plus the dedupe and
    rebase-on-click through `ControlBus`. See
    [the control standard](../api/controls.md). Reach for `EdgeTrigger` when you
    are driving something that is *not* a `myogestic.controls.Target`.

## The pattern

```python
from myogestic.outputs import EdgeTrigger

trigger = EdgeTrigger(callback=send_gesture_to_device)


@pipeline.predict
def predict(model, features):
    class_idx = int(np.argmax(model.predict_proba(features)))
    trigger.fire_if_changed(CLASSES[class_idx])
```

`fire_if_changed(value)` returns `True` when the callback ran, `False`
when suppressed. Use it to log a line only when the gesture changes.

## `rebase()` - when another path already fired

If the user clicks a button in the UI that performs the same side-effect
the trigger would, sync the trigger so it doesn't re-fire on the next tick:

```python
def _on_gesture_button(class_idx: int) -> None:
    send_gesture_to_device(CLASSES[class_idx])  # do the action
    trigger.rebase(CLASSES[class_idx])  # baseline matches
```

Without `rebase`, the next `predict` tick can fire a redundant RPC for the same
class. This is harmless if idempotent but can restart an animation.

## `n_stable_ticks` - debounce flicker

On a noisy signal the predicted class flickers between ticks. For ~100-200 ms
after a gesture, the sliding window still holds data from the preceding class,
so `argmax` can oscillate between classes. With
the default `n_stable_ticks=1` every flip is a "change", so the callback re-fires
on each one and a robot hand visibly jumps between poses before settling.

Pass `n_stable_ticks=N` to require a value to hold for N consecutive ticks
before it fires, swallowing sub-`N` flicker:

```python
trigger = EdgeTrigger(send_gesture_to_device, n_stable_ticks=5)
```

`n_stable_ticks` counts calls, not elapsed time. Convert a duration to a call count using
the loop rate, including when you change `predict_hz`.

```python
import math

STABLE_SECONDS = 0.1
trigger = EdgeTrigger(
    send_gesture_to_device,
    n_stable_ticks=max(1, math.ceil(STABLE_SECONDS * pipeline.predict_hz)),
)
```

`rebase()` discards any half-formed candidate, so a manual command can't be
overridden by a flicker that was mid-count.

## Generic over `T`

`EdgeTrigger[T]` accepts any value type that supports `==`, including string
class names, integer class indices, tuples and named-tuples.

```python
trigger: EdgeTrigger[int] = EdgeTrigger(_on_class_change)
trigger.fire_if_changed(2)
```

Use a tuple to gate on multiple fields at once. For example, fire only
when the predicted class or the dominant DOF changes:

```python
trigger: EdgeTrigger[tuple[str, str]] = EdgeTrigger(_on_state_change)
trigger.fire_if_changed((class_name, dominant_dof))
```

## Thread-safety

Use one writer for `fire_if_changed`, typically the predict thread. The UI thread
occasionally calls `rebase()`. The whole
`(last, candidate, count)` state lives in one tuple that's replaced in a single
assignment, so it updates atomically under CPython's GIL and no lock is needed.
A race between the two paths can suppress or fire one extra callback. This is
harmless for RPC deduplication, audio gating and logging.

If your callback itself is not thread-safe, gate it inside the callback,
not here.

## When *not* to use it

* For continuous effects, such as streaming a pose vector, call the effect
  every tick.
* You need *wall-clock* hysteresis independent of the tick rate.
  `n_stable_ticks` counts calls, even when its count was derived from seconds; add a
  `time.monotonic()` gate inside your callback.

## See also

* [Controls](controls.md#continuous-and-discrete-are-different-things) - the reference
  use case. A discrete DOF is delivered as an edge, gated by `debounce_s`, and commanded
  over the device's own channel when it changes.
* [`myogestic.outputs.edge_trigger.EdgeTrigger`](../api/core.md) - full API reference.
