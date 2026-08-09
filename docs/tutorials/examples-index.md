# Examples directory

Every runnable example under [`examples/synthetic/`](https://github.com/NsquaredLab/MyoGestic/tree/main/examples/synthetic),
what it teaches, and what's tweakable, plus the complete protocols in
[`examples/start_here/`](https://github.com/NsquaredLab/MyoGestic/tree/main/examples/start_here).
All of them are hardware-free - the
`ProcessLauncher` panel spawns `myogestic.tools.emg_generator` for you,
so one terminal is enough.

For VHI integration, install once with `python -m myogestic.tools.install_vhi`
(see [Install the Virtual Hand](../how-to/install-vhi.md)). Without it,
the launcher button errors at click time and everything else still runs.

## Running

```bash
uv sync --extra examples              # core demos
uv sync --extra examples --extra grpc # adds the gRPC-control examples
uv run python examples/synthetic/<name>.py
```

### From VS Code

`.vscode/launch.json` is committed, so **Run and Debug** works without setting anything
up. It is written for **your own files first**:

* Open your app's `.py` and pick **Run current MyoGestic app** — or **Debug current
  MyoGestic app** to stop on breakpoints.
* Open your control map's `.toml` and pick **Inspect a TOML control map** — it validates
  the file, resolves it against a running target if there is one, and prints every alias,
  group member, weight and gate.

Your files do not have to live in this repository. The interpreter comes from this
checkout's `.venv`; the working directory follows your file, so a control map beside your
app resolves the way it does when you run it by hand. The only requirement is that this
folder is the one open in VS Code, since that is where VS Code reads a `launch.json`
from.

The entries below those are conveniences for this repository's own examples, the
walkthrough and the VHI prerequisites. Each name says what it needs — a display, a
running Virtual Hand, or someone watching the hand.

## The control file

Each example maps its own output names onto controls the target declares, in a file of
its own under [`examples/controls/`](https://github.com/NsquaredLab/MyoGestic/tree/main/examples/controls).
A ready-to-copy declaration ships at
[`examples/controls/hand.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/hand.toml)
— signed continuous DOFs, a discrete grasp state, a one-way range, and a `debounce_s`
stability gate, with the mapping-first short forms alongside the explicit table form.
[`examples/controls/myocontrol.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/myocontrol.toml)
declares the narrower thing an app should: only the two aliases it actually pushes. A map
listing a control the app never drives shows a row in its panel that never moves.

To watch it load and drive a hand end to end:

```bash
uv run --extra grpc python tools/inspect_control.py
```

That runs safely with no Virtual Hand at all, and prints a different section for a v2
build and nothing running — and it needs VHI 2.0 or newer, since a pre-2.0 VHI
has no manifest to resolve against.

## Start here: the control-map studio

The shortest path from a control map to something moving — no model, no EMG, no
training. One slider per name in
[`examples/controls/playground.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/playground.toml),
next to an editor for the file itself.

```bash
uv run --extra grpc --extra keyboard python examples/synthetic/control_map_studio.py
```

Launch VHI, press **Connect**, drag a slider. Then change the thumb's `weight` in the
file and save — the file is watched, so the panel and the sliders follow with no button.
Or use the editor panel, which lists what every connected target exports so a control can
be picked rather than typed, and refuses a map that would not resolve before it can be
saved. The TOML stays the source of truth either way.

It drives **two** targets, which is the point of the name: the same file can bend a finger
and press a key.

```toml
[dofs]
close = "vhi.prediction.index"          # a finger
walk  = "keyboard.hold.letter.w"        # held while the control is above 0.5
fire  = "keyboard.tap.edit.space"       # one press per crossing
```

A key is an ordinary two-state control, so the threshold, the debounce and the fan-out are
the same machinery the hand uses — see [Keyboard](../api/keyboard.md). Key sending starts
**disarmed**, because a resolved map types into whatever window has focus.

The editor is a widget, so it works in your own app too:

```python
from myogestic.widgets import ControlMapEditor

editor = ControlMapEditor(pathlib.Path("my_controls.toml"), client=vhi.control_client())

@app.ui
def ui(ctx):
    if editor.ui():          # True on the frame a save lands
        rebuild_my_bus()
```

To see it with no target at all:
`uv run python examples/panels/control_map_editor.py`.

## The examples

### `my_device.py` - drive your own hardware

A complete in-process target with three lines left for you: name your controls, drive your
hardware, release it. No hardware needed to run it — `send` prints what it would have sent,
so you can watch the bus clip an out-of-range value, replace a `NaN` with rest, and return
every control to neutral before teardown.

```bash
uv run python examples/synthetic/my_device.py
```

**What to tweak:** the three numbered lines. See
[Drive your own device](../how-to/add-a-target.md).

### `servo_hand.py` - the same shape, with a real mechanism

Six servos on a serial port. `hand.thumb` drives two of them on different transfer functions,
because a real thumb opposes as it flexes, and that coupling stays inside the target rather
than in anyone's control map. Runs with no hardware; its assertions check the exact bytes.

```bash
uv run python examples/synthetic/servo_hand.py
```

**What to tweak:** `SERVOS` for your travel in degrees, and pass a real
`serial.Serial(...)` as `port`.

### `emg_classification.py` - start here

The simplest end-to-end loop: 8-channel synthetic EMG → MyoVerse RMS+MAV
features → CatBoost binary classifier → smoothed control values to the VHI
predicted hand over LSL, on whichever streams its manifest says carry the
addresses the control file names. No discrete gRPC commands. This is
the reference first read, and its line-by-line companion is the
[EMG classification tutorial](emg-classification.md).

```bash
uv run python examples/synthetic/emg_classification.py
```

**What to tweak:** swap `rms`/`mav` from `myogestic.recipes.features`
for your own feature, change `CLASSES`, replace CatBoost with any
sklearn-shaped classifier.

### `emg_classification_grpc.py` - add the gRPC control plane

Same classifier, plus the `RemoteClient` gRPC plane: each predicted
class change commands a **discrete DOF**, whose declared
`debounce_s` gates the tick-to-tick argmax flicker, and a `VhiMovementPanel`
in the UI lets the user click movements directly. Demonstrates the
dual-plane idiom (continuous LSL pose + discrete gRPC events) on a single
script.

```bash
uv run python examples/synthetic/emg_classification_grpc.py
```

**What to tweak:** wrap `bus.select` in a custom callback
to layer a session-label snap; swap the commanded state from class
name to `(class_name, intensity_bin)` for hysteresis on multiple fields.

### `emg_regression.py` - continuous-target regression

CatBoost regressor maps EMG features to a 5-DOF kinematic target.
Recorded with a discrete DOF — a held state — so VHI snaps to and *holds* each movement's
end pose - regression needs the trainee to physically reach and hold the
target, not sweep through a cycle. RMS + MAV + waveform length features.

```bash
uv run python examples/synthetic/emg_regression.py
```

**What to tweak:** add or remove DOFs in the kinematic target; swap
CatBoost for sklearn's `MultiOutputRegressor` to compare model families.

### `emg_regression_raulnet.py` - RaulNet via Lightning

Same regression flow but with **RaulNetV17** - a PyTorch Lightning CNN
that takes a sliding-RMS feature stack `(channels, time)` and predicts
5-DOF kinematics. Trains with `Trainer(precision="32-true")`
(TorchScript backward has hard-coded fp32 checks; mixed-precision
fails), SWA, ModelCheckpoint, and per-epoch log lines streamed to the
pipeline panel's autoscroll-and-popout log box.

```bash
uv run python examples/synthetic/emg_regression_raulnet.py
```

**What to tweak:** change `RaulNetV17` hyperparameters, increase the
window size, switch the device to MPS (Apple Silicon) or CUDA - the
training callback streams the same per-epoch log either way.

### `emg_32ch_multi_model.py` - multi-classifier comparison

32-channel EMG with a *selectable* classifier - compare CatBoost,
sklearn LDA, sklearn SVM, etc. live without re-running the script. Adds
the **Save/Load model** panel so a tuned model survives a restart, and
the pose-lookup pattern for mapping multiple gestures to control poses.

```bash
uv run python examples/synthetic/emg_32ch_multi_model.py
```

**What to tweak:** plug another classifier into the model registry, add
more gestures to the pose-lookup, increase the channel count (the
generator scales to any `--channels`).

### `emg_popout_layout.py` - dockable layout reference

Same flow as `emg_32ch_multi_model.py` but every block is a tear-off
pop-out window via `App(docking=True)` + `app.popout(...)`. The
`Prediction` panel gets its own floating window; the training log can
pop out independently. Reference layout for multi-monitor experiments.

```bash
uv run python examples/synthetic/emg_popout_layout.py
```

**What to tweak:** rearrange the `app.popout()` call sites; combine
docking with the `Grid` layout from
[Grid layout](../concepts/grid-layout.md) for the in-window panels.

### `vhi_control_hand.py` - the operator's hand, not the model's

The only example that drives `vhi.control.pose.*` instead of `vhi.prediction.*`: sliders
pose the hand an operator sets up by hand, on its own stream. Both namespaces number
channels from 0, so a control-pose address on the prediction stream would land on the
other hand's channel — but nothing in the example says so. The target finds those
addresses on the operator's stream in VHI's manifest and publishes there; VHI
reads a pose instead of animating its own movements for as long as that stream is
present. Point the same file at `vhi.prediction.*` and the example drives the other
hand, unchanged.

```bash
uv run --extra grpc python examples/synthetic/vhi_control_hand.py
```

**What to tweak:** add a mapping to
[`examples/controls/control_hand.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/control_hand.toml)
— a slider appears for it and nothing else changes.

### `start_here/myocontrol.py` - the whole loop as a protocol

What the demos above teach one at a time, assembled into an application you could take to a
subject unmodified: a device dropdown instead of a named source, Rest/Fist trials shown
on the control hand and recorded to a session folder, and a Train that builds either a classifier or a regressor.
The switch chooses what the *next* Train builds — the mode rides inside the model, so
flipping it under a loaded model cannot run a class index down the regression branch. One
control map serves both, because **classification is regression that emits a constant**:
a class names how closed the hand should be, `POSES` says what that constant is, and it
goes out in the same units a regressor's own numbers do. Nothing downstream can tell the
two apart.

The map declares two aliases, named for the hands they drive, and both are commanded
every frame — `prediction` on `vhi.prediction.*`, the model's output, and `control` on
`vhi.control.pose.*`, the class the operator selected. Same kind of value, different
source. The two hands are allowed to disagree; that disagreement is what you are
watching.

```bash
uv run --extra examples --extra grpc python examples/start_here/myocontrol.py
```

VHI is optional: nothing binds until you press **Connect** on the Hand tab, and until then
`predict` pushes nothing and everything else runs.

**What to tweak:** `CLASSES` and `POSES` together - a class is a name plus how closed the
hand is for it, and the module refuses at import if the two disagree. The names are yours;
nothing downstream matches them against VHI's vocabulary. Also the ticked features, and
`iterations` on either estimator.

### `start_here/pong.py` - the first signed example

Everything else that ships is one-way: `fist` runs 0..1, `%MVC` runs 0..1, and rest is
simply the bottom of the range. Here the command is **signed**, in `[-1, +1]`, and Down is
a real `-1` rather than the absence of Up — a wrist is the canonical bidirectional DOF, and
the negative half is a direction a one-way fit never sees. One model emits one number; that
number moves a [`PongTask`][myogestic.widgets.PongTask] paddle, `+1` at the top of the
court, against an opponent paddle that plays it back. A rally is the reason for the game:
it rewards *graded* contraction, where a trapezoid only rewards tracking and a gesture
classifier rewards nothing continuous at all.

Two ways to record the training set, and the Model tab starts either. **Follow the cursor**
runs a [`Pursuit`][myogestic.tracking.Pursuit] block — a ghost paddle wanders the court, the
subject chases it, and the cursor is recorded beside the EMG on the `target` stream. The
Down / Rest / Up buttons cue the older three-class protocol. Prefer the cursor: three cued
classes are three distinct target values, so a tree ensemble fitted on them is a three-class
model whatever it is called — dead below about 30 % effort and non-monotonic in it. Densely
covered levels cut the CatBoost error at intermediate efforts 14x. **What that measurement
actually says** is that the active ingredient is the *number of distinct target levels*, not
pursuit as such: a cued staircase of eleven holds scores at least as well, and a linear
model gains nothing either way, because least squares already draws a straight line through
three points. What a followed cursor buys over a staircase is human — told "go to 0.6" a
subject has no idea what 0.6 feels like, while a cursor gives continuous visual error
feedback, so the intermediate levels are reachable at all.
[Record for proportional control](../how-to/record-for-proportional-control.md) is the
protocol on its own, with the numbers.

The mode switch offers **Proportional**, Regression and Classification, and Proportional is
the default because the obvious baseline is wrong here in an instructive way. A regressor
handed raw features learns whichever cue is louder in the training set, and loudness is not
direction: the CatBoost fit this example shipped with learned "louder = Down", so
contracting harder walked the paddle the wrong way. `Proportional` is
[`directional_decoder`][myogestic.recipes.estimators.directional_decoder], which estimates
*how much* and *which way* separately and multiplies them. Both other modes still train and
run — switching is the point, and the bound mode travels inside the model, so moving the
switch under a loaded model changes nothing until the next Train. Cursor and cued sessions
also train *together*: a class is a constant target, so both protocols land in the same
signed column.

```bash
uv run --extra examples --extra grpc python examples/start_here/pong.py
```

The Virtual Hand is a **mirror**, not a target: the paddle follows a plain float whether or
not VHI ever answers, and the one alias in
[`examples/controls/pong.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/pong.toml)
carries the same float to the wrist once the Hand tab is bound. Its `weight = -1.0` is
anatomy rather than a correction — flexion is palm-ward, which on a pronated forearm is
down. With no hardware at all, the synthetic amplifier's `direction` slider drives an
agonist/antagonist pair, so Down and Up are separable signals and the whole loop demos on
one machine.

**What to tweak:** `CLASSES` and `POSES` together, as in `myocontrol.py` — but keep a
negative entry, since a table that never goes below zero pins the paddle to the top half.
Difficulty is **Easy / Fair / Hard** on the Model tab, which is `OPPONENTS` in the file (the
opponent's top speed as a multiple of `ball_speed`); changing it clears the court, because a
score won against a slower paddle should not carry over. `PongTask(paddle_size=...)` and
`ball_speed` are the two knobs left in code.

### `start_here/force_ramps.py` - a protocol with no model in it

The other two `start_here` apps train something. This one does not: it is the standard
HD-EMG isometric protocol — rest, ramp, hold, ramp down, recover — and the only thing being
produced is a recording good enough to analyse months later.
[`TrackingTask`][myogestic.widgets.TrackingTask] draws the trapezoid and the live force
together, so the subject follows one line with another, and Start stays disabled until Zero
and MVC have both been captured, because force in device counts and a target in %MVC are
not comparable without them. Those two numbers go into the session's `extras`, alongside
the target as its own recorded stream, which is what makes the tracking error recoverable
from the archive alone.

```bash
uv run python examples/start_here/force_ramps.py
```

A synthetic load cell sits in the device list beside the real amplifiers, with an **Effort**
slider you drag yourself — nothing follows the target for you, so the whole loop demos with
nothing plugged in. See [Track a force target](../how-to/track-a-force-target.md) for the
wiring, and `examples/panels/tracking_task.py` for the widget on its own.

**What to tweak:** the `Trapezoid` shape (every segment is seconds, plus `level_pct` and how
many repetitions), and `channel=` on the task — the auxiliary channel your transducer is
actually on.

## Choosing where to start

* **Brand new** - [Anatomy of an app](../anatomy.md) →
  [EMG classification tutorial](emg-classification.md) →
  `emg_classification.py`.
* **I have a device to drive** - `my_device.py`, a complete target with three lines left for
  you, then [Drive your own device](../how-to/add-a-target.md). `servo_hand.py` is the same
  shape carrying a real mechanism: six servos, a coupled thumb, a wire format.
* **Want gRPC discrete control** - `emg_classification_grpc.py` next.
* **Regression flow** -
  [EMG regression with VHI tutorial](emg-regression-with-vhi.md) →
  `emg_regression.py` → swap in `_raulnet` for the deep variant.
* **Comparing models** - `emg_32ch_multi_model.py`.
* **Multi-monitor / docking** - `emg_popout_layout.py`.
* **Posing the control hand for setup or labelling** - `vhi_control_hand.py`.
* **A session to run, not a loop to build on** - `start_here/myocontrol.py`, which is the
  classification and regression flows in one application that names no hardware.
* **A bidirectional DOF, or a task a subject will stay with** - `start_here/pong.py`, the
  one signed example: Down is `-1`, and the rally is what trains graded control.
* **Recording a protocol rather than training a model** - `start_here/force_ramps.py`,
  isometric trapezoids with the calibration that makes them readable later.
* **Custom extension point** - skip the examples and read the
  [guides](../how-to/index.md) - each is a recipe for one
  extension point.
