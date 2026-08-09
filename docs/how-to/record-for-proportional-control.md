# Record for proportional control

A decoder is *proportional* when it answers **how hard** as well as **which way**: half a
contraction moves the paddle half as fast. Getting that is a recording problem before it
is a modelling one, and the short statement of it is this — a block that only ever cues
Down, Rest and Up asks for **three distinct target values**, so the fit is a three-class
problem however you label it. What that *costs* depends on the estimator, and the
[warning below](#the-active-ingredient-is-the-number-of-distinct-levels) is where the
exception lives: it is expensive for the tree ensembles this project ships and free for
a linear model.

This page is the graded counterpart to [Record good training data](record-good-training-data.md),
which covers the cued protocol for classification.
[`examples/start_here/pong.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/start_here/pong.py)
is the whole thing as a running application: its **Follow the cursor** button records the
block described here, and its Proportional mode fits it.

## What three levels cost you

Measured on three 8-channel bracelet recordings of cued Down/Rest/Up, fitting a CatBoost
*regressor* on the class values, it is **dead below about 30 % effort** — everything under
that reads as rest.

A tree ensemble's output is an average of training targets, so it *cannot* emit a level
the block never asked for. Simulating the same protocol reproduces the pathology exactly:
at a true +0.50, the three-class fit emits **-0.34**. Fitting the same estimator on
densely covered levels instead cuts the error at intermediate efforts 14x — CatBoost MAE
**0.402 → 0.029**.

!!! warning "One famous symptom this protocol does *not* fix"
    The same recordings also made CatBoost **non-monotonic in effort**: scaling every
    channel by 1.0 → 1.3 → 1.6 walked its Up prediction 1.000 → 0.882 → 0.723, so
    contracting harder drove the paddle the wrong way. That one is the *estimator*, not
    the level count, and dense levels do not touch it — refit the same CatBoost on a full
    `Pursuit` block (411 distinct levels, the protocol below) and the same sweep still
    reads 0.811 → 0.905 → 0.849, still non-monotone, with or without the "Down was
    recorded harder" asymmetry that caused it. `directional_decoder` on the identical
    block reads 0.792 → 1.0 → 1.0. See [Fit it](#fit-it) for why: one regressor over raw
    features conflates *how much* with *which way*, and no recording protocol can
    separate them for it.

## The active ingredient is the number of distinct levels

!!! warning "What the measurement does and does not say"
    The thing that was measured is the **number of distinct target levels** — not pursuit,
    and not continuity. A cued **staircase of eleven holds beat the pursuit block** on the
    same metric, **0.0367 against 0.0548 MAE, on 4 of 4 seed pairs**.

    The win is also specific to the tree ensembles this project ships. **A linear model
    gains nothing at all**, because least squares already draws a straight line through
    three levels.

    So do not pick a followed cursor because it is more accurate than a staircase. It is
    not.

The reason to prefer a cursor is **human**, not statistical. Told "go to 0.6", a subject
has no idea what 0.6 feels like — a staircase asks for levels they cannot aim at. A cursor
gives continuous visual error feedback, so they see the miss while they are missing it,
which is what makes the intermediate levels reachable at all.

Two corollaries worth acting on:

- If your estimator is **linear**, this protocol buys you nothing. Record whatever is
  convenient.
- If you would rather **cue a staircase**, cue one. Eleven holds is enough; three is not.

## Record the block

[`Pursuit`][myogestic.tracking.Pursuit] is the trajectory: rest at exactly `0.0`, then a
smooth aperiodic wander over signed `[-1, +1]`, then rest again. It is deterministic
arithmetic on the hop index, so two sessions record the identical path and an offline
script can assert an exact value.

[`TargetSource`][myogestic.sources.TargetSource] streams it, which is the part that makes
it trainable — the cursor lands in the session as a recorded signal on the EMG's own
clock, aligned by construction, rather than as a start time plus a copy of the parameters
you hope nobody edited.

```python
from myogestic import Stream
from myogestic.sources import TargetSource
from myogestic.tracking import Pursuit

# Defaults are a 58 s block: 5 s rest, 24 hops of 2 s, 5 s recover.
cursor = TargetSource(Pursuit())
target_stream = Stream("target", source=cursor, window_ms=200)
```

Four things about the wiring, each of which is a way to end up with an unusable session:

- **`target_stream.reconnect()` is not optional.** It is software, so nothing plugs in and
  nothing else attaches it; `start_recording` silently skips a stream whose `info is None`.
- **Press Record first, then start the block.** `cursor.start()` restarts task time from
  zero; the stream runs from `reconnect()` to `disconnect()` either way.
- **Keep the target out of the device picker** — `DevicePicker("emg", exclude=("target",))`.
  One stray Connect replaces the `TargetSource` with an amplifier and the recording holds
  EMG under the name `target`.
- **Draw the cursor from `cursor.elapsed`**, not from a fresh clock reading. It is the task
  time of the newest sample actually *emitted*, so the ghost cannot sit a frame off the
  ground truth the model is later fitted against.

The knobs on `Pursuit` are `hop_s` (seconds per waypoint-to-waypoint segment — the
difficulty knob; halving it doubles every rate without changing the levels visited),
`hops` (fewer than about 16 and the level coverage starts to clump) and `reps`. Raise
`hops` rather than `reps` to lengthen a block: repetitions are identical by design, so
every one after the first is learnable.

## Fit it

[`iter_target_windows`][myogestic.session.iter_target_windows] pairs each EMG window with
the recorded cursor value **at the window's end**. That is deliberate and it is the causal
choice: the model sees a trailing window and must emit the command for *now*. Taking the
centre would train it to predict the past by half a window; taking the mean would train it
to lag every ramp.

By default it yields only windows ending in a phase where the subject was actually
following — every code in `PHASE_CODES` except `idle` (no block running) and `done` (block
finished), both of which sit at target `0` while the subject does whatever they like.

The block below fabricates a rehearsal recording so the page is self-checking; with a real
session you replace the path and keep everything from `features` down.

<!--docs:run-->
```python
import tempfile

import numpy as np

from myogestic.session import Session
from myogestic.sources.target import PHASE_CODES
from myogestic.stream import StreamInfo
from myogestic.tracking import Pursuit

task = Pursuit(rest_s=1.0, hop_s=0.5, hops=24, recover_s=1.0)  # short, so this runs fast
fs, target_fs = 1000.0, 100.0
rng = np.random.default_rng(0)

# Channels 0-3 answer Down, 4-7 answer Up; every channel grows with effort.
side = np.where(np.arange(8) < 4, -1.0, 1.0)


def synth(levels: np.ndarray) -> np.ndarray:
    """Synthetic EMG for a column of signed effort levels — one row per sample."""
    return rng.normal(scale=0.05 + 0.45 * np.maximum(levels[:, None] * side, 0.0))


sess = Session(base_path=tempfile.mkdtemp())
sess.init_stream("emg", StreamInfo(n_channels=8, fs=fs, dtype=np.dtype("float32")))
sess.init_stream(
    "target",
    StreamInfo(
        n_channels=2,
        fs=target_fs,
        dtype=np.dtype("float32"),
        channel_names=["target_pct", "phase"],
    ),
)

emg_ts = np.arange(int(task.total_duration * fs)) / fs
sess.append("emg", synth(np.array([task.value_at(t) for t in emg_ts])).astype(np.float32), emg_ts)

target_ts = np.arange(int(task.total_duration * target_fs)) / target_fs
sess.append(
    "target",
    np.array(
        [(task.value_at(t), PHASE_CODES[task.phase_at(t)]) for t in target_ts], dtype=np.float32
    ),
    target_ts,
)
sess.save_meta("cursor rehearsal")
```

<!--docs:run-->
```python
from myogestic.recipes.estimators import directional_decoder
from myogestic.recipes.features import mav, rms
from myogestic.session import iter_target_windows


def features(window: np.ndarray) -> np.ndarray:
    """RMS and MAV of one channels-first window, stacked into one row."""
    return np.concatenate([rms(window), mav(window)])


X, y = [], []
for window, _ts, level in iter_target_windows([str(sess.path)], "emg", "target", 200, 100):
    X.append(features(window))
    y.append(level)

model = directional_decoder().fit(np.stack(X), np.array(y))
```

[`directional_decoder`][myogestic.recipes.estimators.directional_decoder] is the model this
protocol was built for: it estimates *how much* (the row total, rescaled so rest reads 0
and a full contraction 1) and *which way* (the amplitude-normalised row on a Fisher axis)
apart, then multiplies them. A regressor over raw features conflates the two and learns
whichever cue happened to be louder — which is where the non-monotonic CatBoost above came
from. It has no dependencies. `catboost_regressor` also works on this data and is the
comparison worth running; it is the estimator the 14x number above was measured on.

## Check before the subject does

The property the protocol buys is monotonicity in effort, so assert it:

<!--docs:run-->
```python
probe = [-1.0, -0.5, 0.0, 0.5, 1.0]
commands = model.predict(np.stack([features(synth(np.full(400, level)).T) for level in probe]))

print([round(float(c), 2) for c in commands])   # [-1.0, -0.59, -0.0, 0.61, 1.0]
assert np.all(np.diff(commands) > 0.0), "the fit is not monotonic in effort"
```

On real data the same check is a held-out probe at a few levels, plus a global gain sweep:
multiply every channel by 1.0 / 1.3 / 1.6 and the command must not *fall*. That is the
sweep the shipped CatBoost regressor failed, and — as the warning at the top of this page
says — still fails on a densely covered block. Run it against whichever estimator you
actually ship; it is a property of the model, not of the recording.

!!! note "Gain invariance has a condition"
    `directional_decoder` divides each row by its own sum, so an electrode gain cancels
    only if **every** feature column answers it the same way. RMS, MAV and WL all scale by
    `g`; VAR scales by `g²` and ZC not at all. Mix two of those groups and the
    cancellation goes — ticking VAR beside RMS+MAV walked the mean Up command
    0.913 → 0.837 over a 1.3 → 3.0 gain sweep where RMS+MAV held flat. `pong.py` refuses a
    mixed set in Proportional mode rather than training on it.

## What the decoder needs from the block

The effort scale is fitted **per window** and pooled by median, over the windows whose
target reaches `abs(y) >= 0.5`:

```text
span_ = median((total - rest_) / abs(y))    over abs(y) >= 0.5,  at least 3 windows
```

Two consequences for how you record:

- **The block must ask for at least half deflection, at least three times.** Below that
  `fit` **raises**, naming the count and the largest `abs(y)` in the block, rather than
  quietly fitting a span on two windows. A default `Pursuit()` block clears the bar 55
  times over — 165 qualifying windows against a floor of 3.
- **The target must be in signed `[-1, +1]`.** `fit` raises on any `abs(y) > 1`, because
  nothing else in it can see a unit error: a percent-of-MVC column divides through the
  span at up to 100 instead of 1, `activation` saturates, and the graded command becomes
  a three-step staircase with no complaint. See
  [Mixing cued and cursor sessions](#mixing-cued-and-cursor-sessions).
- **A cued block is unaffected, exactly.** There every non-rest window has `abs(y) == 1`,
  so the threshold selects the same windows as `y != 0`, dividing by 1 is a no-op, and a
  median is translation-equivariant. On the three cued recordings both the old and the new
  rule return the identical float. (Bit-for-bit needs an odd number of qualifying windows;
  on an even count `numpy.median` averages the two middle elements and the two rules part
  company in the last bit — measured at 1.8e-15 worst case.)

The threshold trades bias for count. Dividing by `abs(y)` multiplies a window's noise by
`1 / abs(y)`, and an EMG baseline adds to the row total without scaling with effort, so
low-target windows read *high*:

| `abs(y)` threshold | 0.25 | **0.50** | 0.75 | 0.90 |
|---|---:|---:|---:|---:|
| fitted span (reference 4.23) | 4.40 | **4.29** | 4.24 | 4.22 |
| windows used | 301 | **165** | 68 | 25 |

0.5 caps the noise gain at 2x, lands 1.3 % high and keeps a third of the block. Getting
that to 0.1 % costs four fifths of the windows, which is the wrong side of the trade on a
short recording.

The **direction** estimate uses every non-rest window, including the quiet ones. That was
measured rather than assumed: restricting it to the same strong windows moved mean MAE
0.0820 → 0.0812 over five seed pairs, a 1 % difference that swaps sign across levels, for
two thirds fewer rows in the covariance.

## Mixing cued and cursor sessions

They train together. Both protocols produce the same signed `[-1, +1]` column — a class is
a constant target, so `Down / Rest / Up` are just the levels `-1 / 0 / +1` — which is the
whole reason for having a signed standard.
[`split_sessions_by_stream`][myogestic.session.split_sessions_by_stream] routes each
session by whether it carries the target stream, so recordings made before the cursor
existed still contribute:

```python
from myogestic.session import iter_labeled_windows, iter_target_windows, split_sessions_by_stream

split = split_sessions_by_stream(paths, "target")

for path in split.with_stream:                      # cursor blocks: the recorded level
    for window, _ts, level in iter_target_windows([path], "emg", "target", 200, 100):
        ...

for path in split.without_stream:                   # cued blocks: the class as a level
    for window, _ts, class_index in iter_labeled_windows([path], "emg", 200, 100):
        ...
```

Just do not expect three cued sessions plus one cursor session to behave like four cursor
sessions. The count that matters is distinct levels, and three of them dominate a fit that
is mostly made of them.

!!! danger "`split.with_stream` answers presence, not units, and not content"
    Two traps, both of which produce a worse model and neither of which raises on its own.

    **A force-ramp session is not a cursor session.** The other recorded-target protocol,
    [Track a force target](track-a-force-target.md), writes its `Trapezoid` through the
    same `TargetSource`, onto a stream also called `target`, with the identical channel
    names — in **percent of MVC**, `0..100`. A `StreamInfo` carries no unit, so nothing
    in the recording distinguishes the two, and the same `sessions/` folder holds both.
    Concatenated with a cursor block, one such session collapsed
    `directional_decoder`'s `span_` from 4.17 to 0.046 and turned a graded transfer curve
    into a hard three-step staircase. `fit` now refuses any `abs(y) > 1`, and
    `pong.py`'s `train` refuses it per session and names the file — but if you assemble
    the column yourself, range-check it.

    **A cued session can carry an idle target stream.** `TargetSource` keeps emitting
    baseline with phase `idle` after the block ends, by design, and the stream stays
    attached — so every cued take recorded after a pursuit block has a `target` stream in
    it. `split_sessions_by_stream` puts it in `with_stream`; `iter_target_windows` then
    correctly drops all of it, because `idle` is not a followed phase; and its label track
    is never read. Treat the target path as the *preferred* reading and the label track as
    the fallback, not as an either/or: if the target path yields no windows for a session,
    send that session to `iter_labeled_windows` before concluding it holds nothing.

## See also

- [Record good training data](record-good-training-data.md) - the cued protocol, and how
  many cycles a classifier actually needs.
- [Track a force target](track-a-force-target.md) - the other recorded-target protocol:
  isometric trapezoids in percent of MVC, on an amplifier AUX channel.
- [Examples directory](../tutorials/examples-index.md) - `start_here/pong.py`, this page
  as an application.
- [Estimator recipes](../api/models.md) - `directional_decoder` in full, including the
  measurements behind it.
