# Design: record while predicting — the session carries the model's input and output

**Status:** implemented; ships in the unreleased MyoGestic 2.0.
Adapted to 2.0's gesture tiles, timed takes, participant sessions, and AppHeader state pill.

## Context / problem

A recording is "start appending to Zarr" (`docs/concepts/recording.md`). That is the right
mental model, but the state machine does not follow it: `App.start_recording` refuses
unless `ctx.state == "idle"`, and `Pipeline.start_predicting` refuses unless it is `"idle"`
too. Recording and predicting are mutually exclusive, so the one run everybody wants a
record of — a model driving a hand — cannot be recorded.

Nothing in core persists what the pipeline saw or produced either. `Pipeline.predictions`
holds the latest dict in memory; `ControlBus.push` returns what it delivered and forgets it.
Every downstream project has therefore grown its own copy:

- `myogestic-galvani/examples/bracelet/bracelet_ml.py` carries ~200 lines of "Rec Pred": a
  hand-built `Session`, `stream.attach_session` on the live streams, two manually declared
  streams for predictions and the VHI control readback, a worker thread with its own LSL
  inlet, and a zip step that duplicates `Session.pack_to_zip`.
- `myogestic-galvani/examples/myocontrol_spar_tokens.py` keeps per-prediction rows in
  memory during an evaluation and writes an NPZ plus JSON at the end. Raw EMG is never
  stored, free control leaves no trace, and a third copy was about to be written.

Replay is already solved: `ReplaySource` plays a recorded stream back with its **recorded
timestamps**, so a session fed through it reproduces the original clock. What is missing is
the record to compare against.

## Goals / non-goals

**Goals**

1. Recording can start and stop while a model is predicting. The pipeline keeps running.
2. While a session is active, the pipeline writes what `extract` returned and what `predict`
   returned, one row per tick, timestamped with the newest sample the tick saw.
3. While a session is active, the control bus writes the continuous frame it actually
   delivered, one row per push.
4. On stop, the model that was running is saved into the session folder, with its
   provenance in `meta.json`.
5. Existing apps behave exactly as before unless they press Record while predicting.
6. Downstream projects delete their hand-rolled recorders.

**Non-goals**

- Discrete DOF edges (`changed` in `Target.send`) as a recorded stream. They are events,
  not frames; a later spec can add them as a label-like track.
- Recording during `training`. Training needs `idle` and keeps needing it.
- A replay-comparison CLI. `ReplaySource` plus a second recording is the mechanism; the
  how-to shows the diff in ten lines of numpy.
- Recording ≥ 2-D arrays from `extract`/`predict`. A raw window returned by `extract` is the
  EMG stream, which is already recorded; a CNN history is reconstructible from consecutive
  frames. Both are skipped, once, with a log line.

## Design

### 1. Recording is a flag beside the state, not a state that excludes others

`Context` gains one field:

```python
recording: bool = False  # a Session is open and streams are appending to it
```

`ctx.session` is **not** the flag. `stop_recording` deliberately leaves `ctx.session` set so
the signal viewer keeps drawing the last take's label markers; `discard_recording` clears
it. The flag is set in `start_recording`, cleared in `stop_recording` and
`discard_recording`.

`AppState.RECORDING` stays, with its current meaning: the app is recording and nothing else
is going on. The rule that decides `ctx.state`:

> `ctx.state` is the pipeline's state while the pipeline is busy (`training`,
> `predicting`); otherwise `"recording"` if `ctx.recording`, else `"idle"`.

Which states may start a recording is a registry the same way `STATE_COLORS` is:

```python
# myogestic/core.py
RECORDABLE_STATES: set[str] = {AppState.IDLE}
# myogestic/ml/pipeline.py, in Pipeline.__init__
RECORDABLE_STATES.add(PipelineState.PREDICTING)
```

Core never spells `"predicting"`; the extension registers itself, as it does for colours.
Like `STATE_COLORS`, the set is process-global: once any test has imported `myogestic.ml`,
`"predicting"` is recordable for the rest of the process, so a core test asserting refusal
from that state must snapshot and restore the set rather than rely on import order.

Transitions (rows are the current situation, cells the outcome):

| situation | `start_recording` | `stop_recording` / `discard_recording` | `start_predicting` | `stop_predicting` | `start_training` |
|---|---|---|---|---|---|
| `idle` | → `recording`, flag on | no-op | → `predicting` | no-op | → `training` |
| `recording` | no-op ("already recording") | → `idle`, flag off | → `predicting`, flag stays on | no-op | refused (needs `idle`) |
| `predicting`, flag off | flag on, state stays `predicting` | no-op | no-op | → `idle` | refused |
| `predicting`, flag on | no-op | flag off, state stays `predicting` | no-op | → `recording` | refused |
| `training` | refused | no-op | refused | no-op | no-op |

Concretely:

- `App.start_recording`: refuse if `ctx.recording`; refuse if `ctx.state not in
  RECORDABLE_STATES`; set `ctx.recording = True`; set `ctx.state = RECORDING` only when the
  state was `IDLE`. Everything else unchanged.
- `App.stop_recording` / `discard_recording`: refuse if `not ctx.recording`; clear the flag;
  set `ctx.state = IDLE` only when the state was `RECORDING`. Everything else unchanged.
- `Pipeline.start_predicting`: accept `idle` **or** `recording`; state → `predicting`.
- `Pipeline.stop_predicting`: state → `"recording"` if `ctx.recording` else `"idle"`.
- `Pipeline.start_training`: unchanged (`idle` only). With the flag on the state is
  `recording`, so it is refused with the existing message.

`can_transition` keeps its idle ↔ recording contract and its tests; the new allowances are
explicit checks beside it.

### 2. `Session.append_event`: one row, declared on first use

Recording a per-tick vector today means `init_stream` with a `StreamInfo` invented for the
purpose, then `append` — the bracelet demo's boilerplate. One method replaces it:

```python
def append_event(
    self,
    name: str,
    values: ArrayLike,
    timestamp: float,
    *,
    channel_names: Sequence[str] | None = None,
    fs: float = 1.0,
    dtype: Any = np.float32,
) -> None:
    """Append one timestamped row to an event stream, declaring it on first use.

    `values` is flattened and cast to `dtype`; its width is fixed by the first call and a
    later row of a different width raises ValueError. Rows are dropped silently
    once finalisation has begun, like `append`.
    """
```

`pipeline.tick` (§3) is declared with `dtype=np.float64`: `local_clock()` is seconds since
boot, and float32's ~7 significant digits quantise it to tens of milliseconds after a day
of uptime — the size of the latency the column exists to measure.

- Storage is the same per-stream pair as any stream: `<name>.zarr` `(n_rows, width)` and
  `<name>_timestamps.zarr`, so `open_session_store`, `ReplaySource` and every existing
  reader see it with no change.
- **Rows are buffered in memory and written in batches.** Measured with zarr 3.2.1 on this
  machine: one single-row `append` into a `(1024, 96)`-chunked array costs 1.46 ms, because
  zarr reads, decompresses, rewrites and recompresses the partial chunk every time; the same
  rows appended 32 at a time cost 0.04 ms per row. Ten event streams at 32 Hz would spend
  ~470 ms of every second on the predict thread, whose whole budget is 31 ms per tick. So
  `append_event` appends to a per-stream Python list and flushes it to zarr when the list
  reaches `chunk_rows` (1024) or when its oldest row is more than one second old, checked
  on each call — no timer thread. `freeze()` (below) flushes everything. The check runs
  when *that* stream receives a row, so a stream that goes quiet mid-take reaches disk at
  `freeze()`, not within a second. The bounded cost is therefore, per active stream, one
  second of event rows lost on a hard crash; the raw streams are unaffected, they keep
  appending as today.
- Chunks are `(1024, width)` rather than `int(fs)` rows (`init_stream` gains a `chunk_rows`
  keyword; the default for sampled streams is unchanged).
- `StreamInfo.fs` is a **nominal** rate, not zero: `predict_hz` for the pipeline's streams
  (`1.0` if the cap is off) and the bus `hz` for `controls`. `ReplaySource.read` paces by
  `int(elapsed * fs)`, so a zero rate would make the stream unreplayable, and "drive the
  hand from a recorded `controls` stream with no model" is the obvious next use. `meta.json`
  adds `"event_streams": [names]` to say these rows are irregular, one per tick, so a
  reader does not mistake the nominal rate for a sampling clock.
- `Session.freeze()` takes the lock, sets `_finalising`, flushes every buffer, and returns.
  After it, `append` and `append_event` drop their rows with a debug log, like the late-
  append guard in `append` today, and no new stream can be declared. `stop_recording` and
  `discard_recording` call it **right after detaching the streams and before anything is
  written**, so a `controls` row or a late-appearing prediction key cannot declare a stream
  after `meta.json` has listed the streams (an orphan `.zarr` folder `open_session_store`
  would never see). `pack_to_zip` and `discard` call `freeze()` themselves as well, so they
  stay safe when used directly.
- Thread safety: one `threading.Lock` per session guards declaration, buffer append, flush
  and freeze. Acquisition threads keep calling `append` unchanged; `append_event` is for
  the predict thread, the UI thread and the bus.

### 3. The pipeline records its tick

`_predict_step` already has everything: the windows with their timestamps, the `extract`
result, the `predict` result. When `app.ctx.recording` and `app.ctx.session` is set:

```python
t = max(ts[-1] for ts in window_timestamps if len(ts))  # newest sample this tick saw
self._record(session, "features", features, t)
self._record(session, "prediction", result, t)
session.append_event("pipeline.tick", [local_clock()], t)
```

`_record(session, prefix, obj, t)`:

- A `Mapping` becomes one event stream per key, `f"{prefix}.{key}"`. Anything else is one
  stream named `prefix`.
- A value is recorded when it is a `bool`, a number, or an array-like of numbers with
  `ndim <= 1`. It is skipped when it is a `str`, `None`, a nested mapping, or `ndim >= 2`.
- A skip, or a `ValueError` from a width change (the model was swapped mid-recording), is
  logged **once per session per name** through `ctx.log` and that name is skipped for the
  rest of the recording. The skip list is written to `meta.json` at stop (§5), so a reader
  knows what is missing and why.
- Recording never raises into the predict loop; failures degrade to "not recorded", logged
  once.

Timestamps: rows are stamped with the newest sample the tick consumed, so they align with
the raw arrays and stay in the data's clock under replay. `pipeline.tick` holds the LSL `local_clock()`
at the decision, so **latency = tick − timestamp** is one subtraction away, and a replay
run (whose data timestamps match the original) can be told apart from the live one.

For the SPAR example this rule records, with no app code: `features.features` (72 or 96
wide by family), `features.history_ends` (16 frame times), `features.valid`,
`features.frame_seq`, `prediction.tokens`, `prediction.continuous`, `prediction.token_ids`,
and skips `features.history` (2-D) and `reason` (str), each with one log line.

### 4. The control bus records what it delivered

`ControlBus` has no context today; `connect_controls(ctx=…)` has one. The bus gains an
optional `ctx` and `connect_controls` passes it through. Recording happens in `_deliver`,
the single point where a frame leaves the bus — so the rest frame delivered by the failure
path in `push` is recorded too, as it should be:

```python
def _deliver(self, values, changed):
    for target in self._targets:
        ...  # unchanged
    ctx = self._ctx
    if ctx is not None and ctx.recording and ctx.session is not None:
        try:
            ctx.session.append_event(
                "controls",
                encode(self._controls, values),
                local_clock(),
                channel_names=self._names,
            )
        except Exception as exc:
            self._warn_once("record", f"controls not recorded: {exc!r}")
```

The stream is the continuous frame in declaration order, which is the wire order, with the
DOF names as channel names. It is stamped with the delivery clock, not a data timestamp:
the bus does not know which window produced a frame, and the pair (`pipeline.tick`,
`controls` timestamp) is what tells you how long the smoother and the mapping took.

### 5. The model rides along, and provenance lands in `meta.json`

Core does not know the pipeline. It gains a hook list next to the two it has:

```python
app.finalize_hooks: list[Callable[[Session], None]]
```

run **before** `save_meta`, each wrapped in try/except with a log line, so a hook can add to
`session.extras`. `discard_recording` runs none: a discarded take is a take thrown away.

`stop_recording` is a button handler on the UI thread, and pickling a torch model there
hitches the frame for as long as joblib takes. So the order becomes: on the UI thread,
detach streams and `freeze()` (both cheap); then on the existing `_finalize` daemon, run the
hooks, `save_meta`, `pack_to_zip`, and register the archive. Today `save_meta` runs on the
UI thread and only the pack is deferred; moving it is a one-place change because the browser
path already runs `_finalize` inline (Pyodide has no threads) and keeps doing so. The status
message says "finalizing…" from the moment Stop is pressed, as it does now.

`Pipeline.__init__` registers `_on_finalize(session)`:

- Only takes with recorded pipeline ticks get `extras.pipeline`; ordinary training takes
  do not. The model reference and skip list belong to each take, so a later run cannot
  replace them while finalization is pending. If that model is not None and
  `self.save_model` is set: `save_model(model,
  session.path / "model.joblib")`. This pickles on the finalize thread while the predict
  thread may still be calling the model; every model in this repo is read-only in
  `predict`, so the snapshot is consistent. A model that mutates state in `predict` would
  be pickled mid-update — acceptable for a provenance copy, and noted here so nobody
  relies on it for more. With the default `save_pickle` this also writes the
  `model.joblib.controls.json` sidecar into the folder.
- `session.extras["pipeline"] = {"model": "model.joblib" | None, "model_type":
  qualname, "predict_hz": …, "event_streams": […], "skipped": {name: reason}, "report":
  getattr(model, "report", None) if it is JSON-serialisable}`. When `save_model` is unset
  the entry says so, so the absence is a recorded fact, not a mystery.

### 5b. Exit while recording

`App.run`'s cleanup stops streams and runs the cleanup hooks; it never looks at the session.
An app closed mid-take today leaves a folder with zarr arrays and no `meta.json`, which
`open_session_store` cannot read. The bracelet demo registered its own cleanup hook for
exactly this. Once recording is a first-class run mode, core owns it: the `_do_cleanup`
closure in `run()` becomes an `App._cleanup()` method (so a test can drive it) and calls
`stop_recording()` when `ctx.recording`, **after** the cleanup hooks (so the pipeline's
`_cleanup` has already stopped the predict thread, and no tick appends during the flush)
and **before** `stream.stop()`. `stop_recording` gains a keyword-only `wait: bool = False`;
cleanup passes `wait=True`, which runs `_finalize` inline exactly as the browser path does,
because a daemon would be killed at interpreter exit with the archive half written. The user sees the app take as long to close as the pack takes; the take is saved.

### 6. Widgets

The 2.0 widgets read the recording flag whenever they mean a take is open:

- `RecordingControls` (`widgets/panels/recording.py` and `_recording_controls.py`):
  keep 2.0's gesture tiles, timed takes and saved-take tile. Start is available when
  `not ctx.recording and ctx.state in RECORDABLE_STATES`; ownership, Stop and label
  snapping use `ctx.recording`. Timed warm-ups may run in a recordable state.
- The state pill lives in `AppHeader`. It shows `ctx.state`; when `ctx.recording` and
  the state is not `"recording"`, a second pill reading `REC` in
  `STATE_COLORS["recording"]` follows it, so a predicting-and-recording app shows
  `PREDICTING REC`. RecordingControls no longer draws a pill.
- `RecordButton._stop` detaches the streams and calls `ctx.session.freeze()` at the
  click, before its naming dialog, so raw and event rows both end at Stop.
- `DevicePicker` and `StreamManager` block reconnect during a recording via
  `getattr(ctx, "state", "") == "recording"`; they switch to `getattr(ctx, "recording",
  False)`, which also covers the new case. Reconnecting under a live recording would
  detach the session mid-take either way.
- The ML `PredictButton` starts from `recording` as well as `idle`, since the transition
  table allows it; its "Busy" tooltip follows.
- `RecordButton` draws a disabled Record with a "Busy" tooltip in a state that is neither
  recordable nor recording (`training`), instead of nothing.

### 7. Replay

No new code. The how-to gains a section: record a live run, then run the same app with
`ReplaySource(session, "emg")` and Record on. `ReplaySource` returns the recorded
timestamps, so the second session's raw arrays carry the same clock as the first. The
prediction rows do **not** line up exactly, and the how-to must say so: `_predict_step` is
paced by wall time (`period − elapsed`), so live and replay ticks fall on different sample
boundaries, and an app whose `extract` anchors its frame grid to ring position (the SPAR
example does) shifts phase as well. The check is therefore nearest-timestamp matching within
half a tick, comparing `prediction.*` rows pairwise, with `pipeline.tick − timestamp` as
the latency of each run. An app gets exact matches only if its frame grid is anchored to
data timestamps; that is the app's choice, not core's.

## On-disk layout

```text
sessions/2026-09-13_10-12-44_3f9a1c02/
    meta.json                         # streams (incl. event streams), event_streams,
                                      # extras.pipeline, extras.conditioning, control_space
    labels.json
    model.joblib                      # what was running, if pipeline.save_model is set
    model.joblib.controls.json        # save_pickle's sidecar
    emg.zarr / emg_timestamps.zarr    # 2 kHz, as today
    features.features.zarr / _timestamps.zarr        # one row per tick, width by family
    features.history_ends.zarr / …
    prediction.tokens.zarr / …                       # 5 wide
    prediction.continuous.zarr / …
    prediction.token_ids.zarr / …
    pipeline.tick.zarr / …                           # 1 wide: decision clock
    controls.zarr / controls_timestamps.zarr         # continuous DOFs in wire order
```

Budget for the SPAR example: 96 floats at 32 Hz is 12 KB/s; every event stream together is
under 40 KB/s, against 64 KB/s for the raw EMG. Zarr compresses both.

## Threading and failure handling

| Thread | Writes | Guard |
|---|---|---|
| acquire (per stream) | `append` | `Stream._session_lock`, unchanged |
| predict | `append_event` (features, prediction, tick) → in-memory buffer, batched flush | `Session` lock; skip-once list |
| UI or predict | `append_event("controls")` via the bus | same lock; `_warn_once` |
| UI (Stop) | detach streams, `freeze()` | lock; after it every append is dropped |
| finalise (daemon; inline in the browser and at exit) | hooks, `save_meta`, `pack_to_zip` | runs only after `freeze()` |

Nothing here may raise into the predict loop or the bus. Every failure path logs once and
degrades to "not recorded".

## Backward compatibility

- No API removed. `AppState.RECORDING`, `can_transition`, `RecordingControls`'s call
  signature, `Session.append`/`init_stream` all keep their contracts.
- Behavioural changes an existing app can notice: the Record button appears while
  predicting; `start_recording()` called programmatically while predicting now succeeds;
  `stop_predicting()` lands in `recording` instead of `idle` if a take is open. Each is
  what the button promised.
- Sessions gain `event_streams` in `meta.json`; older readers ignore unknown keys and see
  the new arrays as ordinary streams with a nominal `fs`. `_windows.py` only touches a
  stream when asked to train on it by name.
- `save_meta` moves from the Stop click to the finalize thread. A caller that read
  `meta.json` synchronously after `stop_recording()` returned (none in this repo) would now
  have to wait for the archive.
- Version: unreleased 2.0.

## Testing

Core (`tests/test_core.py`):
- `start_recording` while `predicting` sets the flag, leaves the state, attaches streams.
- `stop_recording` while `predicting` clears the flag, leaves the state, runs finalize
  hooks before `save_meta` (hook writes `extras`, `meta.json` has it).
- `stop_predicting` with the flag on lands in `recording`; with it off, `idle`.
- `start_predicting` from `recording` succeeds and keeps the flag.
- `start_recording` refused while `training`, and while already recording (existing test).
- `discard_recording` while predicting runs no finalize hook and clears the flag.
- `stop_recording` calls `freeze()` before any hook runs; an `append_event` from a hook is
  dropped, and `meta.json` lists exactly the streams that exist on disk.
- Cleanup with the flag on packs the take inline and leaves a readable archive; cleanup
  with the flag off does not create a session.

Session (`tests/test_session*.py`):
- `append_event` declares on first call, fixes the width, raises on a mismatch, stores
  float64 timestamps, uses 1024-row chunks, lists the name under `event_streams`, and
  records the given nominal `fs`.
- Rows sit in the buffer until `chunk_rows` or one second; `freeze()` flushes them all;
  a row after `freeze()` is dropped and the folder still packs; no stream can be declared
  after `freeze()`.
- `open_session_store` reads event streams back, and `ReplaySource` replays one at its
  nominal rate.

Pipeline (`tests/test_ml.py`), driving `_predict_step` directly with a fake stream:
- Dict `extract`/`predict` results become `features.<k>` / `prediction.<k>` rows stamped
  with the window's last timestamp; `pipeline.tick` is present.
- A 2-D value, a `str`, and a width change are skipped, each logged exactly once.
- With `save_model` set, `model.joblib` and `extras["pipeline"]` exist after stop; with it
  unset, the extras say so and the loop never raised.

Bus (`tests/test_control_bus.py`):
- With a recording context, `push` appends one `controls` row equal to the delivered
  continuous vector, in DOF order, with DOF channel names; the failure path records rest.
- Without a context, or with the flag off, nothing is appended.

Widgets (`imgui_frame` fixture; a new test module if none covers `RecordingControls`):
- Record renders while `predicting`; Stop renders while recording under `predicting`;
  the `REC` pill appears only when the state is not `"recording"`.

## Docs and changelog

- `docs/concepts/recording.md`: the state diagram gains the flag; new section "Event
  streams" (what the pipeline and bus record, naming, the skip rules, the clocks).
- `docs/concepts/pipeline.md`: state-machine section updated with the table above.
- `docs/how-to/record-and-replay.md`: "Record a prediction run" and "Check a replay against
  the live run".
- `CHANGELOG.md` `[Unreleased]` → Added: record while predicting; `Session.append_event`;
  pipeline and bus event streams; model saved with the session; `App.finalize_hooks`.
  Changed: `RecordingControls` offers Record while predicting; `stop_predicting` returns to
  `recording` when a take is open.

## Rollout in myogestic-galvani (after 2.7.0 is on PyPI)

- `examples/bracelet/bracelet_ml.py`: delete `_start_pred_recording`, `_stop_pred_recording`,
  `_vhi_ctrl_worker`, the zip step and their globals (~200 lines). The Rec Pred toggle calls
  `app.start_recording("predictions")` / `app.stop_recording()`. Its predictions row layout
  is replaced by `prediction.*`; `tools/plot_prediction_session.py` reads the new names.
- `examples/myocontrol_spar_tokens.py`: the evaluation keeps writing its scoring JSON; the
  NPZ row buffering goes, and a Record toggle works in free control.
- `pyproject.toml`: `myogestic[grpc]>=2.7.0`.

## Open questions

1. `REC` pill beside the state pill, or only the detail line under the button? The pill is
   proposed because the detail line is not visible in every layout.
2. Should `features` from a non-dict `extract` (a bare 1-D vector) be named `features` or
   `features.value`? Proposed: `features`, mirroring the raw stream naming.
