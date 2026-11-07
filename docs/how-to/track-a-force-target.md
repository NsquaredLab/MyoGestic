---
title: "Track a force target"
---
In isometric force tracking, the participant holds a joint still against a
transducer and matches an on-screen trapezoid through rest, ramp up, hold, ramp
down and recovery. This standard HD-EMG protocol uses a slow linear ramp and
steady plateau to measure recruitment order and discharge rates. OT Bioelettronica
provides it in its acquisition software. `TrackingTask` runs it in your app with
the amplifier selected by the [device picker](pick-a-device.md).

`examples/panels/tracking_task.py` runs the whole loop against a synthetic force channel if
you want to see it before wiring a load cell. This is the real version:

```python
from myogestic import App, Stream
from myogestic.sources import TargetSource
from myogestic.tracking import Trapezoid
from myogestic.widgets import DEFAULT_DEVICES, DevicePicker, RecordButton, TrackingTask

app = App("force tracking")

emg = Stream("emg", source=DEFAULT_DEVICES[0].factory(), window_ms=200)
# The target, as a second recorded stream. `TrackingTask` drives this object.
target_source = TargetSource()
target_stream = Stream("target", source=target_source, window_ms=200)
app.streams(emg, target_stream)
# Software, not hardware: there is nothing to plug in, so it attaches here. The
# amplifier waits for Connect.
target_stream.reconnect()

device = DevicePicker("emg")
task = TrackingTask(
    "emg",
    channel=64,  # the AUX channel the transducer is on
    trapezoid=Trapezoid(ramp_up_s=5.0, hold_s=15.0, level_pct=20.0),
    target=target_source,
)
recording = RecordButton(on_record=app.start_recording, on_stop=app.stop_recording)


@app.ui
def ui(ctx):
    device.ui(ctx)
    task.ui(ctx)
    recording.ui(ctx)


app.run()
```

Pass the shape to the task and construct `TargetSource()` without arguments.
The task forwards edits to that source, keeping the displayed and recorded
trapezoids identical.

## Wire the force in

The transducer is not a biosignal channel. Connect it to an auxiliary amplifier input. Its channel follows
the bio block on the EMG stream when auxiliary inputs are enabled. Every OTB entry in the picker has an
`include_aux` row, off by default:

| Device | Picker row | What gets appended | Where the force lands |
|---|---|---|---|
| Muovi, Muovi+ | `IMU + counters` | 6: quaternion `w x y z`, buffer/trigger, sample counter | no analogue input |
| Sessantaquattro+ | `AUX + IMU + counters` | 8: `aux0`, `aux1`, then the Muovi block | `aux0` / `aux1`, first two of the block |
| Quattrocento | `AUX IN + accessory` | 16 AUX IN, then 8 accessory | any of the 16 back-panel AUX IN |

Muovi's accessory block contains IMU and counters, with no analogue input.
That is why its picker row names IMU and counters rather than AUX.
A plain Sessantaquattro reports a 4- or 6-wide accessory block without AUX
channels. The `aux0`/`aux1` pair requires Sessantaquattro+. The source probes
accessory width from the ramp counter on connection. You cannot configure
that width; connect to find out what the device provides.

Do not count channel indices. The panel's Channel dropdown lists the stream's
own names; pick `aux0` by name. Its index varies:
on a Sessantaquattro+ it is 64 at 64 channels monopolar but 32 in `Bipolar`, which
halves the bio block. `channel=` in the constructor is only where the dropdown
opens.

`include_aux` is off by default because Muovi and Sessantaquattro append raw
counts beside bio channels scaled to millivolts. A shared plot range cannot
usefully show both scales. Display bio channels in the
signal viewer and force in the tracking panel to give each a suitable range.

## Calibrate with two captures

Map raw readings to percent of MVC with two captures:

- Zero captures rest with the participant relaxed, hand off the transducer.
- MVC keeps the peak over the next three seconds. Press it and push as hard as possible.

A load cell has a resting offset from preload, its weight or amplifier DC bias.
Normalizing against MVC alone makes a resting reading of 1.0 with an MVC of 3.0
read as 33 %, above a 30 % target. `Calibration` subtracts `zero` from the sample
and maximum so 30 % refers to 30 % of the participant's voluntary range.

Both captures and the live trace use the chosen channel's mean over
`tail_ms`, which defaults to 100 ms. Averaging reduces sample noise.

Units never come up. `Calibration` is a two-point map in whatever the channel
happens to carry, so it works identically on Sessantaquattro counts and on
Quattrocento volts. You do not need the transducer's datasheet to run the
task; use it when reporting newtons.

The calibration row says Capture zero, then MVC until both captures exist.
Zero and MVC sit beside that instruction; during MVC capture the same row
shows the remaining seconds, then the two captured values. Start stays disabled until both captures and a force reading are available;
its tooltip explains why.
Recapture Zero between blocks whenever the participant repositions; the transducer's
offset moves with the grip. Setup controls are dimmed and locked while a block runs.

## Give the force its own stream

Point the task at a stream carrying only force:

```python
app.streams(
    Stream("emg", source=..., window_ms=200),
    Stream("force", source=..., window_ms=200),
    Stream("target", source=target, window_ms=200),
)
task = TrackingTask("force", target=target)
```

An amplifier AUX input puts force on the EMG stream. Sharing that stream couples
the panels' connection state. Use a separate stream for independent force input.

To share a stream, enable the picker's aux row and select the AUX Channel in
the task. Both panels then share the device's connection state.

Keep the target out of the picker's reach while you are at it:

```python
DevicePicker("emg", selectable=True, exclude=("target",))
```

The target stream is the task's own output. Offered as a device stream, one
Connect replaces the task's `TargetSource`, detaching the source it writes to
and recording amplifier data under `target`.

## Try it without a transducer

`SyntheticForceSource` simulates a transducer. It does not simulate a
participant following the target. You act as the participant by watching
the target and dragging `effort` to simulate pushing on a load cell.

```python
from myogestic import Stream
from myogestic.sources import SyntheticForceSource, TargetSource

target = TargetSource()  # bare: `TrackingTask` owns the shape
force = SyntheticForceSource()  # 0.30 V at rest, 2.30 V at full effort
app.streams(
    Stream("force", source=force, window_ms=200),
    Stream("target", source=target, window_ms=200),
)
for name in ("force", "target"):
    app.ctx.streams[name].reconnect()
```

`SyntheticSource` generates oscillating signals: sine by default, or stochastic
signals with `waveform="emg"`. Use `SyntheticForceSource` here for a steady resting
offset and a force level that responds to `effort`.

Its offset and smoothing model transducer readings:

- The resting reading is not zero. A transducer has an offset, and a
  calibration that assumes otherwise puts every target at the wrong force. Here
  you can make that mistake and watch it happen.
- It smooths your slider. Dragging a slider is a step; a muscle is not.
  `lag_s` is a first-order time constant so a drag reads as a contraction. Set
  it to `0` to follow the slider exactly.

Nothing follows the target automatically. Move `effort` yourself to produce
the tracking error the task measures. Automatic tracking would fabricate an
error that no participant produced.

To capture an MVC, raise `effort` while no block is running. The target asks
for nothing then; effort alone drives the force channel.

## Shape the trapezoid

The target row shows a small trapezoid and its durations, level and repetition
count, such as `2·3·5·3·2 s · 40 % · 5 reps`. Its settings icon opens the five
durations, Level, Reps and Look ahead. Captions sit above their controls
in two columns, falling back to one in narrow cells. The segment fields on
`Trapezoid` are ordered as they happen:

| Field | Default | What it is |
|---|---|---|
| `rest_s` | 3.0 | Baseline before the ramp. Every analysis needs this pre-contraction reference. |
| `ramp_up_s` | 5.0 | Linear rise to `level_pct`. Recruitment happens here, so slow enough to resolve it. |
| `hold_s` | 10.0 | Seconds at the plateau. The steady-state segment discharge-rate estimates come from. |
| `ramp_down_s` | 5.0 | Linear fall to baseline for de-recruitment, the counterpart to ramp up. |
| `recover_s` | 5.0 | Baseline before the next repetition for fatigue control. Do not treat it as padding. |
| `level_pct` | 30.0 | Plateau height, in percent of MVC. |
| `reps` | 1 | How many times the shape repeats back to back. |

The sketch previews one repetition using the same corners as the plot. Its height
is normalized so the time proportions stay legible at small sizes; Level states
the plateau height. A mono summary below the plot gives the whole block's duration,
for example `3 x 28.0 s = 84.0 s`. Long row readouts ellipsize in narrow cells; hover
to read the full text.

## What the participant sees

The plot frames one repetition at a time, keeping the force-target gap visible
even with five reps. The trace restarts on each repetition. The running row counts repetitions and names the
phase, such as `Rep 2 of 5 · hold`, above the force and signed error,
`61 % MVC · error +3 %`. Error is measured force minus the current target.
Stop stays beside this readout; the setup above it is dimmed and locked.
The Target and Force legend chips toggle visibility without discarding data.

Force is drawn up to the current moment. Look ahead sets how many seconds of
future target are visible. A shorter preview reduces the opportunity to memorize
the shape. The task measures following, so showing the whole ending from
the first frame changes how the participant can approach it. Set it to zero to hide the future target or to a full repetition
to show the whole trajectory in advance.

Look ahead changes the display only. It is absent from `Trapezoid` and
the block's record; the commanded trajectory stays the same.

Reps roll straight on: the recover segment is the rest between them, so the block
is one continuous recording and only the plot reframes.

Any segment may be zero. Zero-length segments are skipped: `hold_s=0` is a legal triangle, `rest_s=0` starts the ramp immediately.
`Trapezoid` is frozen and validates on construction, and the panel's rows clamp to
what it accepts, so dragging a field can change the shape but never raise.
`duration` is one repetition, `total_duration` the whole block. If every duration
is zero, Start asks you to set at least one above zero before running.

At `total_duration`, the block ends as if Stop were pressed. The trace stays
on the plot for review.

The y range is pinned to the target so errors of 5 % and 50 % remain visibly
different. Per-frame autoscaling would hide this difference.

## The target is recorded as a stream

`TargetSource` implements the same `connect` / `read` / `disconnect` contract as
an amplifier, so a `Stream` records it exactly as it records EMG. Two channels, at
100 Hz by default:

| Channel | Name | Contents |
|---|---|---|
| 0 | `target_pct` | The commanded level, percent of MVC. |
| 1 | `phase` | Segment code stored as a float. This stream carries floats, so segment names are encoded as numbers. |

`myogestic.sources.target.PHASE_CODES` is frozen. Only add codes; never
renumber existing ones. Analysis scripts must read recordings across versions.

```
rest 0 · ramp_up 1 · hold 2 · ramp_down 3 · recover 4 · done 5 · idle 6
```

`idle` marks time before the first Start and between blocks. Both `idle` and `rest` hold the level at 0. Separate codes keep setup time
out of the block's rest phase, so a configured 3 s rest excludes the wait
for the operator to press Start.

The recorded trajectory shares the EMG's `local_clock()` domain sample by sample.
It preserves the target used during the take without reconstructing it from
a start time and saved settings. Reconstruction would depend on two clocks
agreeing and on nobody editing a segment between noting the settings and
recording the take.

Two consequences of it being a real stream:

- Call `target_stream.reconnect()`. `start_recording` silently skips streams
  whose `info is None` because it has no schema to allocate their arrays. An
  unattached target stream is absent from the session.
- It emits baseline while stopped, marked `idle`, to keep data continuous
  between blocks. A source that stops producing leaves a hole exactly where the
  operator was setting the next block up, and a hole is indistinguishable from a
  dropout at analysis time.

Recording and the task are separate buttons on purpose. Press Record, then run
as many blocks as the protocol requires, then Stop. One session contains every
repetition, marked by the phase channel.

## Read it back

The target is a stream in the archive like any other, so everything in
[Record and replay](record-and-replay.md) applies unchanged:

```python
from myogestic.session import open_session_store

sess = open_session_store("data/recordings/20260517-1423.mg.zip")

emg, emg_ts = sess.get_continuous("emg")  # (N, n_ch) sample-major
target, target_ts = sess.get_continuous("target")  # (M, 2)

level = target[:, 0]  # percent of MVC
phase = target[:, 1]  # PHASE_CODES
```

Use the phase code to extract blocks from a session. The gap codes supply
everything needed; no start time, settings or second clock is required.

```python
import numpy as np

from myogestic.sources.target import PHASE_CODES

running = phase != PHASE_CODES["idle"]
edges = np.flatnonzero(np.diff(running.astype(np.int8)))
bounds = np.concatenate(([0], edges + 1, [len(running)]))
blocks = [
    (target_ts[a], target_ts[b - 1])
    for a, b in zip(bounds[:-1], bounds[1:])
    if b > a and running[a]
]
```

Align by timestamps because the target runs at 100 Hz and EMG at kilohertz.
Do not align by sample index. For training,
[`iter_aligned_windows`][myogestic.session.iter_aligned_windows] does that for
you: each EMG window is paired with the target sample nearest its midpoint.

```python
from myogestic.recipes.features import rms
from myogestic.session import iter_aligned_windows

X, Y = [], []
for window, targets, ts in iter_aligned_windows(
    paths=["data/recordings/20260517-1423.mg.zip"],
    primary_stream_name="emg",
    aligned_stream_names=["target"],
    window_ms=200,
    hop_ms=50,
):
    level, phase = targets["target"]
    if phase != 2.0:  # plateau only — the ramps are a different problem
        continue
    X.append(rms(window))
    Y.append(level)
```

The exact `== 2.0` holds because `n_alignment_samples` defaults to 1, so the phase
comes from one recorded sample rather than a mean across a segment boundary. Raise it and
compare with a tolerance, or round.

Force regression usually needs hold segments rather than ramps. Use the
recorded phase channel to select them; the recording answers which samples
were holds without reconstructing them from remembered settings.

## See also

- [Pick a device from the UI](pick-a-device.md) - the picker, and the `include_aux`
  row on every OTB entry.
- [Connect OTB devices](connect-otb-devices.md) - channel geometry and scaling per
  amplifier, including what is in each accessory block.
- [Enable on-disk recording](enable-recording.md) - what a session is and how it is
  written.
- [Record and replay](record-and-replay.md) - reading sessions back, and the
  window iterators.
- [Record for proportional control](record-for-proportional-control.md) - the other
  recorded-target protocol, on the same `TargetSource` machinery: a signed cursor in
  `[-1, +1]` for decoder training. Force trapezoids use %MVC for motor-unit analysis.
