---
title: "Enable on-disk recording"
---
Capture every connected `Stream`'s samples to a Zarr-backed `.mg.zip` archive. Two flows (GUI button or headless API), one artifact, full programmatic control. This page covers configuration, the full lifecycle, the Zarr layout, the `Session` API, and read-back.

## Quick-start: the four lines that enable recording

```python
from myogestic import App, Stream
from myogestic.sources import LSLSource
from myogestic.widgets import RecordingControls

app = App("My recording")  # 1. construct App
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=1000))  # 2. register stream(s)
if not app.ctx.streams["emg"].reconnect():
    raise RuntimeError(app.ctx.streams["emg"].last_error)

recording = RecordingControls(
    ["Rest", "Fist"],
    on_record=app.start_recording,  # 3. wire Record button
    on_stop=app.stop_recording,
)  # 4. wire Stop button


@app.ui
def ui(ctx):
    recording.ui(ctx)


app.run()
```

Click **Record** → data flows into `data/<ID>/recordings/<ID>_<YYYYMMDD-HHMM>/` (or `data/recordings/<YYYYMMDD-HHMM>/` with no participant set). Click **Stop** → that folder packs into `<ID>_<YYYYMMDD-HHMM>_<codes>.mg.zip` beside it, named for the gestures it recorded (`P-014_20260517-1423_R+F.mg.zip`). No further setup required. [File names](../concepts/file-names.md) has the whole standard.

## Just capture, and name it afterwards

`RecordingControls` above is built for *labelled* data: one button per gesture class, each click writing a label event. When you only want to collect a stretch of signal, `RecordButton` is the simpler control — Record, Stop, and a dialog asking what to call the take:

```python
from myogestic.widgets import RecordButton

recorder = RecordButton(
    on_record=app.start_recording,
    on_stop=app.stop_recording,
    on_discard=app.discard_recording,  # optional; omit and the dialog offers no Discard
)
```

**Capture ends the moment you press Stop**, not when you press Save — the streams are detached before the dialog opens, so the seconds spent typing never reach the recording.

The full-width red **Record** button becomes a tinted **Recording** row with a mono elapsed
clock and **Stop**. After stopping, a surface row shows the captured duration; the naming dialog
offers **Name (optional)**, a preview of the resulting file stem, **Save**, and an outlined
**Discard** labelled with the captured duration when a discard handler is supplied. If the app
requires a participant, Record stays disabled with a visible reminder to set their ID first.

The name is written to `meta.json` and appended to the archive filename, so a saved take is `<ID>_<YYYYMMDD-HHMM>[_<codes>][_<name>].mg.zip` beside its original recording folder and appears in `SessionManager` with gesture chips, time, and duration; its tooltip preserves the take name and archive filename. The optional codes segment holds a short code for each class with recorded time, in class-index order, joined with `+` (`Fist` and `Open hand` give `F+Oh`); past 40 characters it becomes the first three codes and a count (`R+F+P+6-more`). The typed name is slugged down to ASCII letters, digits, `-` and `_`. Naming is optional; a take with neither codes nor a name is just `<ID>_<YYYYMMDD-HHMM>.mg.zip`. A second take with the same name in the same minute gets `-2`. See [File names](../concepts/file-names.md) for how codes are chosen and pinned.

**Discard** deletes the take outright — the folder is removed and no archive is written. That is `app.discard_recording()`, and it is the counterpart to `stop_recording()` rather than a wrapper around it: nothing is saved and then cleaned up.

## Lifecycle in detail

```
       ┌──────────────────────────────────────────────────────┐
       │                                                      │
       │   App.run()                                          │
       │     ├─ stream.start()    ── acquisition threads spin │
       │     └─ enter GUI loop                                │
       │                                                      │
       │   ┌─ user clicks Record ────────────────────────┐   │
       │   │ app.start_recording(base_path="data")       │   │
       │   │   ├─ ctx.recording = True                   │   │
       │   │   ├─ idle → recording; predicting stays     │   │
       │   │   ├─ ctx.session = Session(base_path, ...)  │   │
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
       │   │   ├─ detach streams; freeze session         │   │
       │   │   ├─ finalize hooks; Session.save_meta(...) │   │
       │   │   ├─ writes meta.json + labels.json          │   │
       │   │   ├─ Session.pack_to_zip()  (daemon thread)  │   │
       │   │   │    -> <stamp>_<what>.mg.zip         │   │
       │   │   │    folder removed once pack succeeds     │   │
       │   │   └─ recording → idle; predicting stays     │   │
       │   └────────────────────────────────────────────────┘ │
       │                                                      │
       └──────────────────────────────────────────────────────┘
```

## The artifact

```
data/P-014/recordings/
└── P-014_20260517-1423_R+F.mg.zip       # final packaged artifact
                                          # (after Stop completes)
```

A take started while a model is predicting goes to `data/P-014/predictions/` instead, and
`Pipeline.autosave_dir` writes trained models to `data/P-014/models/`. See
[On-disk layout](../concepts/recording.md#on-disk-layout).

Inside the zip:

```
P-014_20260517-1423_R+F.mg.zip
├── emg.zarr/                       # shape (n_samples, n_channels), dtype = stream dtype
│   └── chunks: (fs, n_channels)    # 1 second per chunk
├── emg_timestamps.zarr/            # shape (n_samples,) float64 LSL clock seconds
│   └── chunks: (fs,)
├── vhi_control.zarr/               # one pair of arrays per registered Stream
├── vhi_control_timestamps.zarr/
├── meta.json                       # app_name, created (start time), streams (n_channels, fs, dtype), class_names
└── labels.json                     # list of {timestamp, class_index}
```

While recording is in progress and before `stop_recording()` completes, the same content lives as an unpacked folder `data/P-014/recordings/P-014_20260517-1423/`. The folder is deleted only after the zip is verified.

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

You don't configure these per recording; they're computed automatically from each `Stream`'s `StreamInfo`. Override the storage **location** via `base_path`; use a Rust-accelerated **codec pipeline** by installing the `[zarrs]` extra:

```bash
uv sync --extra zarrs    # transparent speedup; no code change needed
```

With `zarrs` installed, MyoGestic registers `zarrs.ZarrsCodecPipeline` at import time; large sessions write and read meaningfully faster. Without it, plain Python Zarr is used.

## Headless flow (no GUI)

For unattended capture, drive the same API from a plain script. Use `mode="headless"` so `app.run()` doesn't try to open a window:

```python
import os
import signal
import threading
import time
from myogestic import App, Stream
from myogestic.sources import LSLSource

app = App("Headless capture")
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=1000))
if not app.ctx.streams["emg"].reconnect():
    raise RuntimeError(app.ctx.streams["emg"].last_error)
app.ctx.class_names = ["Rest", "Fist"]


def _capture(app):
    # Run on a background thread so app.run()'s main loop can spin
    # the acquisition threads while we sleep here.
    def _run():
        time.sleep(2)  # let buffers warm up
        app.start_recording("data")
        app.ctx.session.add_label(0)  # initial class index
        for class_idx in (1, 0, 1, 0):  # cycle Fist <-> Rest
            time.sleep(5)
            app.ctx.session.add_label(class_idx)
        time.sleep(5)
        app.stop_recording(wait=True)
        os.kill(os.getpid(), signal.SIGINT)  # return through App.run cleanup

    threading.Thread(target=_run, daemon=True).start()


app.before_run_hooks.append(_capture)
app.run(mode="headless")
```

The artifact lands in `data/recordings/` (or `data/<ID>/recordings/` with a participant set) just as in the GUI flow.

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
| `Session(base_path="data")`                           | Constructor (called by `start_recording`; you rarely need it directly).  |
| `session.path`                                        | `Path` to the session folder being written.                              |
| `session.stores[name]`                                | The live `zarr.Array` for stream `name` (sample data, append-only).      |
| `session.ts_stores[name]`                             | Parallel timestamp `zarr.Array` for stream `name`.                       |
| `session.label_track`                                 | `list[LabelEvent]` of all labels added so far.                           |
| `session.add_label(class_index, timestamp=None)`      | Append one label. `timestamp` defaults to `local_clock()`.               |
| `session.init_stream(name, info)`                    | Pre-allocate Zarr arrays for one stream (auto-called by `start_recording`). |
| `session.append(name, data, timestamps)`              | Append a chunk (auto-called by the acquisition thread).                  |
| `session.save_meta(app_name, class_names=None)`       | Write `meta.json` and `labels.json` (auto-called by `stop_recording`).   |
| `session.pack_to_zip()`                               | Pack folder into `.mg.zip` (auto-called on a daemon thread after stop). |

You typically only call `add_label` directly; everything else is wired by `start_recording` / `stop_recording`. The class is documented at [`myogestic.session.Session`](../api/session.md).

## Reading sessions back

```python
from myogestic.session import open_session_store

# Works for both packed zips AND unpacked folders.
sess = open_session_store("data/P-014/recordings/P-014_20260517-1423_R+F.mg.zip")

emg = sess.stores["emg"]  # zarr.Array, shape (n_samples, n_channels)
emg_ts = sess.ts_stores["emg"]  # zarr.Array, shape (n_samples,) float64
labels = sess.label_track  # list[LabelEvent]
info = sess.stream_info("emg")  # StreamInfo(fs, n_channels, dtype)
```

For windowed training iteration, use the helpers in `myogestic.session`:

```python
from myogestic.session import iter_labeled_windows, iter_aligned_windows

# Classification: one (window, ts, class_index) per hop step.
for window, ts, cls in iter_labeled_windows(
    [sess.path],
    stream_name="emg",
    window_ms=200,
    hop_ms=100,
    classes={0, 1},
):
    ...

# Regression: align a primary stream with one or more aligned streams.
for window, aligned, ts in iter_aligned_windows(
    [sess.path],
    primary_stream_name="emg",
    aligned_stream_names=["vhi_control"],
    window_ms=200,
    hop_ms=50,
):
    target = aligned["vhi_control"]
    ...
```

`iter_labeled_windows` keeps each window inside one labelled segment.
`iter_aligned_windows` ignores labels and samples each target near the primary
window's midpoint. Both handle the window/hop math. See [Record and replay](record-and-replay.md) and the [Recording concept page](../concepts/recording.md).

## Common pitfalls

- **Calling `start_recording` before streams connect.** A `Stream` whose `info is None` is skipped (no Zarr schema yet). Call `stream.reconnect()` and check its result first. `App.run()` starts acquisition threads but does not connect their sources.
- **Recording with the synthetic generator paused.** The generator only produces data while it's running. Click Launch in the `ProcessLauncher` panel before Record, or in headless flow start the generator subprocess before `app.run()`.
- **Killing the process mid-recording.** The `.mg.zip` is packed only at `stop_recording()`. Starting a take writes `meta.json` with `finished: false`; each stream declaration checkpoints its schema, and a normal stop updates the metadata with `finished: true`. A crash leaves the raw `data/<ID>/recordings/<ID>_<timestamp>/` folder (or `predictions/` for a prediction take), readable with `open_session_store(...)` and listed by `SessionManager`. With the recording process stopped, pack that folder through the normal verified pack path:

  ```python
  from myogestic.session import recover_session

  archive = recover_session("data/P-001/recordings/P-001_20261107-0930")
  ```

  Recovery removes the folder after packing succeeds and keeps `finished: false` in the archive. It recovers samples and event batches already written to disk; buffered event rows, labels and extras changed since the last checkpoint, and outputs from finalize hooks may be missing. It does not resume recording or run those hooks. Metadata is written at start, stream declaration and stop, with no extra writes per acquisition chunk or event-buffer flush. Older crashed folders without `meta.json` cannot be recovered this way.
- **Forgetting class names.** `RecordingControls` sets them automatically. For custom labels, set `app.ctx.class_names = ["Rest", "Fist"]` before stopping; `stop_recording` passes that list to `save_meta`.

## See also

- [Recording concept page](../concepts/recording.md) - the runtime model + label-track design.
- [Record and replay](record-and-replay.md) - feeding a recorded session back into a `ReplaySource` for offline debugging.
- [`myogestic.App.start_recording` / `stop_recording`](../api/core.md) - full API reference for the lifecycle methods.
- [`myogestic.session.Session`](../api/session.md) - full `Session` class reference.
- [`myogestic.session.open_session_store`](../api/session.md) - load packed or unpacked sessions.
- [`myogestic.session.iter_labeled_windows`, `iter_aligned_windows`](../api/session.md) - training-window iterators.
