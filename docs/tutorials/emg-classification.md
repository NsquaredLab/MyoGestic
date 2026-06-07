# EMG classification (CatBoost)

End-to-end walkthrough of [`examples/synthetic/emg_classification.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/emg_classification.py): synthetic 8-channel EMG → RMS+MAV features (from [`myogestic.recipes.features`][myogestic.recipes.features]) → CatBoost binary classifier → smoothed hand pose → VHI.

!!! note "Code below is included from the example"
    The Python blocks in this walkthrough are pulled verbatim from the example file via snippet includes, so they can't drift from the runnable script.

End to end, zero classes besides the framework's `App` and `Pipeline`.

## Run it first

One terminal, then click **Launch** in the GUI's [`process_launcher`][myogestic.widgets.process_launcher] panel to spawn the synthetic EMG generator.

```bash
uv run python examples/synthetic/emg_classification.py
```

VHI is optional for this demo - the predicted hand pose is pushed over an LSL outlet whether or not VHI is listening. To see the 3D hand, install it once with `python -m myogestic.tools.install_vhi` (see [Install the Virtual Hand](../how-to/install-vhi.md)) and run it alongside.

## What you should see

![EMG classification demo running](../images/gui-overview.png){ loading=lazy }

A 3-column window:

- **Right two columns**: live EMG signal viewer.
- **Left column, top to bottom**: logo, EMG-generator launcher, recording controls, feature selector, session manager, pipeline panel, output-filter panel, prediction label.

Click **Launch** on **EMG Generator** → synthetic 8-channel signal flows. If you started VHI separately, the predicted pose drives its 3D hand.

## The walkthrough

The whole script is structured top-to-bottom: imports → outputs → constants → app setup → callbacks → layout → `app.run()`. Read it in that order.

### 1. Outputs and side-channels

```python
from myogestic.tools.emg_generator import control_outlet

ctrl_outlet = control_outlet()
```

`control_outlet()` is the one-liner over the boilerplate `StreamOutlet(StreamInfo(name="EMG_Control", stype="Control", n_channels=1, ...))` - see [`myogestic.tools.emg_generator.control_outlet`](../api/core.md). The synthetic generator listens on `EMG_Control` for which class pattern to emit. Click "Fist" in the button strip → `ctrl_outlet.push_sample([1.0])` → generator switches to pattern 1.

```python
--8<-- "examples/synthetic/emg_classification.py:poses"
```

VHI consumes a 9-vec pose; we hand-define the two target poses (rest and full fist). The model just chooses between them.

### 2. The output filter

```python
--8<-- "examples/synthetic/emg_classification.py:filter"
```

[`FilterControl`][myogestic.widgets.FilterControl] is the post-processing widget - exposes a UI panel and is callable. We'll wire the call inside `predict()` and the panel inside `@app.ui`.

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

The stream window is 0.2 s - every `extract()` call sees the most-recent 0.2 s of EMG, channels-first as `(n_channels, n_samples)`. The buffer is 60 s so [`signal_viewer`][myogestic.widgets.signal_viewer] shows a longer history than the prediction window.

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

The validation up front (`is_empty`, `len(data.classes) < 2`) gives the user actionable error messages - the framework's design principle "errors tell you what to write." If you forget to tick a session in [`session_manager`][myogestic.widgets.session_manager], you'll see "No sessions selected. Load some and tick the checkboxes." in the status panel.

### 7. `predict` - classify, look up pose, smooth, push

```python
--8<-- "examples/synthetic/emg_classification.py:predict"
```

The pose lookup is a hardcoded `if/else` - small enough not to need a class table. Smoothing happens *after* pose lookup so the user sees smooth blends between rest and fist as the classifier flips. The dict return goes to `pipeline.predictions` for any widgets that want to display class probabilities.

!!! tip "Why filter the pose, not the class index?"
    OneEuro expects a continuous vector. Class indices are integers, smoothing them is meaningless. Smoothing the pose vector lets the hand fade between `HAND_REST` and `HAND_FIST` cleanly even if the classifier flips on the boundary.

### 8. Layout

```python
--8<-- "examples/synthetic/emg_classification.py:layout"
```

An 8×3 grid: the signal viewer fills the right two columns, and the left column stacks eight widget calls top-to-bottom - logo, EMG-generator launcher, recording controls, feature selector, session manager, pipeline panel, output-filter panel, prediction label. Every panel is a plain function call. `session_manager` returns a `TrainingData` instance - assigning it to `pipeline.training_data` is the only line that connects "what's ticked in the UI" to "what `train()` will see."

### 9. The actual experiment loop

In the GUI:

1. Click `Launch` on **EMG Generator** → live signal appears.
2. (Optional) start VHI separately → its 3D hand mirrors the predicted pose.
3. Click the **Rest** button → generator emits the rest pattern.
4. Click **Record** → start saving to `sessions/<timestamp>/`.
5. Hold rest for ~3 s, click **Fist**, hold fist ~3 s, click **Rest**, hold rest ~3 s, click **Fist**… (cycle-style - see [Record and replay](../how-to/record-and-replay.md)).
6. Click **Stop**.
7. Repeat for a few cycles.
8. Tick all sessions in **session_manager**.
9. Click **Train** → console prints `[train] N windows from M sessions ... done - accuracy on train: ~99%`.
10. Click **Predict** → VHI hand follows your button clicks live.

Tune the **One Euro** sliders in the filter panel while predicting to feel the lag/responsiveness trade-off in real time.

## Variations

- **More classes**: bump `CLASSES`, `CTRL_VALUES`, `--classes`, and add new `HAND_*` poses. The `predict` `if/else` becomes a dict lookup.
- **Different feature set**: swap RMS/MAV for whatever your domain needs. Keep `extract()`'s return shape consistent across training and live.
- **Different model**: replace `catboost_classifier` with sklearn / XGBoost / PyTorch. See [Add a custom model](../how-to/add-a-model.md) for the patterns.
- **Real hardware**: replace `LSLSource("TestEMG1")` with a real source - see [Add a custom source](../how-to/add-a-source.md).
