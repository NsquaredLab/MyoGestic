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

### Timed takes

Offer fixed-length takes alongside the usual **Start / stop** mode:

```python
recording = RecordingControls(
    CLASSES,
    on_record=app.start_recording,
    on_stop=app.stop_recording,
    take_lengths=(3.0, 5.0, 10.0),
    warmups=(0.0, 1.0, 2.0, 3.0),
    timed=True,
    take_length=5.0,
    warmup=2.0,
)
```

By default, the widget starts in **Start / stop** mode. Pass `timed=True` to open in
**Timed**, which shows the take-length and warm-up choices. The keyword-only
`take_length` and `warmup` arguments select the initial entries; each defaults to
`None`, selecting the first value in `take_lengths` or `warmups`. An explicit value
outside its sequence raises `ValueError` naming the allowed values. The example
above opens in **Timed** at 5 s with a 2 s warm-up, as Myocontrol does.

Empty `take_lengths` keeps start/stop only; `timed=True` without any take lengths
raises `ValueError`. Take lengths must be finite and positive; warm-ups must be
finite and nonnegative, with at least one choice. Zero is **Off** and starts capture
on the Record press.

Choose a gesture before starting a labelled timed take. Warm-up records nothing.
**Cancel** returns to idle without creating a session.
When capture begins, the chosen gesture is labelled once and the other tiles are
disabled until the take ends. The action row shows elapsed / target time and a
progress line. The first UI frame at or after the deadline calls `on_stop`, saving
the take through the existing app callback. Timing resolution follows the frame
rate; a delayed frame stops immediately when it resumes. **Stop early** also saves
the captured data and marks the confirmation `(stopped early)`. The confirmation
lasts two seconds. Start/stop mode shows elapsed time and permits gesture changes.

`recording.take` is an immutable snapshot with `phase` (`idle`, `warmup`, `recording`,
or `saved`), `timed`, `gesture`, `elapsed_s`, `length_s`, `warmup_left_s`, and
`saved_text`. Read it after `ui()` to draw a signal overlay, as Myocontrol does.
Call `recording.ui(ctx, visible=False)` on frames where another workflow step is
open: this advances the timer without drawing controls. Call `ui()` once per frame.

Participant changes or a recorded stream disconnecting cancel a countdown; during
capture they stop and retain the data already collected, then return the widget
to idle. An outside stop or a replacement session clears the widget's pending
action without stopping another capture. Calling `app.stop_recording()` during
warm-up cancels that countdown even though the app is still idle.

### Saved sessions

`SessionManager` lists folders and archives under `base_path` when you press its rescan icon.
Passing `ui(participant="P-014")` scans that participant's subfolder automatically. Each take
occupies one line, grouped by its recorded day (Today, Yesterday, or a date); only the newest
group starts open. A take's gesture names, time, and duration stay on that line, with its file
name, optional take name, and streams in the tooltip. The list alone scrolls, leaving the
header, selected count, and gesture chips visible.

Use **All** / **None** to select or clear every take, including collapsed days. Gesture chips
show totals across all listed takes; toggling one excludes that class from training and mutes
its chips in the take rows. Exclusions survive **None** followed by **All**, and reset when you
change participants or clear the list. The load icon adds files from elsewhere under **Loaded**;
the broom clears the list while leaving files on disk.

`ui()` returns a [`TrainingData`][myogestic.TrainingData] instance ready for `@pipeline.train`.
`selection()` reads the same selection without rendering or scanning: `n_selected`, `n_total`,
and `class_seconds` (selected takes and included gestures only). Older recordings without
per-gesture duration metadata contribute zero seconds for their labels. Myocontrol's Train
card uses this summary for its gesture bars and total, explains missing gestures before a fit,
and shows the saved model's filename after training.

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

The replay loops back to the start when it reaches the end. `speed` scales the pacing against
wall-clock time; `speed=0` halts it after the first chunk rather than stepping, since there is
no manual-advance call.

## Record a prediction run

Load or train a model, press **Predict**, then press **Record**. The pill row reads `PREDICTING REC`. In Myocontrol’s Drive step, use **Record this run** while predicting. Press it again to save; predicting continues. **Stop predicting** saves an open run first, then returns to idle. Drive runs appear in Takes with a **Drive** tag and stay unticked for training until selected.

Stop when done; the archive holds the raw streams *and* what the model saw and did:

```python
from myogestic.session import open_session_store
import numpy as np

with open_session_store("sessions/2026-09-13_10-12-44_3f9a1c02.session.zip") as s:
    print(s.event_streams)          # ('features.vec', 'prediction.pose', 'pipeline.tick', 'controls')
    pose = np.array(s.stores["prediction.pose"])            # (n_ticks, 5)
    t = np.array(s.ts_stores["prediction.pose"])            # data time of each tick
    tick = np.array(s.stores["pipeline.tick"])[:, 0]        # decision clock
    print("median latency", np.median(tick - t), "s")
    print(s.extras["pipeline"]["model"])                    # 'model.joblib', beside the arrays
```

The model is pickled into the session when `pipeline.save_model` is set (the ML widgets' Save button uses the same callable). Values `extract` or `predict` returned that were not recordable — text, 2-D arrays — are named in `s.extras["pipeline"]["skipped"]` with the reason.

## Check a replay against the live run

Run the same app on the recording with `ReplaySource(path, "emg")` in place of the device, press Predict, press Record, and stop after the replay has looped once. `ReplaySource` returns the recorded timestamps, so both sessions are in the same clock. The ticks do **not** fall on the same samples: the predict loop is paced by wall time, and an app whose feature frames are anchored to ring position shifts phase too. Compare by nearest timestamp within half a tick:

```python
live = open_session_store("live.session.zip")
replay = open_session_store("replay.session.zip")
tl, pl = np.array(live.ts_stores["prediction.pose"]), np.array(live.stores["prediction.pose"])
tr, pr = np.array(replay.ts_stores["prediction.pose"]), np.array(replay.stores["prediction.pose"])
j = np.searchsorted(tr, tl).clip(1, len(tr) - 1)
j = np.where(np.abs(tr[j - 1] - tl) < np.abs(tr[j] - tl), j - 1, j)
close = np.abs(tr[j] - tl) < 0.5 / live.extras["pipeline"]["predict_hz"]
print("matched", close.mean(), "max |Δpose|", np.abs(pr[j][close] - pl[close]).max())
```

Exact matches need an `extract` whose frame grid is anchored to data timestamps rather than to the ring; that is the app's choice.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **Recording too short.** A session with 2 label clicks (e.g. Rest + Fist) and 1.5 s of data yields exactly **one** usable trial after skip-first. Cycle-style sessions are the only way to get robust models with limited recording time per session.
- **`sess.class_names = [...]` after `save_meta`.** Class names persist only when passed as a kwarg to `save_meta(name, class_names=...)`. (`RecordingControls` handles this when it triggers `app.start_recording`.)
- **Sample-major in user code.** `sess.get_continuous("emg")` returns sample-major (matches storage). `iter_labeled_windows` and `iter_aligned_windows` flip to channels-first (matches predict). Don't transpose twice by accident.
- **Replay-then-predict-on-live.** `ReplaySource` and a real `LSLSource` can't share the stream name. Pick one per app.
