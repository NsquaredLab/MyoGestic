---
title: "Run headless (no GUI)"
---
[`App.run(mode="headless")`][myogestic.App.run] starts acquisition, predict and output threads without Dear ImGui. Use it for unattended recordings, remote experiments or integration tests.

Drive recording from a script-level main, a thread or an `app.before_run_hooks` hook. Headless mode skips `@app.ui`.

## A minimum unattended recorder

Records 60 seconds from one stream and packs the session into a `.mg.zip`:

```python
import os
import signal
import threading
import time

from myogestic import App, Stream
from myogestic.sources import LSLSource

app = App("Unattended recorder")
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=1000))
if not app.ctx.streams["emg"].reconnect():
    raise RuntimeError(app.ctx.streams["emg"].last_error)


def run_recording():
    time.sleep(2)  # let streams warm up
    app.start_recording(base_path="data")
    time.sleep(60)  # 60 s of data
    app.stop_recording(wait=True)  # finalise inline before exiting
    # Tell the headless run loop to exit. It blocks on a `while True: sleep`
    # until KeyboardInterrupt - sending SIGINT to ourselves triggers exactly
    # that, and the framework's cleanup hooks fire as normal.
    os.kill(os.getpid(), signal.SIGINT)


threading.Thread(target=run_recording, daemon=True).start()
app.run(mode="headless")
```

Save it as `scripts/unattended.py`, then run `uv run python scripts/unattended.py` with an `EMG` outlet running. After the warm-up and 60 s capture, the session lands in `data/recordings/<YYYYMMDD-HHMM>.mg.zip` and the script exits.

!!! note "Why SIGINT, not a stop event"
    [`App.run(mode="headless")`][myogestic.App.run] blocks on a simple
    `while True: time.sleep(0.1)` loop that only exits on
    `KeyboardInterrupt`. There's no public stop-event to set. Sending
    `SIGINT` to the current process from the worker thread is the cleanest
    way to wake the loop and let cleanup hooks run.

## A timed multi-trial recorder

Run several trials in sequence with an explicit protocol. Useful for IRB-approved studies where the protocol is fixed.

```python
import os
import signal
import threading
import time
from datetime import datetime

from myogestic import App, Stream
from myogestic.sources import LSLSource

app = App("Protocol runner")
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=1000))
if not app.ctx.streams["emg"].reconnect():
    raise RuntimeError(app.ctx.streams["emg"].last_error)
CLASSES = ["Rest", "Fist", "Open"]
app.ctx.class_names = CLASSES

PROTOCOL = [
    ("Rest", 10),
    ("Fist", 10),
    ("Rest", 5),
    ("Fist", 10),
    ("Rest", 5),
    ("Open", 10),
    ("Rest", 10),
]


def run_protocol():
    time.sleep(2)
    print(f"[{datetime.now():%H:%M:%S}] Starting recording")
    app.start_recording()
    for class_name, duration in PROTOCOL:
        cls_idx = CLASSES.index(class_name)
        app.ctx.session.add_label(cls_idx)  # write label event NOW
        print(f"[{datetime.now():%H:%M:%S}] {class_name} for {duration}s")
        time.sleep(duration)
    app.stop_recording(wait=True)
    print("Done. Session in data/recordings/.")
    os.kill(os.getpid(), signal.SIGINT)  # wake the run loop


threading.Thread(target=run_protocol, daemon=True).start()
app.run(mode="headless")
```

The protocol thread writes [`LabelEvent`][myogestic.session.LabelEvent]s directly to the session via `app.ctx.session.add_label(class_idx)`. [`RecordingControls`][myogestic.widgets.RecordingControls] does the same in GUI mode. The label track is a list of timestamped events.

## A signal-handled, graceful-exit recorder

For long-running services (e.g. a ROS launch file or a systemd unit), handle `SIGTERM` so `Ctrl+C` or `systemctl stop` packs the session before exiting:

```python
import signal
import threading
import time

from myogestic import App, Stream
from myogestic.sources import LSLSource

app = App("Service")
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=1000))

def shutdown(signum, frame):
    print(f"Got signal {signum}, stopping.")
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)


def supervisor():
    time.sleep(2)  # let the connected stream warm up
    app.start_recording()


if not app.ctx.streams["emg"].reconnect():
    raise RuntimeError(app.ctx.streams["emg"].last_error)
threading.Thread(target=supervisor, daemon=True).start()
app.run(mode="headless")
```

The signal raises `KeyboardInterrupt` on the main thread. The headless loop returns,
then [`App.run`][myogestic.App.run] runs cleanup hooks and finalizes an open take inline.

## Predicting headless

Load a pre-trained model in a headless [`Pipeline`][myogestic.ml.Pipeline] and let the predict thread drive an output:

```python
import numpy as np

from myogestic import App, Stream
from myogestic.ml import Pipeline, load_pickle
from myogestic.outputs import LSLOutlet
from myogestic.sources import LSLSource

app = App("Headless predictor")
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=200))
if not app.ctx.streams["emg"].reconnect():
    raise RuntimeError(app.ctx.streams["emg"].last_error)
out = LSLOutlet("Predictions", n_channels=1, hz=20)

pipeline = Pipeline(app, predict_hz=20)
pipeline.model = load_pickle("models/my_model.pkl")


@pipeline.extract
def extract(windows):
    return windows["emg"].mean(axis=1)


@pipeline.predict
def predict(model, features):
    cls = int(model.predict(features.reshape(1, -1))[0])
    out.push(np.array([float(cls)], dtype=np.float32))
    return {"class": cls}


# Skip the train decorator; we loaded a model, not training one.
pipeline.start_predicting()
app.cleanup_hooks.append(lambda _app: out.stop())
app.run(mode="headless")
```

Useful when you want a pre-trained model to publish telemetry to a downstream LSL consumer with no operator at the desktop. To drive a robot, use a [target](add-a-target.md).

## Common mistakes

See [Troubleshooting](../troubleshooting.md) for errors by symptom.

- No streams connected. `app.start_recording()` checks `Stream.info` to decide what to record. Call `Stream.reconnect()` and check its result before recording; a sleep alone never connects a stream.
- Calling `app.start_recording()` from before `app.run()`. The streams' acquisition threads start inside `app.run`. Call recording from a thread that's launched *before* `app.run` but does its work after a small sleep, or from a `before_run_hook`.
- Exiting before `.mg.zip` finalizes. Use `app.stop_recording(wait=True)` to finish inline. Normal `App.run` cleanup also finalizes an open take and waits up to 30 seconds for earlier saves; `os._exit` bypasses that cleanup.
- Using `time.sleep` inside `@pipeline.predict`. Same as in GUI mode - it blocks the predict thread. The framework already paces ticks at `predict_hz`.

See also: [Record and replay](record-and-replay.md), [Recording concept page](../concepts/recording.md).
