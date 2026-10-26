# EMG classification (CatBoost)

End-to-end walkthrough of [`examples/synthetic/emg_classification.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/emg_classification.py): synthetic 8-channel EMG → RMS+MAV features (from [`myogestic.recipes.features`][myogestic.recipes.features]) → CatBoost binary classifier, with optional LSL pose and gRPC movement outputs to VHI.

!!! note "Code below is included from the example"
    The Python blocks in this walkthrough are pulled verbatim from the example file via snippet includes, so they can't drift from the runnable script.

End to end, zero classes besides the framework's `App` and `Pipeline`.

## Run it first

One terminal, then launch **EMG Generator** and connect its stream in the **Connect** step.

```bash
uv run python examples/synthetic/emg_classification.py
```

VHI is optional: recording, training and prediction all work without it or the `grpc` extra. The Virtual Hand row shows **Not running** until you connect it. To drive the 3D hand, [install the Virtual Hand](../how-to/install-vhi.md), run with `uv run --extra grpc python examples/synthetic/emg_classification.py`, and click **Connect** on its row. The app first checks for an existing service and launches the hand only if none answers.

## What you should see

![EMG classification demo running](../images/gui-overview.png){ loading=lazy }

The header carries **Connect → Record → Train → Predict**, the participant and session state. The signal and **Simulated EMG** controls stay visible beside the active step, with participant sessions and an activity log below. At narrow widths the same cards stack vertically.

Connect has the generator launcher, stream connection and optional Virtual Hand row. **Hand movements…** opens its full movement palette. Predict shows class probabilities, the output filter and **Sent to the hand**, with separate LSL `fist` and gRPC `gesture` values.

## The walkthrough

The whole script is structured top-to-bottom: imports → outputs → constants → app setup → callbacks → layout → `app.run()`. Read it in that order.

### 1. Outputs and side-channels

[`SimulatorControls`][myogestic.widgets.SimulatorControls] lazily publishes the generator's `EMG_Control` stream. Its persistent **Rest** and **Fist** chips preview either signal without changing a recording label. The Record step's class buttons also select the control-hand movement when a hand is connected; starting a take restores the signal for its selected label.

```python
--8<-- "examples/synthetic/emg_classification.py:poses"
```

The example declares two outputs in `examples/controls/classification_grpc.toml`. `fist` is a continuous activation: `0` for Rest and `1` for Fist, fanned out to the predicted hand's digits with negative thumb abduction for opposition. `gesture` is the matching movement name, sent to the control hand over gRPC after the configured `debounce_s = 0.1` settles a class change. The target's manifest supplies its controls and streams; nothing is resolved until the optional hand is connected, and gRPC clients are created only on that request.

### 2. The output filter

```python
--8<-- "examples/synthetic/emg_classification.py:filter"
```

[`PostProcessor`][myogestic.widgets.PostProcessor] is the post-processing widget - exposes a UI panel and is callable. We hand it to the bus as `ControlBus(..., smoothing=output_filter)` so it runs once per frame before any target sees it, and render its panel inside `@app.ui`.

See [Post-process predictions](../how-to/post-process-output.md) for tuning.

### 3. Feature set

```python
--8<-- "examples/synthetic/emg_classification.py:features"
```

[`FeatureSelector`][myogestic.widgets.FeatureSelector] holds a menu of named feature functions - the reference `rms`/`mav`/`wl`/`var`/`zc` from [`myogestic.recipes.features`][myogestic.recipes.features], plus any of your own callables - and renders a panel to toggle them live. Calling it, `features(window)`, runs every active feature over the channels-first window and stacks the results into one flat vector. `default=["RMS", "MAV"]` ticks two on at startup.

### 4. App, stream, pipeline

```python
--8<-- "examples/synthetic/emg_classification.py:setup"
```

The stream window is 0.2 s - every `extract()` call sees the most-recent 0.2 s of EMG, channels-first as `(n_channels, n_samples)`. The buffer is 60 s so [`SignalViewer`][myogestic.widgets.SignalViewer] shows a longer history than the prediction window.

### 5. `extract` - same code for training and live predict

```python
--8<-- "examples/synthetic/emg_classification.py:extract"
```

`features(windows["emg"])` runs every active feature over the window (channels-first `(n_channels, n_samples)`) and returns one flat vector. The same function is invoked from inside `train()` (over recorded windows) and on the predict thread (over live windows), so training and inference always see identical features.

### 6. `train` - slice sessions, featurize, fit

```python
--8<-- "examples/synthetic/emg_classification.py:train"
```

[`iter_labeled_windows`][myogestic.session.iter_labeled_windows] does all the session-loading, label-track walking, and overlapping-window slicing - see [Record and replay](../how-to/record-and-replay.md). We just call `extract()` on each window.

The validation up front (`is_empty`, `len(data.classes) < 2`) gives the user actionable error messages - the framework's design principle "errors tell you what to write." If you forget to tick a session in [`SessionManager`][myogestic.widgets.SessionManager], you'll see "No sessions selected. Load some and tick the checkboxes." in the status panel.

### 7. `predict` - classify, smooth the pose and command movements

```python
--8<-- "examples/synthetic/emg_classification.py:predict"
```

The class index chooses both values from `CTRL_VALUES` and `CLASSES`. One bus frame carries `{"fist": 1.0, "gesture": "Fist"}` for a fist prediction. The bus smooths the continuous activation and debounces the discrete movement; LSL carries the predicted-hand pose and gRPC carries control-hand class changes. Palette clicks use `bus.select("gesture", state)` to send an immediate movement and rebase that trigger.

Without a connected bus, `predict` returns class and probabilities normally. It never tries to bind: capability discovery is a blocking RPC, so the Connect row runs it on a background worker. The returned `hand` dict, when present, supplies the values shown under **Sent to the hand**.

### 8. Layout

```python
--8<-- "examples/synthetic/emg_classification.py:layout"
```

A responsive [`Grid`][myogestic.Grid] keeps the header and status in bare rows. The wide layout places the live signal beside the active step and sessions; the narrow layout stacks them. Each active step is one card with one header. `SessionManager` returns a `TrainingData` instance; assigning it to `pipeline.training_data` connects the selected participant takes to `train()`.

### 9. The actual experiment loop

In the GUI:

1. In **Connect**, launch **EMG Generator**, then connect **TestEMG1**.
2. Optionally connect **Virtual Hand**; **Hand movements…** opens its palette.
3. Set a participant in the header and open **Record**.
4. Select **Rest**, record a take for about 3 s, then stop. Repeat with **Fist** and collect a few takes of each. A connected hand's recording gate disables its local keyboard during each take.
5. Select the participant's takes in **Sessions**, open **Train**, choose features and train.
6. Open **Predict** and start predicting. Use **Simulated EMG** to switch between Rest and Fist; the predicted class updates with or without the optional hand.
7. With a hand connected, inspect the smoothed `fist` and debounced `gesture` values under **Sent to the hand**.

Tune the **One Euro** sliders in the filter panel while predicting to feel the lag/responsiveness trade-off in real time.

## Variations

- **More classes**: extend `CLASSES` and `CTRL_VALUES`, provide distinguishable generator patterns or real signals, and use movement names the hand advertises. The same prediction callback sends the selected activation and movement name.
- **Different feature set**: swap RMS/MAV for whatever your domain needs. Keep `extract()`'s return shape consistent across training and live.
- **Different model**: replace `catboost_classifier` with sklearn / XGBoost / PyTorch. See [Add a custom model](../how-to/add-a-model.md) for the patterns.
- **Real hardware**: replace `LSLSource("TestEMG1")` with a real source - see [Add a custom source](../how-to/add-a-source.md).
