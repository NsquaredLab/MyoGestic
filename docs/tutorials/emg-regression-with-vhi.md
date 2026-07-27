# EMG regression with the Virtual Hand

End-to-end walkthrough of
[`examples/synthetic/emg_regression.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/emg_regression.py):
8-channel synthetic EMG → MyoVerse RMS+MAV+WL features →
**multi-output CatBoost regressor** → five canonical DOFs → a
`ControlBus` that sanitises and smooths them → a `VhiTarget` that
renders them on the Virtual Hand.

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

## The five DOFs

The app declares *what it controls*, by name — not which channel of
which application receives it:

```python
--8<-- "examples/synthetic/emg_regression.py:dofs"
```

Each is **signed and normalized**: `+1` is the direction the name says
(full flexion), `-1` is the opposite, `0` is rest. That is the whole
canonical vocabulary; see [Control standard](../api/controls.md) for the
declaration format and the rules it enforces.

Five DOFs keeps the regressor manageable on fake EMG, so thumb
abduction is left out. Notice what is *absent*: no channel index, no
sign convention, no mention of nine of anything. A legacy Virtual Hand
does want a 9-float frame with flexion as negative — but that belongs to
the hand, so `VhiTarget` is the only thing that knows it.

## The output path

```python
--8<-- "examples/synthetic/emg_regression.py:bus"
```

The bus owns the ordering that must not be re-derived per app:
substitute rest → clip → smooth → **clip again** → deliver. Rest
substitution comes first because `min(hi, max(lo, nan))` is `lo`, so a
NaN prediction would otherwise arrive as a full-scale deflection; the
second clip exists because a smoother undershoots on a falling edge.

`VhiTarget` refuses at construction what it cannot render. Declare a
`wrist.rotation` and it raises, listing the six DOFs a legacy hand does
have — because a silently dropped joint looks exactly like a joint that
is working and holding still.

## Training: two iterators, one model

The training callback handles **two kinds of session** transparently:

```python
--8<-- "examples/synthetic/emg_regression.py:kin_loop"
```

`iter_aligned_windows` walks every EMG window in the session and
*time-aligns* a slice of the `vhi_control` stream to it. `decode_pose`
then reads that recorded slice as canonical values, so the training
target lands in exactly the space `predict` commands — one declaration
serving both directions is what keeps train and serve from drifting.
This is the primary path: sessions with both EMG and kinematics.

```python
--8<-- "examples/synthetic/emg_regression.py:label_loop"
```

`iter_labeled_windows` is the fallback for sessions that were recorded
*before* VHI was wired up (no `vhi_control` store). The script
synthesises a 5-vec target from the class index - `Fist → all 1s`,
`Rest → all 0s`. Those are the same numbers as before the canonical
conversion, but now for a stated reason rather than by accident: `+1`
*is* flexion. Useful for mixing pre-VHI data into a new training set
without re-recording.

The labeled fallback honours the class chips the user un-ticked in the
session manager, via its `classes=data.classes` argument; the kinematics
path regresses every aligned window (kinematics are continuous, so there's
nothing to filter by class).

The model is a single
[`catboost_regressor(loss_function="MultiRMSE")`](../api/models.md) fit
to the stacked `(X, y)`.

## Prediction: name the DOFs, hand them over

```python
--8<-- "examples/synthetic/emg_regression.py:predict"
```

Two steps: regress five numbers, label them, push. Everything else —
range enforcement, the live-tunable
[`PostProcessor`](../how-to/post-process-output.md) (one-euro at 32 Hz
by default), the encode to VHI's wire layout — belongs to the bus and
its target.

There is deliberately **no `np.clip` here**. Each DOF's declared range
is the authority, and clipping *before* the smoother is a bug rather
than a safeguard: the filter then overshoots straight back out of the
range you just enforced. `bus.push` returns the frame it actually
delivered, which is what feeds `pipeline.predictions`.

`bus.stop()` runs in the example's `finally`, and it does two things
that matter on a real limb: it delivers the rest frame *before* tearing
the targets down, and it **flushes** it. An outlet sends on a paced
thread, so a pose pushed as the process exits would otherwise never
leave — leaving the hand holding its last commanded position.

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
