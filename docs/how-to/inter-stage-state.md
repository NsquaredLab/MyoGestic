# Keep state between pipeline stages

`@pipeline.extract` and `@pipeline.predict` are plain functions called once per predict tick (`1 / predict_hz` seconds). They get no implicit context object - if you need data to *survive* between ticks, you store it yourself. This page covers the four patterns that come up.

## The base case: stateless tick

```python
@pipeline.extract
def extract(windows):
    return rms(windows["emg"])   # returns a fresh feature vector each tick

@pipeline.predict
def predict(model, features):
    return {"class": int(model.predict(features.reshape(1, -1))[0])}
```

No state to keep. The pipeline calls `extract` then `predict`, the dict goes into `pipeline.predictions`, the next tick starts fresh.

## Pattern 1: module-level mutable state

For anything that needs to persist across ticks, put it at module scope and mutate from inside the callback. Both threads (predict + render) see the same object, and CPython's GIL guarantees scalar / reference assignment is atomic - no lock needed for simple cases.

```python
import numpy as np

# Persists across predict ticks because it's module-level.
prediction_count = 0
last_predicted_class: int | None = None

@pipeline.predict
def predict(model, features):
    global prediction_count, last_predicted_class
    pred = int(model.predict(features.reshape(1, -1))[0])
    prediction_count += 1
    last_predicted_class = pred
    return {"class": pred, "tick": prediction_count}
```

The render thread can read `prediction_count` directly to display "1234 predictions made" - no synchronization needed for an int.

## Pattern 2: rolling-window deque for feature smoothing

When a single window isn't enough context - e.g. you want the RMS averaged over the last 5 ticks - keep a `deque` at module scope and append per tick:

```python
from collections import deque
import numpy as np

# Last 5 RMS vectors; older entries auto-evict.
recent_rms: deque[np.ndarray] = deque(maxlen=5)

@pipeline.extract
def extract(windows):
    rms_now = np.sqrt(np.mean(windows["emg"] ** 2, axis=1))
    recent_rms.append(rms_now)
    # Mean of however many we have so far (1..5).
    return np.mean(np.stack(recent_rms), axis=0).astype(np.float32)
```

The deque is owned by the predict thread (only `extract` writes), so no lock is needed.

For state that *spans extract and predict on the same tick*, return it from `extract` - `predict` receives the same object back:

```python
@pipeline.extract
def extract(windows):
    rms_now = np.sqrt(np.mean(windows["emg"] ** 2, axis=1))
    recent_rms.append(rms_now)
    # Return both the smoothed feature AND raw - predict sees both.
    smooth = np.mean(np.stack(recent_rms), axis=0).astype(np.float32)
    return {"smooth": smooth, "raw": rms_now}

@pipeline.predict
def predict(model, features):
    pred = int(model.predict(features["smooth"].reshape(1, -1))[0])
    return {"class": pred, "raw_rms": features["raw"]}
```

`features` can be any shape - tuple, dict, dataclass, whatever pickleable-or-not thing your model wants. The framework just passes it through.

## Pattern 3: stateful model objects

The `model` argument to `@pipeline.predict` is whatever object `@pipeline.train` returned. If that object has internal state - a Kalman filter, an HMM, a sequence model that wants its own RNN state - it persists across ticks because the same `model` reference is used every call.

```python
class StatefulClassifier:
    def __init__(self):
        self._prev_logits = None

    def step(self, features):
        logits = self._raw_predict(features)
        if self._prev_logits is not None:
            # Exponential smoothing across ticks.
            logits = 0.7 * logits + 0.3 * self._prev_logits
        self._prev_logits = logits
        return int(np.argmax(logits))

@pipeline.train
def train(_data):
    return StatefulClassifier()   # state lives here

@pipeline.predict
def predict(model, features):
    return {"class": model.step(features)}
```

A retrain replaces the model object (and its state). If you need state that *survives* retraining, use Pattern 1 (module-level) instead.

## Pattern 4: gating side-effects on state changes

You often want a side-effect (RPC, audio cue, serial write) to fire only when the prediction *changes*, not every tick. [`EdgeTrigger`](../concepts/edge-trigger.md) is the one-liner:

```python
from myogestic.outputs import EdgeTrigger

trigger = EdgeTrigger(callback=vhi_client.set_movement)

@pipeline.predict
def predict(model, features):
    class_idx = int(model.predict(features.reshape(1, -1))[0])
    name = CLASSES[class_idx]
    trigger.fire_if_changed(name)    # only fires on the rising edge of a change
    return {"class": class_idx}
```

`fire_if_changed` returns `True` when the callback ran, `False` when suppressed - useful for paired effects (e.g. log only when the gesture actually changed).

See [Edge trigger](../concepts/edge-trigger.md) for `rebase()`, thread-safety, and the deeper "why".

## Detecting stale ticks (predict thread faster than acquisition)

The predict thread wakes every `1/predict_hz`. The acquisition thread may not have new data on any given tick. Pass the latest timestamp through and let the model decide:

```python
@pipeline.extract
def extract(windows):
    emg, ts = ctx.streams["emg"].get_window()   # framework helper
    last_ts = float(ts[-1]) if ts.size > 0 else None
    return (emg, last_ts)

@pipeline.predict
def predict(model, features):
    emg, last_ts = features
    return model.step(emg, last_ts=last_ts)     # model returns prev pred on stale
```

The model's `step()` checks `last_ts` against its own stored last value and returns the previous prediction unchanged when the timestamp hasn't advanced.

## Thread-safety quick reference

| Storage                              | Safe without a lock?   |
|--------------------------------------|------------------------|
| Module-level scalar (int / str / bool / ref) | Yes (GIL atomic) |
| Module-level `deque` written from one thread only | Yes |
| Module-level `dict` mutated from one thread only | Yes |
| Module-level container written from BOTH predict thread AND render thread | Use a `threading.Lock` or refactor to single-writer |
| Stateful model object internal fields | Yes (predict thread is the only writer) |

The render thread (running `@app.ui` at 60 fps) reads from these - reads are always safe. Writes from the render thread (e.g. a button click that updates a setting) into an object the predict thread reads need atomicity or a lock; for simple flags use scalar assignment (atomic), for richer state use `threading.Lock`.

## See also

- [Pipeline concept page](../concepts/pipeline.md) - lifecycle, state transitions, GPU contention rule.
- [Threading concept page](../concepts/threading.md) - the four threads (acquire / predict / render / output) and how they share data.
- [Edge trigger](../concepts/edge-trigger.md) - the fire-on-change pattern in depth.
