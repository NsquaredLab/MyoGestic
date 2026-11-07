---
title: "Keep state between pipeline stages"
---
`@pipeline.extract` and `@pipeline.predict` are plain functions called on predict ticks with available input. The target interval is `1 / predict_hz` seconds. The callbacks receive no implicit context object. Store persistent state explicitly using one of the four patterns below.

## Stateless ticks

```python
@pipeline.extract
def extract(windows):
    return rms(windows["emg"])  # returns a fresh feature vector each tick


@pipeline.predict
def predict(model, features):
    return {"class": int(model.predict(features.reshape(1, -1))[0])}
```

No state to keep. The pipeline calls `extract` then `predict`, the dict goes into `pipeline.predictions`, the next tick starts fresh.

## Pattern 1: module-level mutable state

For anything that needs to persist across ticks, put it at module scope and mutate from inside the callback. The predict and render threads share the object. CPython's GIL makes scalar and reference assignment atomic, so simple assignments need no lock.

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

The render thread can read `prediction_count` directly to display "1234 predictions made" without synchronization.

## Pattern 2: rolling-window deque for feature smoothing

To average RMS over the last 5 ticks, keep a `deque` at module scope and append each tick:

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

`features` can be any object your model accepts, including a tuple, dict or dataclass. It need not be pickleable. The framework passes it through.

## Pattern 3: stateful model objects

The `model` argument to `@pipeline.predict` is whatever object `@pipeline.train` returned. The same `model` reference is used on every call, preserving internal state for Kalman filters, HMMs and RNNs.

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
    return StatefulClassifier()  # state lives here


@pipeline.predict
def predict(model, features):
    return {"class": model.step(features)}
```

A retrain replaces the model object (and its state). If you need state that *survives* retraining, use Pattern 1 (module-level) instead.

## Pattern 4: gating side-effects on state changes

Use [`EdgeTrigger`](../concepts/edge-trigger.md) to run an RPC, audio cue or serial write only when the prediction changes. Unchanged ticks do not fire the effect.

```python
from myogestic.outputs import EdgeTrigger

trigger = EdgeTrigger(callback=send_gesture_to_device)


@pipeline.predict
def predict(model, features):
    class_idx = int(model.predict(features.reshape(1, -1))[0])
    name = CLASSES[class_idx]
    trigger.fire_if_changed(name)  # only fires on the rising edge of a change
    return {"class": class_idx}
```

`fire_if_changed` returns `True` when the callback ran and `False` when suppressed. Use it to pair effects, such as logging a gesture change.

See [Edge trigger](../concepts/edge-trigger.md) for `rebase()`, thread safety and the reasons for change-gated side effects.

## Detect stale ticks

The predict thread wakes every `1/predict_hz`. The acquisition thread may not have new data on any given tick. Pass the latest timestamp through and let the model decide:

```python
@pipeline.extract
def extract(windows):
    emg, ts = pipeline.app.ctx.streams["emg"].get_window()
    last_ts = float(ts[-1]) if ts.size > 0 else None
    return (emg, last_ts)


@pipeline.predict
def predict(model, features):
    emg, last_ts = features
    return model.step(emg, last_ts=last_ts)  # model returns prev pred on stale
```

The model's `step()` checks `last_ts` against its own stored last value and returns the previous prediction unchanged when the timestamp hasn't advanced.

## Thread-safety quick reference

| Storage                              | Safe without a lock?   |
|--------------------------------------|------------------------|
| Module-level scalar (int / str / bool / ref) | Yes (GIL atomic) |
| Module-level `deque` written from one thread only | Keep iteration on that thread, or lock |
| Module-level `dict` mutated from one thread only | Individual lookups; lock iteration during mutation |
| Module-level container written from BOTH predict thread AND render thread | Use a `threading.Lock` or refactor to single-writer |
| Stateful model object internal fields | Yes (predict thread is the only writer) |

The render thread can read scalar references directly. Iterating a `dict` or `deque`
while another thread mutates it can raise; copy the needed state under a shared lock.
Writes from the render thread into richer state read by prediction also need a lock.

## See also

- [Pipeline concept page](../concepts/pipeline.md) - lifecycle, state transitions, GPU contention rule.
- [Threading concept page](../concepts/threading.md) - the four threads (acquire / predict / render / output) and how they share data.
- [Edge trigger](../concepts/edge-trigger.md) - the fire-on-change pattern in depth.
