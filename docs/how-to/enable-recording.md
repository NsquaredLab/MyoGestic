# Enable on-disk recording

You want to capture incoming biosignal data to a `.session.zip` file. Two ways: through the GUI (one widget + two callbacks) or headless (direct API calls). Both produce the same artifact.

## The artifact

When you call `app.start_recording("sessions")` and later `app.stop_recording()`, the framework writes a session folder and then packs it into a portable archive:

```
sessions/
└── 2026-05-17_14-23-05/
    ├── emg.zarr/                    # shape (n_samples, n_channels), dtype matches your stream
    ├── emg_timestamps.zarr/         # shape (n_samples,) float64 LSL clock
    ├── vhi_control.zarr/            # one pair of arrays per registered Stream
    ├── vhi_control_timestamps.zarr/
    ├── meta.json                    # streams_info, app_name, class_names
    └── labels.json                  # the LabelEvent track
```

After `stop_recording()` a daemon thread packs the folder into `2026-05-17_14-23-05.session.zip` (the folder is kept until the pack succeeds, then deleted). The zip is self-contained - you can read it back with `myogestic.session.open_session_store` regardless of whether the source folder still exists.

## GUI flow (recommended)

Drop the `recording_controls` widget into `@app.ui`. The Record / Stop buttons start and stop the session:

```python
from myogestic import App, Stream
from myogestic.sources import LSLSource
from myogestic.widgets import recording_controls, signal_viewer

CLASSES = ["Rest", "Fist", "Open"]

app = App("My recording")
app.streams(Stream("emg", source=LSLSource("EMG"), window_seconds=1.0))


@app.ui
def ui(ctx):
    signal_viewer(ctx, "emg")
    recording_controls(
        ctx, CLASSES,
        on_record=app.start_recording,  # called when Record is clicked
        on_stop=app.stop_recording,     # called when Stop is clicked
    )


app.run()
```

That's the minimum. The class buttons next to Record (one per `CLASSES` entry) write `LabelEvent`s onto the active session's label track on click. The framework appends every Stream's data to its Zarr arrays while `ctx.state == "recording"`.

To override the base path or per-recording callbacks:

```python
def _start():
    app.start_recording(base_path="experiments/run3/sessions")

def _stop():
    app.stop_recording()
    print(f"Wrote {app.ctx.session.path}")

recording_controls(
    ctx, CLASSES,
    on_record=_start,
    on_stop=_stop,
    on_gesture=lambda i: my_synthetic_generator.set_class(i),
)
```

## Headless flow (no GUI)

For unattended captures, drive the same API from a plain script. Set `mode="headless"` so `app.run()` doesn't try to open a window:

```python
import time
from myogestic import App, Stream
from myogestic.sources import LSLSource

app = App("Headless capture")
app.streams(Stream("emg", source=LSLSource("EMG"), window_seconds=1.0))

# Schedule a fixed-duration recording via a before_run hook so the
# Stream's acquisition thread is already running by the time we start.
import threading

def _capture(app):
    def _run():
        time.sleep(2)                              # let buffers warm up
        app.start_recording("sessions")
        app.ctx.session.add_label(0)               # initial class index
        time.sleep(30)                             # record 30 s
        app.stop_recording()
        app.ctx.app_shall_exit = True              # break out of headless loop
    threading.Thread(target=_run, daemon=True).start()

app.before_run_hooks.append(_capture)
app.run(mode="headless")
```

Same artifact lands in `sessions/<timestamp>.session.zip`.

## Adding labels mid-session

`recording_controls` adds labels for you when the user clicks a class button. To label from code (custom UI, headless, programmatic experiment driver):

```python
from mne_lsl.lsl import local_clock

app.ctx.session.add_label(class_index=1, timestamp=local_clock())
```

`timestamp` defaults to `local_clock()` if omitted. Negative `class_index` is the unlabeled sentinel.

## Loading sessions back

```python
from myogestic.session import open_session_store

sess = open_session_store("sessions/2026-05-17_14-23-05.session.zip")
emg = sess.stores["emg"]                  # zarr.Array, shape (n_samples, n_channels)
ts  = sess.ts_stores["emg"]               # zarr.Array, shape (n_samples,)
labels = sess.label_track                 # list[LabelEvent]
```

For windowed training iteration, prefer the helpers in `myogestic.session` (`iter_labeled_windows`, `iter_aligned_windows`) - they handle the window/hop math and skip windows that straddle a label boundary. See [Record and replay](record-and-replay.md) and the [Recording concept page](../concepts/recording.md).

## Common pitfalls

- **Calling `start_recording` before streams connect.** A Stream whose `info is None` is silently skipped (no Zarr schema yet). Either wait for `app.ctx.streams["emg"].info is not None` or do recording from a `before_run` hook plus a short sleep, as in the headless example.
- **Recording with the synthetic generator paused.** The generator only produces data while it's running. Click Launch in the `process_launcher` panel before Record, or in headless flow start the generator subprocess before `app.run()`.
- **Forgetting `app.stop_recording()`.** The `.session.zip` is only packed at stop. Killing the process mid-recording leaves the raw `sessions/<timestamp>/` folder; you can pack it later with `myogestic._session_core.pack_to_zip(folder_path)` or load the folder directly with `open_session_store(folder_path)`.

## See also

- [Recording concept page](../concepts/recording.md) - the runtime model + label-track design.
- [Record and replay](record-and-replay.md) - feeding a recorded session back into a `ReplaySource` for offline debugging.
- [`myogestic.App.start_recording` / `stop_recording`](../api/core.md) - full API reference.
