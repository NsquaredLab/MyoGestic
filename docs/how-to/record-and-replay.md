# Record and replay

End-to-end: capture sessions in the GUI, browse them in [`SessionManager`][myogestic.widgets.SessionManager], train on them, then replay one offline as a Source so you can debug the predict path without re-running the experiment.

## Live capture

Drop two widgets in `@app.ui`:

```python
from myogestic.widgets import RecordingControls, SessionManager

CLASSES = ["Rest", "Fist", "Open"]

recording = RecordingControls(
    CLASSES,
    on_record=app.start_recording,
    on_stop=app.stop_recording,
    on_gesture=lambda i: ctrl_outlet.push_sample([float(i)]),
)
sessions = SessionManager(base_path="sessions", class_names=CLASSES)


@app.ui
def ui(ctx):
    with grid[0, 0]:
        recording.ui(ctx)
    with grid[1, 0]:
        pipeline.training_data = sessions.ui()
```

[`RecordingControls`][myogestic.widgets.RecordingControls] renders:

- **Record / Stop** buttons that call `app.start_recording("sessions")` / `app.stop_recording()`.
- One **button** per class. Clicking a button writes a `LabelEvent(class_index, timestamp=local_clock())` to the active session's label track and fires your `on_gesture` callback. Use the callback to drive an external pattern (synthetic generator, robot, prompt screen).

The `on_gesture` callback is yours; the label is added by `RecordingControls` itself before calling it. You don't need to call `ctx.session.add_label()` manually.

`SessionManager` lists every folder/archive under `base_path`, lets the user tick which to include in training, and returns a [`TrainingData`][myogestic.TrainingData] instance ready for `@pipeline.train`.

## Recording cycles

For models that need many short trials per session, record cycle-style:

```text
[Record]
  [Rest]   3 s    "rest"
  [Fist]   3 s    "first activation"
  [Rest]   3 s
  [Fist]   3 s    "second activation"
  ...
[Stop]
```

One Record→Stop cycle yields one session with 8–10 trials. The framework's training helpers skip the first segment (it's usually setup noise), so single-click sessions yield exactly one usable trial - too few for robust models.

## Reading sessions programmatically

Use [`open_session_store`][myogestic.session.open_session_store] for either layout (folder or `.session.zip`):

```python
from myogestic.session import open_session_store

sess = open_session_store("sessions/2026-05-06_18-46-47.session.zip")

# Continuous data - sample-major as recorded
data, ts = sess.get_continuous("emg")
print(data.shape, ts.shape)  # (N, n_ch), (N,)

# Stream metadata
info = sess.stream_info("emg")
print(info.n_channels, info.fs, info.channel_names)

# Per-trial slices
for r in sess.get_trials("emg", pre_s=0, post_s=0):
    print(r.class_name, r.data.shape, r.timestamps.shape)
```

`r.data` is `(n_samples, n_channels)` - sample-major (as stored on disk).

## Iterating windows for training

### Classification - [`iter_labeled_windows`][myogestic.session.iter_labeled_windows]

<!--docs:run-->
```python
from myogestic.session import iter_labeled_windows

X, y = [], []
for window, ts, cls in iter_labeled_windows(
    data.paths,
    stream_name="emg",
    window_ms=200,
    hop_ms=100,
    classes={0, 1, 2},
):
    X.append(rms(window))  # window: (n_channels, n_samples)
    y.append(cls)
```

- `window_ms` / `hop_ms`: window duration / step in milliseconds.
- `classes`: optional set of class indices to include (handy when you want to skip "rest").
- Drops windows that straddle a label boundary so each window has exactly one class.
- Each iteration yields `(window, ts, class_index)` - `ts` is the matching 1-D timestamp array.
- `window` is **channels-first** - match your feature extractor.

### Regression - [`iter_aligned_windows`][myogestic.session.iter_aligned_windows]

<!--docs:run-->
```python
from myogestic.session import iter_aligned_windows

X, Y = [], []
for window, targets, ts in iter_aligned_windows(
    paths=data.paths,
    primary_stream_name="emg",
    aligned_stream_names=["vhi_guide"],
    window_ms=200,
    hop_ms=50,
    n_alignment_samples=1,
):
    X.append(rms(window))
    Y.append(targets["vhi_guide"])  # 1-D vector synchronised to ts[-1]
```

- `primary` is the stream you slice into windows.
- `aligned` is a list of *target* streams whose latest value at the window's end is paired with the EMG window.
- `n_alignment_samples` is the tolerance (samples) for the alignment lookup.

## Replay as a Source

[`ReplaySource`][myogestic.sources.ReplaySource] reads from a `.session.zip` (or folder) and re-emits the data at the original sample rate, just like a live device:

```python
from myogestic import App, Stream
from myogestic.sources import ReplaySource

app = App("Offline replay")
app.streams(
    Stream(
        "emg",
        source=ReplaySource(
            session_path="sessions/2026-05-06_18-46-47.session.zip",
            stream_name="emg",
            speed=1.0,  # 0.5 = half-speed, 2.0 = double-speed
        ),
        window_ms=1000,
    )
)
app.run()
```

Your `@pipeline.predict` runs against the replayed data - same shape, same channel count, same timestamps. Useful for:

- **Debugging the predict path** without re-running the experiment.
- **Comparing models** on a fixed input.
- **Demos** without hardware.

The replay loops by default; set `speed=0` if you want to step manually (TODO: not currently exposed).

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **Recording too short.** A session with 2 label clicks (e.g. Rest + Fist) and 1.5 s of data yields exactly **one** usable trial after skip-first. Cycle-style sessions are the only way to get robust models with limited recording time per session.
- **`sess.class_names = [...]` after `save_meta`.** Class names persist only when passed as a kwarg to `save_meta(name, class_names=...)`. (`RecordingControls` handles this when it triggers `app.start_recording`.)
- **Sample-major in user code.** `sess.get_continuous("emg")` returns sample-major (matches storage). `iter_labeled_windows` and `iter_aligned_windows` flip to channels-first (matches predict). Don't transpose twice by accident.
- **Replay-then-predict-on-live.** `ReplaySource` and a real `LSLSource` can't share the stream name. Pick one per app.
