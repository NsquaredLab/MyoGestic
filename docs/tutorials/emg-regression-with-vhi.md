---
title: "EMG regression with the Virtual Hand"
---
End-to-end walkthrough of
[`examples/synthetic/emg_regression.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/emg_regression.py):
8-channel synthetic EMG → MyoVerse RMS+MAV+WL features →
**multi-output CatBoost regressor** → five control DOFs → a
`ControlBus` that sanitises and smooths them → a `RemoteTarget` that
drives them on the Virtual Hand.

Why regression and not classification? Two reasons it's the next thing
to learn after `emg_classification.py`:

* **The label loop is different.** Recording captures the VHI control
  hand's *kinematics throughout the take*, rather than using a class
  index as the training target. That changes both the recorder setup and the training-data
  iterator.
* **The dual-plane idiom is unavoidable.** The example commands a
  *discrete DOF* over gRPC to drive the control hand to static
  end poses, uses the *recording aid* to gate the session, reads the
  resulting kinematics over LSL, and pushes the predicted pose back over
  LSL. Three streams, three roles.

If you haven't yet, read [Drive a remote target](../how-to/drive-a-remote-target.md) for the
dual-plane architecture in general and
[Integrate the Virtual Hand](../how-to/integrate-vhi.md) for what VHI calls its own
controls; this page walks the specific script.

## Run it first

```bash
uv run --extra examples --extra grpc python examples/synthetic/emg_regression.py
```

The **Connect** step has launch controls for the EMG generator
and the VHI binary, followed by their stream connections. No env vars required if VHI was installed with
`python -m myogestic.tools.install_vhi`.

## The recording loop, narrated

The thing that surprises first-time regression users:
**recording captures the control hand's kinematics throughout the take.**
Select a pose and let it settle before recording if you want a static target. The flow:

1. In **Connect**, launch EMG Generator and VHI Hand, then connect
   **TestEMG1** and **VHI_Control**. Set a participant in the header and
   open **Record**.
2. Click a gesture button (Rest / Fist). Two things happen:
   * `bus.select("gesture", name)` - the gesture is a
     **discrete DOF**, a *held state*: the control hand snaps to that
     pose and stays there. That it holds rather than sweeps is
     load-bearing here — regression needs the hand to reach and hold the
     target, so `VHI_Control` settles to a static kinematic value the
     regressor can map back from EMG amplitude. (If you *want* a swept
     trajectory instead, that is `recording_aid.start_trajectory(...)`, a
     recording aid rather than a control command.)
   * `simulator.set(CTRL_VALUES[i])` - the EMG generator
     switches to the corresponding amplitude pattern.
3. Click **Record Rest** or **Record Fist**. `recording_aid.set_recording_session(True)` disables
   VHI's local keyboard so the *only* movement source for this session
   is your gesture buttons. The session captures EMG samples
   *and* the `VHI_Control` 9-channel kinematics stream side by side.
   It returns `False` if this VHI has no recording aid, which the example
   surfaces — an ungated recording can pick up stray keyboard movements.
4. Click **Stop**. The session ends; `set_recording_session(False)`
   restores VHI's local control.

That's the loop. Repeat for every gesture you want the model to
regress; pick the recorded sessions in the session manager; click
**Train**.

## The five DOFs

The app declares *what it controls*, by name — not which channel of
which application receives it:

```python
--8 < --"examples/synthetic/emg_regression.py:dofs"
```

Each is **signed and normalized**: `+1` is the direction the name says
(full flexion), `-1` is the opposite, `0` is rest. That is the whole
control vocabulary; see [Control standard](../api/controls.md) for the
declaration format and the rules it enforces.

Five DOFs keeps the regressor manageable on fake EMG, so thumb
abduction is left out. Notice what is *absent*: no channel index, no
sign convention, no mention of nine of anything. VHI's recorded pose format
once encoded flexion as negative, the opposite of the stream it was compared
against; both ends speak the standard now and the archives were converted
once by `myogestic.tools.migrate_vhi_sessions`, so there is nothing left to
decode.

## The output path

```python
--8 < --"examples/synthetic/emg_regression.py:bus"
```

The bus owns the ordering that must not be re-derived per app:
substitute rest → clip → smooth → **clip again** → deliver. Rest
substitution comes first because `min(hi, max(lo, nan))` is `lo`, so a
NaN prediction would otherwise arrive as a full-scale deflection; the
second clip keeps any smoother output inside the declared range.

`resolve()` and `RemoteTarget.bind()` refuse a map the target cannot drive. Declare
something this hand has no joint for and resolution raises, listing what it does
have — because a silently dropped joint looks exactly like a joint that
is working and holding still.

## Training: two iterators, one model

Training and live prediction share the same 200 ms EMG window (`WINDOW_MS`);
training advances by 100 ms (`HOP_MS`). Once the live window is full, the
same RMS+MAV+WL extractor produces the same flattened feature layout for
training and prediction.

The training callback handles **two kinds of session** transparently:

```python
--8 < --"examples/synthetic/emg_regression.py:kin_loop"
```

`iter_aligned_windows` walks every EMG window in the session and
*time-aligns* a slice of the `vhi_control` stream to it. `split_pose`
then names that slice's channels — the values are already in the space
`predict` commands — so the training target and the command share one
declaration, which is what keeps train and serve from drifting.
This is the primary path: sessions with both EMG and kinematics.

```python
--8 < --"examples/synthetic/emg_regression.py:label_loop"
```

`iter_labeled_windows` is the fallback for sessions that were recorded
*before* VHI was wired up (no `vhi_control` store). The script
synthesises a 5-vec target from the class index - `Fist → all 1s`,
`Rest → all 0s`. Those are the same numbers as before the switch to
control values, but now for a stated reason rather than by accident: `+1`
*is* flexion. Useful for mixing pre-VHI data into a new training set
without re-recording.

Select at least one class in the session manager before training. Untick
every class and both this example and the RaulNet variant refuse with
"No classes selected — select at least one class before training." in the
training status and log. With a non-empty selection, the labeled fallback
honours the class chips via its `classes=data.classes` argument; the
kinematics path regresses every aligned window (kinematics are continuous,
so there's nothing to filter by class).

The model is a single
[`catboost_regressor(loss_function="MultiRMSE")`](../api/models.md) fit
to the stacked `(X, y)`.

## Prediction: name the DOFs, hand them over

```python
--8 < --"examples/synthetic/emg_regression.py:predict"
```

Two steps: regress five numbers, label them, push. Everything else —
range enforcement, the live-tunable
[`PostProcessor`](../how-to/post-process-output.md) (one-euro at 32 Hz
by default), the encode to VHI's wire layout — belongs to the bus and
its target.

There is deliberately **no `np.clip` here**. Each DOF's declared range
is the authority, and clipping *only before* the smoother cannot
keep its output in range. The bus clips both before and after smoothing. `bus.push` returns the frame it actually
delivered, which is what feeds `pipeline.predictions`.

`link.stop()` runs in the example's `finally` and calls `bus.stop()`, and it does two things
that matter on a real limb: it delivers the rest frame *before* tearing
the targets down, and it **flushes** it. An outlet sends on a paced
thread, so a pose pushed as the process exits would otherwise never
leave — leaving the hand holding its last commanded position.

## Layout - responsive steps

```python
--8 < --"examples/synthetic/emg_regression.py:grid"
```

The wide layout has six rows and two columns: a growing signal column
and a 400 px step-and-sessions column. The header and status span both.
The simulator and activity log stay beside the sessions. Below 1100 px,
the narrow layout stacks the same panels in one column.

The header shows **Connect → Record → Train → Predict** and the
participant. See [Grid layout](../concepts/grid-layout.md) for the
`Px`/`Fr` rules.

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
