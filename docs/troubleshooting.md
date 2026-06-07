# Troubleshooting

Symptom-first reference for the things that go wrong. Each entry: what you see, what's actually happening, and how to fix it.

The deep-dive concept and how-to pages have their own short "Common mistakes" admonitions that point back here.

## Streams and acquisition

### "buffer empty" or no data on the first read

`Stream.get_window()` returns an empty array because the acquisition thread hasn't received any chunks yet. Either the source isn't connected (`stream.info is None`), or the upstream LSL outlet hasn't started publishing.

!!! tip "Fix"
    In headless scripts, sleep ~2 s between `app.run` startup and your first `app.start_recording()` / first prediction. In GUI mode, click **Launch** on the EMG generator (or wait for hardware to warm up). Check `app.ctx.streams["emg"].info` is not `None` before trusting the buffer.

### Acquisition thread freezes

A blocking call inside the source's `read()` pauses the acquisition thread, which pauses ring-buffer updates, which delays prediction. Custom sources should poll non-blockingly (e.g. `pylsl.pull_chunk(timeout=0.0)`).

!!! tip "Fix"
    Audit your source for synchronous network reads, blocking I/O on serial lines, or anything else that holds the GIL longer than ~1 ms.

### Wrong shape from a custom source

If a Source subclass accidentally returns `(n_channels, n_samples)` instead of sample-major `(n_samples, n_channels)`, the recording layer writes a Zarr array with the wrong shape and replay won't match.

!!! tip "Fix"
    Stay sample-major in the source. The transpose to channels-first happens at one edge, inside `Stream.get_window()`.

See: [Streams concept page](concepts/streams.md), [Add a custom source](how-to/add-a-source.md).

## Recording

### One-click sessions yield bad models

A session with two label clicks (e.g. Rest + Fist) and a few seconds of data extracts exactly one usable trial after the framework's "skip first" heuristic. Classifiers see one window per class and underfit badly.

!!! tip "Fix"
    Cycle-style recording: one session with 6-10 button clicks (Rest → Fist → Rest → Fist → … hold each ~3 s). See the dedicated guide: [Record good training data](how-to/record-good-training-data.md).

### `sess.class_names = [...]` doesn't persist

Setting `class_names` as an attribute on the session object after the fact doesn't write it to `meta.json`. The class names persist only when passed as a kwarg: `sess.save_meta(name, class_names=[...])`.

!!! tip "Fix"
    `recording_controls` calls `app.start_recording` which handles this for you. Only relevant if you're constructing sessions manually.

### `.session.zip` truncated when script exits

`app.stop_recording()` kicks off a daemon thread that packs the session folder. If the script exits immediately, the zip may not finish.

!!! tip "Fix"
    Sleep 1-2 seconds after `stop_recording()` in headless scripts, or check `sessions/<timestamp>.session.zip` exists before exiting.

See: [Recording concept page](concepts/recording.md), [Record and replay](how-to/record-and-replay.md), [Run headless](how-to/headless-mode.md).

## Pipeline (training and prediction)

### Predict thread won't fire

Several causes:

1. `pipeline.start_predicting()` was never called. Click **Predict** in the GUI (or call it explicitly headless).
2. `pipeline.model is None`. Train first or load a saved model with `pipeline.load_model = load_pickle` plus the **Load Model** button / explicit call.
3. Your `@pipeline.predict` returned a non-`dict` value. Non-dict returns are silently dropped and the previous prediction stays in `pipeline.predictions`.
4. The state machine is stuck in `training` or `recording`. Check `app.ctx.state`.

!!! tip "Fix"
    Always `return {"...": ...}` from `predict()`. Check the state. A `print()` inside `predict()` confirms whether the predict thread is firing at all.

### "Save Model button does nothing"

`pipeline.save_model` is unset, so the button has no callable to invoke.

!!! tip "Fix"
    Set it explicitly: `pipeline.save_model = save_pickle` (and the same for `load_model`). Both helpers are in `myogestic.ml`.

### "GPU contention" / training and predict don't run together

By design. The state machine refuses to enter `training` while in `predicting` (and vice versa) so PyTorch CUDA streams don't fight for memory.

!!! tip "Fix"
    This isn't a bug. Click **Predict** again after training finishes.

### `extract()` shape mismatch after retraining

Your `extract()` returns a different feature dimensionality from what the trained model expects. Common cause: changed `WINDOW_MS` or `HOP_MS` between training and predicting.

!!! tip "Fix"
    Keep extract's return shape stable. If you change feature engineering, retrain.

See: [Pipeline concept page](concepts/pipeline.md), [Add a custom model](how-to/add-a-model.md).

## Widgets and the UI

### Widget appears in the wrong place / overlaps another

`Grid` cells use Python slicing conventions. `grid[0:6, 1:3]` is rows 0-5 inclusive, cols 1-2 inclusive. Two widgets occupying overlapping cells will draw on top of each other.

!!! tip "Fix"
    Don't share cells. The grid silently allows it.

### Widget state shared accidentally between instances

Two `signal_viewer(ctx, "emg")` calls share state because the key matches; that's intentional. If you want independent state, use different stream names or different `widget_id` arguments where the widget supports them.

!!! tip "Fix"
    Match the widget's keying convention. Some key by `stream_name` (signal viewers), others by `uid` (template inspectors).

### Widget calls work in `@app.ui` but not elsewhere

Dear ImGui is not thread-safe. Widget calls only work inside `@app.ui` (the render thread). Calling them from the predict thread or a custom thread will crash or silently do nothing.

!!! tip "Fix"
    Pass data into the widget via `ctx` or your own object. Don't call ImGui from non-render threads.

See: [Widgets concept page](concepts/widgets.md), [Add a custom widget](how-to/add-a-widget.md).

## Outputs

### Output sends old values forever

`Output.push(data)` writes to a *latest-value slot*. The output thread sends whatever's in the slot every `1/hz`. If you stop pushing but the slot still holds the last value, the same value gets re-sent forever.

!!! tip "Fix"
    This is the contract: latest-wins, not queued. For event-style streams (one send per event, not periodic), implement a queue-based output by overriding the daemon-thread loop.

### Output thread falls behind

Your `_send` takes longer than `1/hz` per call. The daemon thread can't keep up.

!!! tip "Fix"
    Lower `hz`, or move slow work outside `_send` (cache, pre-compute, etc.).

See: [Add a custom output](how-to/add-an-output.md).

## Virtual Hand Interface

### "VHI launcher button errors" / `FileNotFoundError`

VHI isn't installed at the location `virtual_hand()` looks at - by default `<repo>/tools/MyoGestic-VHI` in a git checkout or `<user_data>/myogestic/vhi` elsewhere. The launcher raises a `FileNotFoundError` with the exact install command rather than letting `Popen` fail silently.

!!! tip "Fix"
    Install the packaged binary once:

    ```bash
    python -m myogestic.tools.install_vhi          # latest release
    # or after `pip install myogestic`:
    myogestic-install-vhi
    ```

    See [Install the Virtual Hand](how-to/install-vhi.md) for the full installer reference, `--tag` pinning, and the macOS Gatekeeper note.

    For VHI **development** (running from the Godot source project), set `$VHI_PATH` to your checkout and `$GODOT_BIN` to a Godot 4.x binary:

    ```bash
    export VHI_PATH=$HOME/code/Virtual-Hand-Interface
    export GODOT_BIN=$HOME/Applications/Godot.app/Contents/MacOS/Godot
    ```

    Or accept that the launcher button errors at click time and use a different output (the bundled examples wrap `vhi.launcher()` in a try/except so the button stays visible regardless).

### VHI hand looks twitchy

You're pushing raw model output. VHI rendering at 32-50 Hz amplifies any per-tick jitter.

!!! tip "Fix"
    Pair every VHI integration with a [`FilterControl`][myogestic.widgets.FilterControl] block (1€ filter is the default and usually right). Pass `timestamp=time.monotonic()` into the filter so it computes real elapsed dt.

### VHI hand drifts after retraining

The `OneEuroFilter` keeps smoothing history across training boundaries; the first few frames after a retrain blend the new model's first prediction with the old model's tail.

!!! tip "Fix"
    Call `pose_filter.reset()` (or the FilterControl version) inside `@pipeline.train` before returning the new model.

See: [Integrate the Virtual Hand](how-to/integrate-vhi.md), [Post-process predictions](how-to/post-process-output.md).

## Threading and performance

### `time.sleep` in `@pipeline.predict` blocks everything

It blocks the predict thread. The framework already paces ticks at `predict_hz`.

!!! tip "Fix"
    Don't. Lower `predict_hz` or use a state machine that returns the previous prediction on stale ticks.

### Stale-tick warnings

Predict thread is firing faster than acquisition is producing new data. Stateful models check `last_ts` and short-circuit when the timestamp hasn't advanced.

!!! tip "Fix"
    Pass `last_ts` from `extract()` into your model: `emg, ts = stream.get_window(); last_ts = float(ts[-1]) if ts.size > 0 else None`. A stateful model should check it and return the previous prediction when the timestamp hasn't advanced.

See: [Threading concept page](concepts/threading.md).
