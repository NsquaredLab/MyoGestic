# EMG regression with the Virtual Hand

End-to-end walkthrough of
[`examples/synthetic/emg_regression.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/emg_regression.py):
8-channel synthetic EMG → MyoVerse RMS+MAV+WL features →
**multi-output CatBoost regressor** → 5-DOF kinematics → expanded
9-vec → smoothed pose pushed to the Virtual Hand.

Why regression and not classification? Two reasons it's the next thing
to learn after `emg_classification.py`:

* **The label loop is different.** Recording captures the VHI control
  hand's *kinematic value at the end of each movement*, not a class
  index. That changes both the recorder setup and the training-data
  iterator.
* **The dual-plane idiom is unavoidable.** The example uses gRPC
  (`SetMovement`, `SetSessionActive`) to drive the control hand to
  static end poses *and* LSL to read the resulting kinematics *and* LSL
  to push the predicted pose back. Three streams, three roles.

If you haven't yet, read
[Integrate the Virtual Hand](../how-to/integrate-vhi.md) first - that
page explains the dual-plane architecture in general; this one walks the
specific script.

## Run it first

```bash
uv run --extra examples --extra grpc python examples/synthetic/emg_regression.py
```

The `ProcessLauncher` panel inside the GUI spawns the EMG generator
and the VHI binary. No env vars required if VHI was installed with
`python -m myogestic.tools.install_vhi`.

## The recording loop, narrated

The thing that surprises first-time regression users:
**recording captures the control hand's settled kinematics, not the
button click.** The flow:

1. Click **Launch** on EMG Generator and VHI Hand.
2. Click a gesture button (Rest / Fist). Two things happen:
   * `vhi_client.set_movement(name, cycle=False)` - VHI animates the
     control hand to the *end pose* of that movement and **holds it**.
     The `cycle=False` is load-bearing: regression needs the hand to
     reach and hold the target, not sweep through an open/close cycle.
   * `ctrl_outlet.push_sample([CTRL_VALUES[i]])` - the EMG generator
     switches to the corresponding amplitude pattern.
3. Click **Record**. `vhi_client.set_session_active(True)` disables
   VHI's local keyboard so the *only* movement source for this session
   is your gesture buttons. The session captures EMG samples
   *and* the `VHI_Control` 9-channel kinematics stream side by side.
4. Click **Stop Rec**. The session ends; `set_session_active(False)`
   restores VHI's local control.

That's the loop. Repeat for every gesture you want the model to
regress; pick the recorded sessions in the session manager; click
**Train**.

## The five DoFs

```python
--8<-- "examples/synthetic/emg_regression.py:dofs"
```

VHI's `VHI_Control` outlet is the full 9-channel pose (see the table in
[Integrate the Virtual Hand](../how-to/integrate-vhi.md#plane-1-continuous-pose-over-lsl)).
For a fake-EMG demo you don't want the regressor to wrestle with the
3-DoF wrist - five DoFs (wrist rotation + four fingers, indices 0, 2,
3, 4, 5) is the right starter target.

The expansion back to 9-DoF for `vhi_outlet.push()` zero-fills the
unselected channels:

```python
--8<-- "examples/synthetic/emg_regression.py:expand"
```

The sign flip aligns the regressor's `[0, 1]` magnitude with VHI's
flexion convention (`-1` = full flex).

## Training: two iterators, one model

The training callback handles **two kinds of session** transparently:

```python
--8<-- "examples/synthetic/emg_regression.py:kin_loop"
```

`iter_aligned_windows` walks every EMG window in the session and
*time-aligns* a slice of the `vhi_control` stream to it. The kinematics
slice becomes the regression target. This is the primary path -
sessions with both EMG and kinematics.

```python
--8<-- "examples/synthetic/emg_regression.py:label_loop"
```

`iter_labeled_windows` is the fallback for sessions that were recorded
*before* VHI was wired up (no `vhi_control` store). The script
synthesises a 5-vec target from the class index - `Fist → all 1s`,
`Rest → all 0s`. Useful for mixing pre-VHI data into a new training set
without re-recording.

The labeled fallback honours the class chips the user un-ticked in the
session manager, via its `classes=data.classes` argument; the kinematics
path regresses every aligned window (kinematics are continuous, so there's
nothing to filter by class).

The model is a single
[`catboost_regressor(loss_function="MultiRMSE")`](../api/models.md) fit
to the stacked `(X, y)`.

## Prediction: smoothed, expanded, pushed

```python
--8<-- "examples/synthetic/emg_regression.py:predict"
```

Three steps:

1. Predict 5 DOFs, clamp to `[0, 1]`.
2. Expand to a 9-vec with the sign flip.
3. Apply the live-tunable
   [`PostProcessor`](../how-to/post-process-output.md) (defaults to
   one-euro at 32 Hz) and push to the LSL outlet.

The returned dict feeds `pipeline.predictions` so widgets like
`PredictionLabel` (when configured) can render the current 5-vec.

## Layout - six rows, three columns

```python
--8<-- "examples/synthetic/emg_regression.py:grid"
```

A 6×3 grid: a fixed-height top row sized to the wordmark aspect, then
five equal-share rows below. The left column is fixed at 300 px for the
logo + control panels; columns 2 and 3 are `Fr(1)` and grow with the
window. See [Grid layout](../concepts/grid-layout.md) for the
`Px`/`Fr` rules.

The signal viewer spans rows 0-3 across columns 1-2; stream and log
panels share the bottom two rows.

## Where to go next

* [`examples/synthetic/emg_regression_raulnet.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/emg_regression_raulnet.py) -
  swap CatBoost for **RaulNetV17** (PyTorch Lightning CNN). Same I/O
  contract, deeper model. Use `Trainer(precision="32-true")` - the
  TorchScript backward has hard-coded fp32 checks that fail under
  mixed-precision.
* [Record good training data](../how-to/record-good-training-data.md) -
  how many seconds per gesture, how to avoid posture drift.
* [Edge trigger](../concepts/edge-trigger.md) - the gating helper used
  by the classifier example.
