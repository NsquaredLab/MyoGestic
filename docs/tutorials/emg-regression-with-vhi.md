---
title: "EMG regression with the Virtual Hand"
---
[`examples/synthetic/emg_regression.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/emg_regression.py)
maps 8-channel synthetic EMG to five Virtual Hand DOFs using MyoVerse
RMS+MAV+WL features and a multi-output CatBoost regressor. `ControlBus`
sanitizes and smooths predictions; `RemoteTarget` delivers them to the hand.

Two parts differ from `emg_classification.py`.

* Recording captures the VHI control hand's kinematics throughout the take
  as the training target. This uses a different recorder setup and training
  iterator.
* The example commands a
  *discrete DOF* over gRPC to drive the control hand to static
  end poses, uses the *recording aid* to gate the session, reads the
  resulting kinematics over LSL, and pushes the predicted pose back over
  LSL. The three streams have separate roles.

See [Drive a remote target](../how-to/drive-a-remote-target.md) for the
dual-plane architecture and [Integrate the Virtual Hand](../how-to/integrate-vhi.md)
for VHI control names.

## Run it first

```bash
uv run --extra examples --extra grpc python examples/synthetic/emg_regression.py
```

The Connect step has launch controls for the EMG generator
and the VHI binary, followed by their stream connections. Install VHI with
`python -m myogestic.tools.install_vhi` to use the default environment settings.

## The recording loop, narrated

Recording captures the control hand's kinematics throughout the take.
For a static target, select a pose and let it settle before recording.

1. In Connect, launch EMG Generator and VHI Hand, then connect
   TestEMG1 and VHI_Control. Set a participant in the header and
   open Record.
2. Click a Rest / Fist gesture button.
   * `bus.select("gesture", name)` sends a discrete DOF. The control hand
     holds the pose so `VHI_Control` provides a static kinematic target.
     Use the recording aid `recording_aid.start_trajectory(...)` for a
     swept trajectory.
   * `simulator.set(CTRL_VALUES[i])` switches the EMG generator
     to the corresponding amplitude pattern.
3. Click Record Rest or Record Fist. `recording_aid.set_recording_session(True)` disables
   VHI's local keyboard so the *only* movement source for this session
   is your gesture buttons. The session captures EMG samples
   *and* the `VHI_Control` 9-channel kinematics stream side by side.
   It returns `False` if this VHI has no recording aid, which the example
   reports. An ungated recording can pick up stray keyboard movements.
4. Click Stop. The session ends; `set_recording_session(False)`
   restores VHI's local control.

Repeat for each gesture, select the recorded takes in the session manager,
then click Train.

## The five DOFs

The app declares its controls by name.

```python
--8 < --"examples/synthetic/emg_regression.py:dofs"
```

Each is signed and normalized. `+1` is full flexion, the named direction;
`-1` is the opposite; `0` is rest. See [Control standard](../api/controls.md) for the
declaration format and the rules it enforces.

Five DOFs keep the regressor manageable on synthetic EMG. Thumb abduction
is excluded. The nine-channel VHI pose uses the same signed convention.
Use `myogestic.tools.migrate_vhi_sessions` to convert archives with negative flexion.

## The output path

```python
--8 < --"examples/synthetic/emg_regression.py:bus"
```

The bus applies this order.
Substitute rest → clip → smooth → clip again → deliver. Rest
substitution comes first because `min(hi, max(lo, nan))` is `lo`, so a
NaN prediction would otherwise arrive as a full-scale deflection; the
second clip keeps any smoother output inside the declared range.

`resolve()` and `RemoteTarget.bind()` reject maps containing unsupported controls
and list the controls the hand provides.

## Training: two iterators, one model

Training and live prediction share the same 200 ms EMG window (`WINDOW_MS`);
training advances by 100 ms (`HOP_MS`). Once the live window is full, the
same RMS+MAV+WL extractor produces the same flattened feature layout for
training and prediction.

The training callback handles two kinds of session transparently:

```python
--8 < --"examples/synthetic/emg_regression.py:kin_loop"
```

`iter_aligned_windows` walks every EMG window in the session and
*time-aligns* a slice of the `vhi_control` stream to it. `split_pose`
then names the channels using the same declaration as `predict`.
Use this path for takes with both EMG and kinematics.

```python
--8 < --"examples/synthetic/emg_regression.py:label_loop"
```

For takes with class labels and no `vhi_control` store, `iter_labeled_windows`
creates a 5-value target from the class index. `Fist → all 1s`, `Rest → all 0s`,
because `+1` is flexion. Train on both types of take together.

Select at least one class in the session manager before training. Untick
every class and both this example and the RaulNet variant refuse with
"No classes selected — select at least one class before training." in the
training status and log. With a non-empty selection, the labeled fallback
honours the class chips via its `classes=data.classes` argument; the
kinematics path regresses every aligned window using continuous targets.

The model is a single
[`catboost_regressor(loss_function="MultiRMSE")`](../api/models.md) fit
to the stacked `(X, y)`.

## Prediction: name the DOFs, hand them over

```python
--8 < --"examples/synthetic/emg_regression.py:predict"
```

Regress five numbers, name them and push them. The bus and target enforce
ranges, apply the live-tunable [`PostProcessor`](../how-to/post-process-output.md)
with a one-euro filter at 32 Hz by default, and encode VHI's wire layout.

Call `bus.push` without `np.clip`. The bus clips to each DOF's declared range before and after smoothing. `bus.push` returns the frame it actually
delivered, which is what feeds `pipeline.predictions`.

`link.stop()` runs in `finally` and calls `bus.stop()` to deliver and flush
the rest frame before target teardown. Flushing sends the frame before
the paced outlet thread exits, so the hand returns to rest.

## Layout - responsive steps

```python
--8 < --"examples/synthetic/emg_regression.py:grid"
```

The wide layout has six rows and two columns, with a growing signal column
and a 400 px step-and-sessions column. The header and status span both.
The simulator and activity log stay beside the sessions. Below 1100 px,
the narrow layout stacks the same panels in one column.

The header shows Connect → Record → Train → Predict and the
participant. See [Grid layout](../concepts/grid-layout.md) for the
`Px`/`Fr` rules.

## Where to go next

* [`examples/synthetic/emg_regression_raulnet.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/emg_regression_raulnet.py) -
  swap CatBoost for the RaulNetV17 PyTorch Lightning CNN using the
  same I/O contract. Use `Trainer(precision="32-true")` because the
  TorchScript backward has hard-coded fp32 checks that fail under
  mixed-precision.
* [Record good training data](../how-to/record-good-training-data.md) -
  how many seconds per gesture, how to avoid posture drift.
* [Edge trigger](../concepts/edge-trigger.md) - the gating helper used
  by the classifier example.
