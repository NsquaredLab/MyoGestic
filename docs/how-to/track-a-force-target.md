# Track a force target

Isometric force tracking: the subject holds a joint still against a transducer and
squeezes to match a trapezoid drawn on screen — rest, ramp up, hold, ramp down,
recover. It is the standard HD-EMG protocol for motor-unit work, because a slow
linear ramp into a steady plateau is what makes recruitment order and discharge
rates readable, and it is the task OT Bioelettronica's own acquisition software
provides. `TrackingTask` is that task inside your app, against whichever amplifier
the [device picker](pick-a-device.md) is holding.

`examples/panels/tracking_task.py` runs the whole loop against a synthetic sine if
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
    channel=64,                       # the AUX channel the transducer is on
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

The shape is passed to the **task**, not to the source. The task forwards every
edit to the source it was handed, so what is drawn and what is recorded cannot be
two different trapezoids — which is also why you construct `TargetSource()` bare.

## Wire the force in

The transducer is not a biosignal channel. It goes into an **auxiliary input** on
the amplifier and arrives on the same stream as the EMG, appended after the bio
block — but only if you ask for it. Every OTB entry in the picker has an
`include_aux` row, off by default:

| Device | Picker row | What gets appended | Where the force lands |
|---|---|---|---|
| Muovi, Muovi+ | `IMU + counters` | 6: quaternion `w x y z`, buffer/trigger, sample counter | **nowhere** — no analogue input |
| Quattrocento | `AUX IN + accessory` | 16 AUX IN, then 8 accessory | any of the 16 back-panel AUX IN |

One exception worth knowing before you order a transducer. A **Muovi** has no
analogue input at all — its accessory block is IMU and counters, which is why the
row is named for what is in it rather than "AUX".

**Do not count channel indices.** The panel's *Channel* dropdown lists the
stream's own channel names, so you pick `aux0` by name. The index behind it moves
with the channel count and the detection mode. `channel=` in the constructor is
only where the dropdown opens.

Turning `include_aux` on has one cost worth knowing: the appended channels are
raw, unscaled counts on a Muovi, sitting in the same stream as
bio channels scaled to millivolts. A shared plot range across both is useless.
That is why it is off by default, and why the signal viewer is worth pointing at
the bio channels while the force lives in this panel.

## Calibrate: two numbers, not one

The target is a percentage of MVC, so a raw reading has to be mapped onto that
scale before the two traces mean anything against each other. That takes **two**
captures, not one:

- **Zero** — the resting reading, subject relaxed, hand off the transducer.
- **MVC** — press it and push as hard as possible; the peak over the next three
  seconds is kept.

The reason it is two is that a load cell does not read zero at rest. It has a
resting offset — preload, its own weight, the amplifier's DC bias — and that
offset is in every sample. Normalise against MVC alone and you get nonsense: a
cell resting at 1.0 with an MVC of 3.0 makes a relaxed subject read 33 %, and a
30 % target becomes a force they are already past by doing nothing. `Calibration`
subtracts `zero` from the sample *and* from the maximum, so the percentage is of
the subject's voluntary range and 30 % is really 30 %.

Both captures read the same thing the live trace does: the mean of the last
`tail_ms` (100 ms by default) of the chosen channel, not a single sample. One raw
sample off a load cell is noise with a force in it.

Units never come up. `Calibration` is a two-point map in whatever the channel
happens to carry, so it works identically on raw counts and on Quattrocento
volts — you do not need the transducer's datasheet to run the task,
only to report newtons afterwards.

**Start stays disabled until both exist**, and says so on hover. Recapture Zero
whenever the subject repositions; the transducer's offset moves with the grip.

## Give the force its own stream

Point the task at a stream that carries **only** the force, not at the EMG
stream:

```python
app.streams(
    Stream("emg", source=..., window_ms=200),
    Stream("force", source=..., window_ms=200),
    Stream("target", source=target, window_ms=200),
)
task = TrackingTask("force", target=target)
```

Sharing the EMG stream works — the force is a channel of it if the transducer is
wired to an amplifier AUX input — but it couples the two panels: connecting the
amplifier makes the force panel come alive, for a signal it has nothing to do
with. A separate stream keeps each panel answering for its own subject.

If the transducer *is* on an AUX channel and you want one stream, that is fine —
turn the picker's aux row on and point the task's Channel at it. Just know that
the two panels then rise and fall together, because they are reading the same
device.

Keep the target out of the picker's reach while you are at it:

```python
DevicePicker("emg", selectable=True, exclude=("target",))
```

The target stream is the task's own output. Offered as a device stream, one
Connect replaces the `TargetSource` the task is driving — leaving the task
writing to a source attached to nothing, and the recording holding an
amplifier's data under the name `target`.

## Try it without a transducer

`SyntheticForceSource` is a stand-in **transducer** — not a stand-in subject.
You are the subject: watch the target and drag `effort`, exactly as the person
on a real load cell watches the plot and pushes.

```python
from myogestic import Stream
from myogestic.sources import SyntheticForceSource, TargetSource

target = TargetSource()                       # bare: `TrackingTask` owns the shape
force = SyntheticForceSource()                # 0.30 V at rest, 2.30 V at full effort
app.streams(Stream("force", source=force), Stream("target", source=target))
```

`SyntheticSource` cannot stand in for this. Its channels are fixed sine waves —
no resting level to zero, no peak to calibrate against, nothing that responds to
a target.

Two details it gets deliberately right, so a rehearsal behaves like the real
thing rather than flattering you:

- **The resting reading is not zero.** A transducer has an offset, and a
  calibration that assumes otherwise puts every target at the wrong force. Here
  you can make that mistake and watch it happen.
- **It smooths your slider.** Dragging a slider is a step; a muscle is not.
  `lag_s` is a first-order time constant so a drag reads as a contraction. Set
  it to `0` to follow the slider exactly.

**Nothing follows the target for you**, deliberately. A channel that tracked on
its own would draw a tracking error nobody produced — and that error is the one
number the task exists to measure.

To capture an MVC, raise `effort` — no block is running then, so the target is
asking for nothing and effort is the only thing driving the channel.

## Shape the trapezoid

Every segment is a row in the panel and a field on `Trapezoid`, in the order they
happen:

| Field | Default | What it is |
|---|---|---|
| `rest_s` | 3.0 | Baseline before the ramp — the pre-contraction reference every analysis needs. |
| `ramp_up_s` | 5.0 | Linear rise to `level_pct`. Recruitment happens here, so slow enough to resolve it. |
| `hold_s` | 10.0 | Seconds at the plateau. The steady-state segment discharge-rate estimates come from. |
| `ramp_down_s` | 5.0 | Linear fall back to baseline — de-recruitment, the mirror of the ramp up. |
| `recover_s` | 5.0 | Baseline after, before the next repetition. Fatigue control, not padding. |
| `level_pct` | 30.0 | Plateau height, in percent of MVC. |
| `reps` | 1 | How many times the shape repeats back to back. |

Beside those rows the panel draws the block they add up to, every repetition of it,
captioned with how long it runs — `3 x 28.0 s = 84.0 s`. Seven fields are a shape
nobody can see, and the total is arithmetic nobody does before pressing Start on a
subject. It is drawn from the same corners the plot uses, so the preview cannot
disagree with what eventually runs.

Ticks under the drawing divide it into the five segments and name them, so **Ramp
down** is a piece of a shape rather than a word above a number. Put the pointer on a
row and that segment lights up in every repetition, with its own value spelled out
above the drawing; put the pointer on the drawing instead and it names the segment
under it. Either direction answers the same question — *which part of this is the
hold?*

A segment too narrow to hold its name loses the label rather than overlapping its
neighbour, so at several repetitions the drawing quietly goes back to being the
block overview. The lit segment is still named above it, which is the case where you
are asking.

Height is not to scale — the plateau reaches the top whatever the level is. What the
drawing is for is the part no field states, the arrangement in *time*; **Level** says
the height, and a second copy of that number here would be one more thing to keep in
step.

## What the subject sees

The plot frames **one repetition at a time**, not the whole block — that is what
the sketch up in the Target section is for. Five reps on one axis leaves none of
them readable, and the thing you are watching is the gap between two lines. The
trace starts over on each rep and the status line counts them: `rep 2/5`.

Your force is drawn left to right up to the moment; the target is drawn only as
far as **Look ahead** seconds past it. That is deliberate. A block whose ending
is visible from the first frame is a shape to memorise rather than one to follow,
which is not what the task measures. Set it to zero to reveal nothing at all, or
to a full repetition to show the whole trajectory in advance.

Look ahead is a *display* setting, not part of the trajectory — it changes what
the subject can see coming, not what they are asked to do, so it is not a field
on `Trapezoid` and is not written into the block's record.

Reps roll straight on: the recover segment is the rest between them, so the block
is one continuous recording and only the plot reframes.

**Any segment may be zero**, and a zero-length one is skipped rather than
rejected: `hold_s=0` is a legal triangle, `rest_s=0` starts the ramp immediately.
`Trapezoid` is frozen and validates on construction, and the panel's rows clamp to
what it accepts, so dragging a field can change the shape but never raise.
`duration` is one repetition, `total_duration` the whole block.

The block **ends by itself** at `total_duration` — the same event as pressing
Stop, and the trace stays on the plot for review either way.

The plot's y range is pinned to the target rather than autoscaled. With per-frame
autoscaling a subject who is 5 % off and one who is 50 % off draw the same
picture, which is precisely what this plot exists to distinguish.

## The target is recorded as a stream

`TargetSource` implements the same `connect` / `read` / `disconnect` contract as
an amplifier, so a `Stream` records it exactly as it records EMG. Two channels, at
100 Hz by default:

| Channel | Name | Contents |
|---|---|---|
| 0 | `target_pct` | The commanded level, percent of MVC. |
| 1 | `phase` | Which segment, as a number — a stream carries floats, not strings. |

`myogestic.sources.target.PHASE_CODES` is the key, and it is **frozen**: codes are
added, never renumbered, because an analysis script written next year reads
sessions recorded today.

```
rest 0 · ramp_up 1 · hold 2 · ramp_down 3 · recover 4 · done 5 · idle 6
```

`idle` is the stretch with no block running — before the first Start, and between
blocks. It is a separate code from `rest` although both hold the level at 0,
because otherwise the wait while the operator sets the next block up would merge
into that block's rest phase, and a rest phase configured for 3 s would measure
however long the button took to press.

Recording the trajectory beats reconstructing it. The alternative is storing a
start time plus a copy of the task settings and rebuilding the curve months later,
which means trusting two clocks to agree and trusting that nobody dragged a
segment between the note and the take. As a stream it is sample-by-sample on the
same `local_clock()` domain as the EMG, aligned by construction.

Two consequences of it being a real stream:

- **`target_stream.reconnect()` is not optional.** `start_recording` silently
  skips a stream whose `info is None` — no schema, nothing to allocate — so an
  unattached target stream simply does not appear in the session.
- **It emits baseline while stopped**, marked `idle`, rather than going quiet
  between blocks. A source that stops producing leaves a hole exactly where the
  operator was setting the next block up, and a hole is indistinguishable from a
  dropout at analysis time.

Recording and the task are separate buttons on purpose. Press **Record**, then run
as many blocks as the protocol wants, then **Stop** — one session, every
repetition in it, with the phase channel marking where each one was.

## Read it back

The target is a stream in the archive like any other, so everything in
[Record and replay](record-and-replay.md) applies unchanged:

```python
from myogestic.session import open_session_store

sess = open_session_store("sessions/2026-05-17_14-23-05.session.zip")

emg, emg_ts = sess.get_continuous("emg")        # (N, n_ch) sample-major
target, target_ts = sess.get_continuous("target")  # (M, 2)

level = target[:, 0]        # percent of MVC
phase = target[:, 1]        # PHASE_CODES
```

Because the gaps carry their own code, the blocks cut out of a session without
consulting anything else — no start times, no settings, no second clock:

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

The rates differ — 100 Hz of target against kilohertz of EMG — which is why you
align on timestamps and not on sample index. For training,
[`iter_aligned_windows`][myogestic.session.iter_aligned_windows] does that for
you: each EMG window is paired with the target sample nearest its midpoint.

```python
from myogestic.recipes.features import rms
from myogestic.session import iter_aligned_windows

X, Y = [], []
for window, targets, ts in iter_aligned_windows(
    paths=["sessions/2026-05-17_14-23-05.session.zip"],
    primary_stream_name="emg",
    aligned_stream_names=["target"],
    window_ms=200,
    hop_ms=50,
):
    level, phase = targets["target"]
    if phase != 2.0:        # plateau only — the ramps are a different problem
        continue
    X.append(rms(window))
    Y.append(level)
```

The exact `== 2.0` holds because `n_alignment_samples` defaults to 1, so the phase
is one recorded sample rather than a mean across a segment boundary. Raise it and
compare with a tolerance, or round.

Filtering on the phase channel is the point of carrying it. A model trained to
regress force from EMG usually wants the hold segments and not the ramps, and
"which samples were the hold" is a question the recording answers rather than one
you re-derive from the settings you think you used.

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
  `[-1, +1]` instead of a trapezoid in %MVC, for training a decoder rather than for
  motor-unit analysis.
