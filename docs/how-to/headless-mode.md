# Run headless (no GUI)

[`App.run(mode="headless")`][myogestic.App.run] starts the same acquisition / predict / output threads as the GUI mode but skips Dear ImGui. Useful for unattended overnight recordings, scripted experiments on remote machines, integration tests, or any case where a window would just be in the way.

In headless mode, **there's no `@app.ui` callback**, so the user can't click Record. You drive the recording state machine yourself - typically from a script-level main, a thread, or an `app.before_run_hooks` hook.

## A minimum unattended recorder

Records 60 seconds from one stream and packs the session into a `.session.zip`:

```python
import os
import signal
import threading
import time

from myogestic import App, Stream
from myogestic.sources import LSLSource

app = App("Unattended recorder")
app.streams(Stream("emg", source=LSLSource("EMG"), window_seconds=1.0))


def run_recording():
    time.sleep(2)  # let streams warm up
    app.start_recording(base_path="sessions")
    time.sleep(60)  # 60 s of data
    app.stop_recording()
    time.sleep(2)  # let .session.zip finalise
    # Tell the headless run loop to exit. It blocks on a `while True: sleep`
    # until KeyboardInterrupt - sending SIGINT to ourselves triggers exactly
    # that, and the framework's cleanup hooks fire as normal.
    os.kill(os.getpid(), signal.SIGINT)


threading.Thread(target=run_recording, daemon=True).start()
app.run(mode="headless")
```

Run it: `uv run python scripts/unattended.py`. After 60 s the session lands in `sessions/<timestamp>.session.zip` and the script exits.

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
app.streams(Stream("emg", source=LSLSource("EMG"), window_seconds=1.0))

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
    if app.ctx.session is None:
        print("No streams connected; aborting.")
        os.kill(os.getpid(), signal.SIGINT)
        return
    for class_name, duration in PROTOCOL:
        cls_idx = ["Rest", "Fist", "Open"].index(class_name)
        app.ctx.session.add_label(cls_idx)  # write label event NOW
        print(f"[{datetime.now():%H:%M:%S}] {class_name} for {duration}s")
        time.sleep(duration)
    app.stop_recording()
    print("Done. Session in sessions/.")
    time.sleep(2)
    os.kill(os.getpid(), signal.SIGINT)  # wake the run loop


threading.Thread(target=run_protocol, daemon=True).start()
app.run(mode="headless")
```

The protocol thread writes [`LabelEvent`][myogestic.session.LabelEvent]s directly to the session via `app.ctx.session.add_label(class_idx)`. That's exactly what the [`recording_controls`][myogestic.widgets.recording_controls] widget does in GUI mode - the label track is just a list of timestamped events.

## A signal-handled, graceful-exit recorder

For long-running services (e.g. a ROS launch file or a systemd unit), handle `SIGTERM` so `Ctrl+C` or `systemctl stop` packs the session before exiting:

```python
import signal
import threading
import time

from myogestic import App, Stream
from myogestic.sources import LSLSource

app = App("Service")
app.streams(Stream("emg", source=LSLSource("EMG"), window_seconds=1.0))

stop = threading.Event()


def shutdown(signum, frame):
    print(f"Got signal {signum}, stopping.")
    stop.set()


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)


def supervisor():
    time.sleep(2)
    app.start_recording()
    stop.wait()  # block until SIGTERM
    app.stop_recording()
    time.sleep(2)
    import os

    os._exit(0)  # exit the run loop hard


threading.Thread(target=supervisor, daemon=True).start()
app.run(mode="headless")
```

The `os._exit(0)` is a hammer; if your run loop already supports clean shutdown via a stop event, prefer that. The framework's [`App.run`][myogestic.App.run] cleanup hooks fire either way.

## Predicting headless

You can run a [`Pipeline`][myogestic.ml.Pipeline] in headless too - load a pre-trained model and let the predict thread drive an output:

```python
from myogestic import App, Stream
from myogestic.ml import Pipeline, load_pickle
from myogestic.outputs import LSLOutlet
from myogestic.sources import LSLSource

app = App("Headless predictor")
app.streams(Stream("emg", source=LSLSource("EMG"), window_seconds=0.2))
out = LSLOutlet("Predictions", n_channels=1, hz=20)

pipeline = Pipeline(app, predict_hz=20)
pipeline.model = load_pickle("models/my_model.pkl")


@pipeline.extract
def extract(windows):
    return windows["emg"].mean(axis=1)


@pipeline.predict
def predict(model, features):
    cls = int(model.predict(features.reshape(1, -1))[0])
    out.push([float(cls)])
    return {"class": cls}


# Skip the train decorator; we loaded a model, not training one.
pipeline.start_predicting()
app.run(mode="headless")
```

Useful when you want a pre-trained model to drive a robot or downstream LSL consumer with no operator at the desktop.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **No streams connected.** In headless mode, `app.start_recording()` checks `Stream.info` to decide what to record. If your streams haven't connected yet (the upstream LSL outlet hasn't appeared), recording starts with zero streams. Sleep for 1-2 seconds after `app.run` starts before recording.
- **Calling `app.start_recording()` from before `app.run()`.** The streams' acquisition threads start inside `app.run`. Call recording from a thread that's launched *before* `app.run` but does its work after a small sleep, or from a `before_run_hook`.
- **Forgetting to wait for `.session.zip` to finalise.** `app.stop_recording()` kicks off a daemon thread that packs the folder. If main exits immediately, the zip might not finish. Sleep 1-2 seconds before exiting, or check that `sessions/<timestamp>.session.zip` exists.
- **Using `time.sleep` inside `@pipeline.predict`.** Same as in GUI mode - it blocks the predict thread. The framework already paces ticks at `predict_hz`.

See also: [Record and replay](record-and-replay.md), [Recording concept page](../concepts/recording.md).
