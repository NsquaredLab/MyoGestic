---
title: "Examples directory"
---
Every runnable example under [`examples/synthetic/`](https://github.com/NsquaredLab/MyoGestic/tree/main/examples/synthetic),
what it teaches, and what's tweakable, plus the complete protocols in
[`examples/start_here/`](https://github.com/NsquaredLab/MyoGestic/tree/main/examples/start_here).
All can run without hardware. The EMG demos launch
`myogestic.tools.emg_generator` from their connection controls; the array
viewers and `start_here` protocols also offer in-process synthetic sources.

For VHI integration, install once with `python -m myogestic.tools.install_vhi`
as described in [Install the Virtual Hand](../how-to/install-vhi.md). The apps offer launch controls when a binary is available. Otherwise, run
a compatible hand separately and bind to it, or use the app without it.

## Running

```bash
uv sync --extra examples              # core demos
uv sync --extra examples --extra grpc # adds the gRPC-control examples
uv run --extra examples --extra grpc python examples/synthetic/<name>.py
```

### From VS Code

Use Run and Debug with the committed `.vscode/launch.json`. No setup is required.
The first entries run your own files.

* Open your app's `.py` and pick Run current MyoGestic app or Debug current
  MyoGestic app to stop on breakpoints.
* Open your control map's `.toml` and pick Inspect a TOML control map. It validates
  the file, resolves it against a running target if there is one, and prints every alias,
  group member, weight and gate.

Open this checkout in VS Code to load its `launch.json`. You can run files outside the
repository. The interpreter uses this checkout's `.venv`; the working directory follows
your file, so control maps beside your app resolve as they do from the shell.

The entries below those are conveniences for this repository's own examples, the
walkthrough and the VHI prerequisites. Each name states its requirements, such as a display, a
running Virtual Hand, or someone watching the hand.

## The control file

Each example maps its own output names onto controls the target declares, in a file of
its own under [`examples/controls/`](https://github.com/NsquaredLab/MyoGestic/tree/main/examples/controls).
A ready-to-copy declaration ships at
[`examples/controls/hand.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/hand.toml)
with signed continuous DOFs, a discrete grasp state, a one-way range and a `debounce_s`
stability gate. It shows mapping-first short forms alongside explicit tables.
[`examples/controls/myocontrol.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/myocontrol.toml)
declares the model's `prediction` alias. The separate `myocontrol_operator.toml` declares
the operator's `control` alias. Each link binds only the hand it drives. A map
listing a control the app never drives shows a row in its panel that never moves.

To watch it load and drive a hand end to end:

```bash
uv run --extra grpc python tools/inspect_control.py
```

The tool prints different sections for a running v2 hand and for no running hand. It can run without a hand; binding
requires VHI 2.0 or newer because pre-2.0 builds provide no manifest.

<a id="start-here-the-control-map-studio"></a>

## Control-map studio

Start here to drive controls without a model, EMG or training. Use one slider per name in
[`examples/controls/playground.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/playground.toml),
next to an editor for the file itself.

```bash
uv run --extra grpc --extra keyboard python examples/synthetic/control_map_studio.py
```

Launch VHI, press Connect, drag a slider. Then change the thumb's `weight` in the
file and save. The file watcher updates the panel and sliders automatically.
Or use the editor panel, which lists what every connected target exports so a control can
be selected, and refuses a map that would not resolve before it can be
saved. The TOML stays the source of truth either way.

The same file drives two targets, bending a finger and pressing a key.

```toml
[dofs]
close = "vhi.prediction.index"          # a finger
walk  = "keyboard.hold.letter.w"        # held while the control is above 0.5
fire  = "keyboard.tap.edit.space"       # one press per crossing
```

A key is an ordinary two-state control, so the threshold, the debounce and the fan-out are
the same machinery the hand uses. See [Keyboard](../api/keyboard.md). Key sending starts
disarmed, because a resolved map types into whatever window has focus.

The editor shows each control as a card with its name, probability toggle, weighted targets,
and activation sliders. Its header offers Reload, Save as, and a TOML toggle; TOML appears beside
the cards when there is room and below them in narrow panels. The single Save action applies
pending TOML edits before writing, and a disk conflict asks which version to keep.

The editor is a widget, so it works in your own app too:

```python
from myogestic.widgets import ControlMapEditor

editor = ControlMapEditor(pathlib.Path("my_controls.toml"), client=vhi.control_client())


@app.ui
def ui(ctx):
    if editor.ui():  # True on the frame a save lands
        rebuild_my_bus()
```

To see it with no target at all:
`uv run python examples/panels/control_map_editor.py`.

## The examples

### `electrode_grids.py` - compare electrode arrays

One in-process 256-channel stream split into four 64-channel electrode arrays,
each in its own `SignalViewer` below the app header. The 2 × 2 tiles start on one
manual amplitude range, so a quieter array stays visibly quieter. No hardware or
external generator is needed.

```bash
uv run python examples/synthetic/electrode_grids.py
```

Set `Y_RANGE` for the common amplitude scale, `WINDOW_S` for the
time window, and `initial_channels` for each tile's opening selection. A unique
`widget_id` keeps selections independent; `channel_scope` keeps All, None,
Invert and the spatial selection grid inside that tile's array. Expand a tile's
controls to edit channels, and keep the same manual range when comparing arrays.

### `electrode_overview.py` - spatial RMS maps

Five 64-channel arrays from one in-process 320-channel source, with a
shared colour range and a signal viewer for detail. One contact on IN3 is
silent so there is a visible fault to find.

```bash
uv run python examples/synthetic/electrode_overview.py
```

Set `RMS_MS` for integration time and `_scale` for the
amplitude of each array or contact.

### `high_channel_viewer.py` - a high-channel LSL viewer

Launch a 256-channel generator, connect TestEMG256, and inspect the
stream with `SignalViewer`. This app has no recording or model step.

```bash
uv run python examples/synthetic/high_channel_viewer.py
```

Set `N_CHANNELS`, `FS` and the stream buffer duration.

### `reference_target.py` - a separate remote target

A headless gRPC service with six continuous `vhi.prediction.*` addresses.
It reads one LSL stream per address and holds the latest values. Drive it
from a second process using a control map; it generates no EMG itself.

```bash
uv run --extra grpc python examples/synthetic/reference_target.py
```

Edit `ADDRESSES` and the application of each received value.
See [Your first remote target](your-first-remote-target.md).

### `my_device.py` - drive your own hardware

An in-process target with three lines to fill in for control names, hardware commands and
release. `send` prints commands when run without hardware,
so you can watch the bus clip an out-of-range value, replace a `NaN` with rest, and return
every control to neutral before teardown.

```bash
uv run python examples/synthetic/my_device.py
```

Fill in the three numbered lines. See
[Drive your own device](../how-to/add-a-target.md).

### `my_session_app.py` - copy your own session app

A small Connect / Record / Train / Predict app with the shared header, persistent signal
and simulator, sessions, activity log and status bar. It launches synthetic EMG and fits
a NumPy nearest-centroid model, so it runs without hardware or an ML package.

```bash
uv run python examples/synthetic/my_session_app.py
```

Edit the four numbered sections for gesture classes, features, training and
prediction. Choose a participant in the header, record each gesture and select the takes
before training. Add your device's output call in `predict` when you are ready.

### `servo_hand.py` - the same shape, with a real mechanism

Six servos on a serial port. `hand.thumb` drives two of them on different transfer functions,
because a real thumb opposes as it flexes. The target handles that coupling. Do not put it in a control map. Runs with no hardware; its assertions check the exact bytes.

```bash
uv run python examples/synthetic/servo_hand.py
```

Set `SERVOS` for your travel in degrees, and pass a real
`serial.Serial(...)` as `port`.

### `emg_classification.py` - start here

An 8-channel synthetic EMG binary classifier using NumPy RMS+MAV features and CatBoost. It runs fully without the Virtual Hand;
Connect shows the hand as Not running until you choose to connect it. This is
the reference first read, and its line-by-line companion is the
[EMG classification tutorial](emg-classification.md).

The optional hand uses two outputs in `classification_grpc.toml`. `fist` streams a
smoothed pose to the predicted hand over LSL, while `gesture` sends each settled
class change to the control hand over gRPC (`debounce_s = 0.1`). The compact
Virtual Hand row in Connect opens the movement palette; Predict shows the last
values under Sent to the hand. Connecting the hand needs the `grpc` extra:
`uv run --extra examples --extra grpc python examples/synthetic/emg_classification.py`.

```bash
uv run --extra examples python examples/synthetic/emg_classification.py
```

Swap `rms`/`mav` from `myogestic.recipes.features`
for your own feature, change `CLASSES`, replace CatBoost with any
sklearn-shaped classifier.

### `emg_regression.py` - continuous-target regression

CatBoost regressor maps EMG features to a 5-DOF kinematic target.
Recorded with a discrete DOF, a held state that snaps to and holds each movement's end
pose. Regression needs the trainee to physically reach and hold the target. Sweeping
through a cycle does not provide that static target. Uses RMS + MAV + waveform length features.

```bash
uv run --extra examples --extra grpc python examples/synthetic/emg_regression.py
```

Add or remove DOFs in the kinematic target; swap
CatBoost for sklearn's `MultiOutputRegressor` to compare model families.

### `emg_regression_raulnet.py` - RaulNet via Lightning

The same regression flow with RaulNetV17, a PyTorch Lightning CNN
that takes a sliding-RMS feature stack `(channels, time)` and predicts
5-DOF kinematics. Uses `Trainer(precision="32-true")` because TorchScript
backward requires fp32, plus ModelCheckpoint and per-epoch logs streamed
to the pipeline panel's log window, which supports autoscroll and pop-out.

```bash
uv run --extra examples --extra grpc python examples/synthetic/emg_regression_raulnet.py
```

Change `RaulNetV17` hyperparameters, increase the
window size, or switch to Apple Silicon MPS or CUDA. The training callback
streams per-epoch logs on either device.

### `emg_32ch_multi_model.py` - multi-classifier comparison

32-channel EMG with a selectable classifier. Compare CatBoost,
sklearn LDA, sklearn SVM, etc. live without re-running the script. Adds
the Save/Load model panel so a tuned model survives a restart, and
the pose-lookup pattern for mapping multiple gestures to control poses.
Every card can pop out into its own window; the training log can float independently.

```bash
uv run --extra examples --extra grpc python examples/synthetic/emg_32ch_multi_model.py
```

Plug another classifier into the model registry, add
more gestures to the pose-lookup, increase the channel count (the
generator scales to any `--channels`).

<a id="vhi_control_handpy---the-operators-hand-not-the-models"></a>

### `vhi_control_hand.py` - pose the operator's hand

An example that drives `vhi.control.pose.*` instead of `vhi.prediction.*`: sliders
pose the operator's hand. `RemoteTarget` publishes one one-channel LSL stream
per address in the map, using the same transport as the prediction controls. VHI
reads those values instead of animating its own movements while the streams are
present. Point the same file at `vhi.prediction.*` and the example drives the other
hand, unchanged.

```bash
uv run --extra grpc python examples/synthetic/vhi_control_hand.py
```

Add a mapping to
[`examples/controls/control_hand.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/control_hand.toml)
to add a slider. No other code changes are needed.

### `start_here/myocontrol.py` - the whole loop as a protocol

A session application combines the preceding demos for use with a participant. A device
dropdown replaces a named source, and Rest/Fist trials are shown
on the control hand and saved as `.mg.zip` takes in `data/<ID>/recordings/`,
and a Train step that builds either a classifier or a regressor. The header
shows Connect → Record → Train → Drive; prediction takes and saved models
go in `data/<ID>/predictions/` and `data/<ID>/models/`.
The switch chooses what the next Train builds. The fitted model stores its mode, so
changing the switch leaves a loaded model unchanged. A class index cannot enter the
regression branch by changing the switch. One control map serves both modes.
`POSES` maps each class to a constant hand activation in the same units as regression
outputs. Downstream code receives the same kind of value and cannot distinguish the modes.

Two maps declare aliases named for the hands they drive. `prediction` sends
`vhi.prediction.*` values each prediction tick. Gesture buttons or a Follow run
send `control` values to `vhi.control.pose.*`. Both hands receive the same kind of value
from different sources. They are allowed to disagree. Compare them to assess prediction
against the operator's command.

```bash
uv run --extra examples --extra grpc python examples/start_here/myocontrol.py
```

To bind VHI, press Connect on the Virtual Hand row in Connect. Nothing binds before that
request. Recording, training and prediction also run without VHI; `predict` pushes nothing
until the hand is bound.

Set `CLASSES` and `POSES` together. Each class names an activation level;
the module rejects mismatched lists at import. The names are yours;
nothing downstream matches them against VHI's vocabulary. Also the ticked features, and
`iterations` on either estimator.

### `start_here/pong.py` - the first signed example

Myocontrol uses `0..1` hand activation, with rest at the bottom of the range. Pong uses
signed `[-1, +1]` wrist commands, with Down at `-1`. Down is a direction. It is not the absence of Up. A wrist is a bidirectional DOF. A one-way fit never sees the negative direction.
One model emits one number to move a [`PongTask`][myogestic.widgets.PongTask]
paddle, with `+1` at the top of the court. Rallies against the opponent paddle reward
graded contraction. A trapezoid rewards tracking; a gesture classifier supplies no
continuous reward.

Serve sits inside the court; Space also starts a rally. The court shows a serif
score and a signed command meter, or an effort meter during cursor tracking. The header
shows the rally count and Stop; court dimensions follow the UI scale.

Two ways to record the training set, both on the Record step. Follow the cursor
runs a [`Pursuit`][myogestic.tracking.Pursuit] block. The participant chases a ghost paddle,
and the cursor is recorded beside the EMG on the `target` stream. Down / Rest / Up
buttons offer the older three-class protocol. Prefer cursor tracking. Three cued classes
provide only three distinct target values, so a fitted tree ensemble remains a three-class
model regardless of its name. It is inactive below about 30 % effort and non-monotonic. Dense target levels cut CatBoost
error at intermediate efforts 14x. A cued staircase of eleven holds scores at least
as well; the number of distinct levels accounts for the improvement. A linear model
gains nothing because least squares draws a straight line through three points. Cursor feedback
helps participants reach intermediate efforts such as 0.6 without knowing what 0.6 feels like.
[Record for proportional control](../how-to/record-for-proportional-control.md) is the
protocol on its own, with the numbers.

The Train step offers Proportional, Regression and Classification, and Proportional is
the default because a regressor fitted to raw features can learn whichever cue is louder.
Loudness does not specify direction. The CatBoost fit shipped with this example learned
"louder = Down", so stronger contraction moved the paddle the wrong way.
`Proportional` is
[`directional_decoder`][myogestic.recipes.estimators.directional_decoder], which estimates
*how much* and *which way* separately and multiplies them. Both other modes still train and
run. The fitted model stores its mode; the switch takes effect on the next Train.
Cursor and cued takes train together because each class maps to a constant signed target.

```bash
uv run --extra examples --extra grpc python examples/start_here/pong.py
```

The Virtual Hand mirrors the command. The paddle follows a float even if VHI never answers.
The single alias in
[`examples/controls/pong.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/pong.toml)
sends the same float to the wrist when the Virtual Hand is bound in Connect. Its `weight = -1.0` is
the anatomical mapping. It does not correct a sign error. Flexion is palm-ward, which is down on a pronated forearm. With no hardware at all, the Synthetic wrist (dummy follows the cursor) source drives an agonist/antagonist pair. It follows the
cursor during a block; outside a block, arrow keys or the mouse set its drive.

Set `CLASSES` and `POSES` together, as in `myocontrol.py`. Keep a
negative entry, since a table that never goes below zero pins the paddle to the top half.
Difficulty is Easy / Fair / Hard under Opponent on the Play step, which is `OPPONENTS` in the file. It sets the
opponent's top speed as a multiple of `ball_speed`. Changing it clears the court and score, because a score won against a slower paddle
should not carry over. `PongTask(paddle_size=...)` and
`ball_speed` can also be changed in code.

### `start_here/force_ramps.py` - a protocol with no model in it

This app trains no model. It records the standard HD-EMG isometric protocol with rest,
ramp, hold, ramp down and recovery for later analysis.
[`TrackingTask`][myogestic.widgets.TrackingTask] draws the trapezoid and the live force
together, so the participant can track the target. Capture Zero and MVC to enable Start and
compare force with the %MVC target. Raw device counts and a %MVC target cannot be
compared without both calibrations. The two calibration values are saved in `extras`;
the target has its own stream, so tracking error can be computed from the archive.

```bash
uv run python examples/start_here/force_ramps.py
```

A synthetic load cell sits in the device list beside the real amplifiers, with an Effort
slider for manual tracking without hardware. Nothing follows the target automatically. See [Track a force target](../how-to/track-a-force-target.md) for the
wiring, and `examples/panels/tracking_task.py` for the widget on its own.

Set the `Trapezoid` segment durations in seconds, `level_pct`, repetition count
and `channel=` for the transducer's auxiliary channel.

## Choosing where to start

* Getting started - [Anatomy of an app](../anatomy.md) →
  [EMG classification tutorial](emg-classification.md) →
  `emg_classification.py`.
* I have a device to drive - `my_device.py`, a complete target with three lines left for
  you, then [Drive your own device](../how-to/add-a-target.md). `servo_hand.py` is the same
  shape for six servos with a coupled thumb and a wire format.
* Want gRPC discrete control - connect the optional hand in `emg_classification.py`.
* Regression flow -
  [EMG regression with VHI tutorial](emg-regression-with-vhi.md) →
  `emg_regression.py` → swap in `_raulnet` for the deep variant.
* Comparing models - `emg_32ch_multi_model.py`.
* Multi-monitor / docking - `emg_32ch_multi_model.py`.
* Posing the control hand for setup or labelling - `vhi_control_hand.py`.
* A session protocol - `start_here/myocontrol.py`, which is the
  classification and regression flows in one application that names no hardware.
* A bidirectional DOF or a task that sustains participant engagement - `start_here/pong.py`, the
  signed paddle example. Down is `-1`, and the rally is what trains graded control.
* Recording a protocol without training a model - `start_here/force_ramps.py`,
  isometric trapezoids with the calibration that makes them readable later.
* Custom extension point - skip the examples and read the
  [guides](../how-to/index.md) - each is a recipe for one
  extension point.
