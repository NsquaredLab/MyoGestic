---
title: "Troubleshooting"
---
Find a symptom, its cause and its fix below. The concept and how-to pages link here from their "Common mistakes" sections.

## Streams and acquisition

### "buffer empty" or no data on the first read

`Stream.get_window()` returns an empty array because the acquisition thread hasn't received any chunks yet. Either the source isn't connected (`stream.info is None`), or the upstream LSL outlet hasn't started publishing.

!!! tip "Fix"
    Streams start detached. In headless scripts, call `stream.reconnect()` before `app.run(mode="headless")` and start recording from a startup hook or another control path. In GUI mode, press Connect in the device picker or viewer after the source is available. Wait for `get_window()` to return nonempty data; a fixed sleep does not connect a source.

### Acquisition thread freezes

A blocking call inside the source's `read()` pauses acquisition and ring-buffer updates, delaying prediction. Custom sources should poll without blocking, for example with `pylsl.pull_chunk(timeout=0.0)`.

!!! tip "Fix"
    Audit your source for synchronous network reads, blocking I/O on serial lines, or anything else that holds the GIL longer than ~1 ms.

### Wrong shape from a custom source

If a Source adapter accidentally returns `(n_channels, n_samples)` instead of sample-major `(n_samples, n_channels)`, the recording layer writes a Zarr array with the wrong shape and replay won't match.

!!! tip "Fix"
    Stay sample-major in the source. The transpose to channels-first happens at one edge, inside `Stream.get_window()`.

See [Streams concept page](concepts/streams.md), [Add a custom source](how-to/add-a-source.md).

## Recording

### One-click sessions yield bad models

`iter_labeled_windows` uses every nonnegative labeled segment long enough for a window, including the first. One short trial per class may supply too few representative windows for a useful model.

!!! tip "Fix"
    Record one session with 6-10 button clicks, cycling Rest → Fist → Rest → Fist → … and holding each ~3 s. See [Record good training data](how-to/record-good-training-data.md).

### `sess.class_names = [...]` doesn't persist

Setting `class_names` as an attribute on the session object after the fact doesn't write it to `meta.json`. Pass the class names to `sess.save_meta(name, class_names=[...])` to persist them.

!!! tip "Fix"
    `RecordingControls` passes the class names through `app.start_recording`. For manual sessions, pass them to `save_meta`.

### Waiting for a `.mg.zip` save

`app.stop_recording()` normally finalizes and packs the session on a daemon thread. Returning from it does not mean the archive is ready. `App.run()` cleanup saves an open take inline and waits up to 30 seconds for saves already in progress.

!!! tip "Fix"
    Use `app.stop_recording(wait=True)` when the next step needs the finished archive. Successful saves go to `data/<ID>/recordings/<ID>_<YYYYMMDD-HHMM>_<what>.mg.zip`, or `predictions/` for a take started while predicting. Do not use a fixed sleep as completion evidence.

See [Recording concept page](concepts/recording.md), [Record and replay](how-to/record-and-replay.md), [Run headless](how-to/headless-mode.md).

## Pipeline (training and prediction)

### Predict thread won't fire

Several causes:

1. `pipeline.start_predicting()` was never called. Click Predict in the GUI or call it in headless mode.
2. `pipeline.model is None`. Train first or load a saved model with `pipeline.load_model = load_pickle` plus the Load Model button / explicit call.
3. Your `@pipeline.predict` returned a non-`dict` value. Non-dict returns are silently dropped and the previous prediction stays in `pipeline.predictions`.
4. The app is still in `idle`, `recording` or `training`, so prediction has not started. `start_predicting()` accepts either `idle` or `recording`; also check that input windows are nonempty and both decorators are wired.

!!! tip "Fix"
    Always `return {"...": ...}` from `predict()`. Check the state. A `print()` inside `predict()` confirms whether the predict thread is firing at all.

### "Save Model button is disabled"

`pipeline.save_model` is unset, so the button has no callable to invoke.

!!! tip "Fix"
    Set `pipeline.save_model = save_pickle` and `pipeline.load_model = load_pickle`. Both helpers are in `myogestic.ml`.

### "GPU contention" / training and predict don't run together

The state machine refuses entry to `training` while `predicting`, and vice versa, to avoid
PyTorch CUDA memory contention. This exclusion is intentional and is not a bug.

!!! tip "Fix"
    Click Predict again after training finishes.

### `extract()` shape mismatch after retraining

Your `extract()` returns a different feature dimensionality from what the trained model expects. Check whether `WINDOW_MS` or `HOP_MS` changed between training and predicting.

!!! tip "Fix"
    Keep extract's return shape stable. If you change feature engineering, retrain.

See [Pipeline concept page](concepts/pipeline.md), [Add a custom model](how-to/add-a-model.md).

## Widgets and the UI

### Widget appears in the wrong place / overlaps another

`Grid` cells use Python slicing conventions. `grid[0:6, 1:3]` is rows 0-5 inclusive, cols 1-2 inclusive. Two widgets occupying overlapping cells will draw on top of each other.

!!! tip "Fix"
    Assign each widget its own cells. The grid silently allows overlaps.

### Widget state shared accidentally between instances

Two `SignalViewer("emg")` instances share state because their default identity is the stream name. Give them distinct `widget_id` values to view the same stream independently.

!!! tip "Fix"
    Match the widget's keying convention. Signal viewers default to the stream name; template inspectors require an explicit `widget_id`.

### Widget calls work in `@app.ui` but not elsewhere

Dear ImGui is not thread-safe. Call widgets inside `@app.ui` on the render thread. Calling them from the predict thread or a custom thread will crash or silently do nothing.

!!! tip "Fix"
    Pass data into the widget via `ctx` or your own object. Don't call ImGui from non-render threads.

See [Widgets concept page](concepts/widgets.md), [Add a custom widget](how-to/add-a-widget.md).

## Outputs

### An outlet sends old values forever { #output-sends-old-values-forever }

`Outlet.push(data)` writes to a *latest-value slot*. The output thread sends whatever's in the slot every `1/hz`. If you stop pushing but the slot still holds the last value, the same value gets re-sent forever.

!!! tip "Fix"
    This is the latest-wins contract. Each push replaces the latest value; values are never
    queued. For one send per event, implement a queue-based output by overriding the daemon-thread loop.

### The output thread falls behind { #output-thread-falls-behind }

Your `_send` takes longer than `1/hz` per call. The daemon thread can't keep up.

!!! tip "Fix"
    Lower `hz`, or cache or pre-compute slow work outside `_send`.

See [Publish a data stream](how-to/add-an-output.md).

## Virtual Hand Interface

### "VHI launcher button errors" / `FileNotFoundError`

Install VHI where `virtual_hand()` looks by default, at `<repo>/tools/MyoGestic-VHI` in a git checkout or `<user_data>/myogestic/vhi` elsewhere. Before calling `Popen`, the launcher raises a `FileNotFoundError` with the exact install command.

!!! tip "Fix"
    Install the packaged binary once:

    ```bash
    python -m myogestic.tools.install_vhi          # latest release
    # or after `pip install myogestic`:
    myogestic-install-vhi
    ```

    See [Install the Virtual Hand](how-to/install-vhi.md) for the full installer reference, `--tag` pinning, and the macOS Gatekeeper note.

    To run VHI from the Godot source project, set `$VHI_PATH` to your checkout and `$GODOT_BIN` to a Godot 4.x binary:

    ```bash
    export VHI_PATH=$HOME/code/Virtual-Hand-Interface
    export GODOT_BIN=$HOME/Applications/Godot.app/Contents/MacOS/Godot
    ```

    For an optional hand in your own app, use `vhi.launchable()` to return an empty process list when it cannot be launched. The start-here apps can still connect to an already running hand; they report when no hand is available.

### VHI hand looks twitchy

You're pushing raw model output. VHI moving at 32-50 Hz amplifies any per-tick jitter.

!!! tip "Fix"
    Pair every VHI integration with a [`PostProcessor`][myogestic.widgets.PostProcessor] block. It defaults to the 1€ filter, which is usually suitable. Pass `timestamp=time.monotonic()` into the filter so it computes real elapsed dt.

### VHI hand drifts after retraining

The `OneEuroFilter` keeps smoothing history across training boundaries; the first few frames after a retrain blend the new model's first prediction with the old model's tail.

!!! tip "Fix"
    Call `pose_filter.reset()` or the PostProcessor version inside `@pipeline.train` before returning the new model.

See [Integrate the Virtual Hand](how-to/integrate-vhi.md), [Post-process predictions](how-to/post-process-output.md).

## Threading and performance

### `time.sleep` in `@pipeline.predict` delays predictions

It blocks the predict thread. The framework already paces ticks at `predict_hz`.

!!! tip "Fix"
    Do not sleep in `@pipeline.predict`. Lower `predict_hz` or use a state machine that returns the previous prediction on stale ticks.

### Stale-tick warnings

Predict thread is firing faster than acquisition is producing new data. Stateful models check `last_ts` and short-circuit when the timestamp hasn't advanced.

!!! tip "Fix"
    Pass `last_ts` from `extract()` into your model. `emg, ts = stream.get_window(); last_ts = float(ts[-1]) if ts.size > 0 else None`. A stateful model should check it and return the previous prediction when the timestamp hasn't advanced.

See [Threading concept page](concepts/threading.md).
