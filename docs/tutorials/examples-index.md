# Examples directory

Every runnable example under [`examples/synthetic/`](https://github.com/NsquaredLab/MyoGestic/tree/main/examples/synthetic),
what it teaches, and what's tweakable. All of them are hardware-free - the
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

`.vscode/launch.json` is committed, so **Run and Debug** lists every example on this
page, the walkthrough, and the VHI prerequisites by name — with the extras synced by a
`preLaunchTask` first, so a fresh clone works on the first press of F5. The entries say
which need a display, which need a running Virtual Hand, and which need someone watching
the hand. Read the comments at the top of the file for the one thing worth knowing in
advance: the installed VHI release is pre-v2, so a v2 manifest needs source-mode.

## The control file

Each example maps its own output names onto controls the target declares, in a file of
its own under [`examples/controls/`](https://github.com/NsquaredLab/MyoGestic/tree/main/examples/controls).
A ready-to-copy declaration ships at
[`examples/controls/hand.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/hand.toml)
— signed continuous DOFs, a discrete grasp state, a one-way range, and a `debounce_s`
stability gate, with the mapping-first short forms alongside the explicit table form.

To watch it load and drive a hand end to end:

```bash
uv run --extra grpc python tools/inspect_canonical_control.py
```

That runs safely with no Virtual Hand at all, and prints a different section for a v2
build, a pre-v2 build, and nothing running.

## The examples

### `emg_classification.py` - start here

The simplest end-to-end loop: 8-channel synthetic EMG → MyoVerse RMS+MAV
features → CatBoost binary classifier → smoothed control values to the VHI
predicted hand via the `MyoGestic_Output` LSL outlet. No gRPC. This is
the canonical first read, and its line-by-line companion is the
[EMG classification tutorial](emg-classification.md).

```bash
uv run python examples/synthetic/emg_classification.py
```

**What to tweak:** swap `rms`/`mav` from `myogestic.recipes.features`
for your own feature, change `CLASSES`, replace CatBoost with any
sklearn-shaped classifier.

### `emg_classification_grpc.py` - add the gRPC control plane

Same classifier, plus the `VhiControlClient` gRPC plane: each predicted
class change commands a canonical **discrete DOF**, whose declared
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

CatBoost regressor maps EMG features to a 5-DoF kinematic target.
Recorded with a discrete DOF — a held state — so VHI snaps to and *holds* each movement's
end pose - regression needs the trainee to physically reach and hold the
target, not sweep through a cycle. RMS + MAV + waveform length features.

```bash
uv run python examples/synthetic/emg_regression.py
```

**What to tweak:** add or remove DoFs in the kinematic target; swap
CatBoost for sklearn's `MultiOutputRegressor` to compare model families.

### `emg_regression_raulnet.py` - RaulNet via Lightning

Same regression flow but with **RaulNetV17** - a PyTorch Lightning CNN
that takes a sliding-RMS feature stack `(channels, time)` and predicts
5-DoF kinematics. Trains with `Trainer(precision="32-true")`
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
the pose-lookup pattern for mapping multiple gestures to canonical poses.

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
channels from 0, so `VhiTarget(..., stream="control_pose")` is what keeps a control-pose
address off the other hand's channel — and it declares the stream during negotiation,
which is how the renderer knows to read a pose instead of animating its own movements.

```bash
uv run --extra grpc python examples/synthetic/vhi_control_hand.py
```

**What to tweak:** add a mapping to
[`examples/controls/control_hand.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/control_hand.toml)
— a slider appears for it and nothing else changes.

## Choosing where to start

* **Brand new** - [Anatomy of an app](../anatomy.md) →
  [EMG classification tutorial](emg-classification.md) →
  `emg_classification.py`.
* **Want gRPC discrete control** - `emg_classification_grpc.py` next.
* **Regression flow** -
  [EMG regression with VHI tutorial](emg-regression-with-vhi.md) →
  `emg_regression.py` → swap in `_raulnet` for the deep variant.
* **Comparing models** - `emg_32ch_multi_model.py`.
* **Multi-monitor / docking** - `emg_popout_layout.py`.
* **Posing the control hand for setup or labelling** - `vhi_control_hand.py`.
* **Custom extension point** - skip the examples and read the
  [how-to guides](../how-to/index.md) - each is a recipe for one
  extension point.
