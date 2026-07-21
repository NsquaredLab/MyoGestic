# Enable on-disk recording

Capture every registered `Stream`'s incoming biosignal data to a Zarr-backed `.session.zip` archive. Two flows (GUI button or headless API), one artifact, full programmatic control. This page covers configuration, the full lifecycle, the Zarr layout, the `Session` API, and read-back.

## Quick-start: the four lines that enable recording

```python
from myogestic import App, Stream
from myogestic.sources import LSLSource
from myogestic.widgets import RecordingControls

app = App("My recording")                                              # 1. construct App
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=1000))  # 2. register stream(s)

recording = RecordingControls(["Rest", "Fist"],
                              on_record=app.start_recording,             # 3. wire Record button
                              on_stop=app.stop_recording)                # 4. wire Stop button

@app.ui
def ui(ctx):
    recording.ui(ctx)

app.run()
```

Click **Record** → data flows into `sessions/<timestamp>/`. Click **Stop** → that folder packs into `sessions/<timestamp>.session.zip`. No further setup required.

## Lifecycle in detail

```
       ┌──────────────────────────────────────────────────────┐
       │                                                      │
       │   App.run()                                          │
       │     ├─ stream.start()    ── acquisition threads spin │
       │     └─ enter GUI loop                                │
       │                                                      │
       │   ┌─ user clicks Record ────────────────────────┐   │
       │   │ app.start_recording(base_path="sessions")   │   │
       │   │   ├─ ctx.state = "recording"                │   │
       │   │   ├─ ctx.session = Session(base_path)       │   │
       │   │   ├─ Session.init_stream(name, info)        │   │
       │   │   │    creates <stream>.zarr and            │   │
       │   │   │    <stream>_timestamps.zarr             │   │
       │   │   └─ acquisition threads now append to Zarr │   │
       │   │                                              │   │
       │   │ user clicks gesture buttons                  │   │
       │   │   recording_controls adds                    │   │
       │   │   ctx.session.add_label(class_idx,           │   │
       │   │                  timestamp=local_clock())    │   │
       │   │                                              │   │
       │   │ user clicks Stop                             │   │
       │   │ app.stop_recording()                         │   │
       │   │   ├─ Session.save_meta(class_names=...)      │   │
       │   │   ├─ writes meta.json + labels.json          │   │
       │   │   ├─ Session.pack_to_zip()  (daemon thread)  │   │
       │   │   │    -> <timestamp>.session.zip            │   │
       │   │   │    folder removed once pack succeeds     │   │
       │   │   └─ ctx.state = "idle"                      │   │
       │   └────────────────────────────────────────────────┘ │
       │                                                      │
       └──────────────────────────────────────────────────────┘
```

## The artifact

```
sessions/
└── 2026-05-17_14-23-05.session.zip       # final packaged artifact
                                          # (after Stop completes)
```

Inside the zip:

```
2026-05-17_14-23-05/
├── emg.zarr/                       # shape (n_samples, n_channels), dtype = stream dtype
│   └── chunks: (fs, n_channels)    # 1 second per chunk
├── emg_timestamps.zarr/            # shape (n_samples,) float64 LSL clock seconds
│   └── chunks: (fs,)
├── vhi_control.zarr/               # one pair of arrays per registered Stream
├── vhi_control_timestamps.zarr/
├── meta.json                       # app_name, created, streams (n_channels, fs, dtype), class_names
└── labels.json                     # list of {timestamp, class_index}
```

While recording is in progress and before `stop_recording()` completes, the same content lives as an unpacked folder `sessions/2026-05-17_14-23-05/`. The folder is deleted only after the zip is verified.

## Zarr configuration (what defaults you get)

Recording uses [Zarr v3](https://zarr.readthedocs.io/) with these defaults, applied per registered Stream:

| Setting | Value | Why |
|---------|-------|-----|
| Sample array shape | `(n_samples, n_channels)` | sample-major, append-only |
| Sample array chunk | `(int(fs), n_channels)` | one second of data per chunk |
| Sample array dtype | the Stream's `StreamInfo.dtype` (typically `float32`) | matches what the source produced |
| Timestamp array shape | `(n_samples,)` | parallel to sample array |
| Timestamp array chunk | `(int(fs),)` | one second per chunk |
| Timestamp array dtype | `float64` | LSL clock seconds |
| Outer zip compression | `ZIP_STORED` (none) | Zarr chunks already compress internally |

You don't configure these per recording; they're computed automatically from each `Stream`'s `StreamInfo`. Override the storage **location** via `base_path`; override the **codec** by installing the `[zarrs]` extra (Rust-accelerated):

```bash
uv sync --extra zarrs    # transparent speedup; no code change needed
```

With `zarrs` installed, MyoGestic registers `zarrs.ZarrsCodecPipeline` at import time; large sessions write and read meaningfully faster. Without it, plain Python Zarr is used.

## Headless flow (no GUI)

For unattended capture, drive the same API from a plain script. Use `mode="headless"` so `app.run()` doesn't try to open a window:

```python
import threading
import time
from myogestic import App, Stream
from myogestic.sources import LSLSource

app = App("Headless capture")
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=1000))


def _capture(app):
    # Run on a background thread so app.run()'s main loop can spin
    # the acquisition threads while we sleep here.
    def _run():
        time.sleep(2)                              # let buffers warm up
        app.start_recording("sessions")
        app.ctx.session.add_label(0)               # initial class index
        for class_idx in (1, 0, 1, 0):             # cycle Fist <-> Rest
            time.sleep(5)
            app.ctx.session.add_label(class_idx)
        time.sleep(5)
        app.stop_recording()
        # Wait for the pack thread to finish before exiting.
        time.sleep(2)
        import os; os._exit(0)
    threading.Thread(target=_run, daemon=True).start()


app.before_run_hooks.append(_capture)
app.run(mode="headless")
```

The artifact lands at `sessions/<timestamp>.session.zip` just as in the GUI flow.

## Custom GUI integration

For non-default UX (custom Record button placement, conditional triggers, multi-step protocols), call the API directly instead of using `RecordingControls`:

```python
from imgui_bundle import imgui
from mne_lsl.lsl import local_clock

@app.ui
def ui(ctx):
    if ctx.state == "idle":
        if imgui.button("Start trial"):
            app.start_recording(base_path="experiments/trial5")
            # Optional: stamp an initial label so first samples are
            # labeled before any user input.
            app.ctx.session.add_label(class_index=0, timestamp=local_clock())
    elif ctx.state == "recording":
        imgui.text(f"Recording: {app.ctx.session.path}")
        if imgui.button("Stop trial"):
            app.stop_recording()
```

## The `Session` API surface

When `ctx.state == "recording"`, `app.ctx.session` is a live [`Session`](../api/session.md) instance you can poke at directly:

| Method                                                | Purpose                                                                  |
|-------------------------------------------------------|--------------------------------------------------------------------------|
| `Session(base_path="sessions")`                       | Constructor (called by `start_recording`; you rarely need it directly).  |
| `session.path`                                        | `Path` to the session folder being written.                              |
| `session.stores[name]`                                | The live `zarr.Array` for stream `name` (sample data, append-only).      |
| `session.ts_stores[name]`                             | Parallel timestamp `zarr.Array` for stream `name`.                       |
| `session.label_track`                                 | `list[LabelEvent]` of all labels added so far.                           |
| `session.add_label(class_index, timestamp=None)`      | Append one label. `timestamp` defaults to `local_clock()`.               |
| `session.init_stream(name, info)`                    | Pre-allocate Zarr arrays for one stream (auto-called by `start_recording`). |
| `session.append(name, data, timestamps)`              | Append a chunk (auto-called by the acquisition thread).                  |
| `session.save_meta(app_name, class_names=None)`       | Write `meta.json` and `labels.json` (auto-called by `stop_recording`).   |
| `session.pack_to_zip()`                               | Pack folder into `.session.zip` (auto-called on a daemon thread after stop). |

You typically only call `add_label` directly; everything else is wired by `start_recording` / `stop_recording`. The class is documented at [`myogestic.session.Session`](../api/session.md).

## Reading sessions back

```python
from myogestic.session import open_session_store

# Works for both packed zips AND unpacked folders.
sess = open_session_store("sessions/2026-05-17_14-23-05.session.zip")

emg     = sess.stores["emg"]            # zarr.Array, shape (n_samples, n_channels)
emg_ts  = sess.ts_stores["emg"]         # zarr.Array, shape (n_samples,) float64
labels  = sess.label_track              # list[LabelEvent]
info    = sess.stream_info("emg")       # StreamInfo(fs, n_channels, dtype)
```

For windowed training iteration, use the helpers in `myogestic.session`:

```python
from myogestic.session import iter_labeled_windows, iter_aligned_windows

# Classification: one (window, ts, class_index) per hop step.
for window, ts, cls in iter_labeled_windows(
    [sess.path], stream_name="emg",
    window_ms=200, hop_ms=100,
    classes={0, 1},
):
    ...

# Regression: align a primary stream with one or more aligned streams.
for window, aligned, ts in iter_aligned_windows(
    [sess.path], primary_stream_name="emg",
    aligned_stream_names=["vhi_control"],
    window_ms=200, hop_ms=50,
):
    target = aligned["vhi_control"]
    ...
```

These skip windows that straddle a label boundary and handle the window/hop math for you. See [Record and replay](record-and-replay.md) and the [Recording concept page](../concepts/recording.md).

## Common pitfalls

- **Calling `start_recording` before streams connect.** A `Stream` whose `info is None` is silently skipped (no Zarr schema yet). Either wait for `app.ctx.streams["emg"].info is not None` or trigger recording from a `before_run_hook` plus a short sleep, as in the headless example.
- **Recording with the synthetic generator paused.** The generator only produces data while it's running. Click Launch in the `ProcessLauncher` panel before Record, or in headless flow start the generator subprocess before `app.run()`.
- **Killing the process mid-recording.** The `.session.zip` is packed only at `stop_recording()`. Crashes leave the raw `sessions/<timestamp>/` folder; you can pack it later with `Session(base_path=...).pack_to_zip()` after re-attaching to it, or just load the folder directly with `open_session_store("sessions/<timestamp>/")` - both work.
- **Forgetting `class_names` in `save_meta`**. `RecordingControls` passes them through automatically. If you call `add_label` directly from custom code, also call `app.ctx.session.save_meta(app_name="...", class_names=[...])` before `stop_recording` or your labels will only be integers in `labels.json` with no name lookup.

## See also

- [Recording concept page](../concepts/recording.md) - the runtime model + label-track design.
- [Record and replay](record-and-replay.md) - feeding a recorded session back into a `ReplaySource` for offline debugging.
- [`myogestic.App.start_recording` / `stop_recording`](../api/core.md) - full API reference for the lifecycle methods.
- [`myogestic.session.Session`](../api/session.md) - full `Session` class reference.
- [`myogestic.session.open_session_store`](../api/session.md) - load packed or unpacked sessions.
- [`myogestic.session.iter_labeled_windows`, `iter_aligned_windows`](../api/session.md) - training-window iterators.
