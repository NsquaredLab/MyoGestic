# Examples directory

Every runnable example under [`examples/synthetic/`](https://github.com/NsquaredLab/MyoGestic/tree/main/examples/synthetic),
what it teaches, and what's tweakable. All six are hardware-free - the
`process_launcher` panel spawns `myogestic.tools.emg_generator` for you,
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

## The six examples

### `emg_classification.py` - start here

The simplest end-to-end loop: 8-channel synthetic EMG → MyoVerse RMS+MAV
features → CatBoost binary classifier → smoothed 9-vec to the VHI
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
class change fires `SetMovement(name)` via an
[`EdgeTrigger`](../concepts/edge-trigger.md), and a `VhiMovementPanel`
in the UI lets the user click movements directly. Demonstrates the
dual-plane idiom (continuous LSL pose + discrete gRPC events) on a single
script.

```bash
uv run python examples/synthetic/emg_classification_grpc.py
```

**What to tweak:** wrap `vhi_client.set_movement` in a custom callback
to layer a session-label snap; swap the `EdgeTrigger` value from class
name to `(class_name, intensity_bin)` for hysteresis on multiple fields.

### `emg_regression.py` - continuous-target regression

CatBoost regressor maps EMG features to a 5-DoF kinematic target.
Recorded with `cycle=False` so VHI snaps to and *holds* each movement's
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
* **Custom extension point** - skip the examples and read the
  [how-to guides](../how-to/index.md) - each is a recipe for one
  extension point.
