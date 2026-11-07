---
title: "Record for proportional control"
---
A proportional decoder estimates effort and direction. Half a contraction moves
the paddle half as fast. Cued Down, Rest and Up provide three distinct target
values. Recording only those cues leaves a three-class target problem
regardless of the estimator's name. Establish level coverage in the recording
before choosing a model. Tree ensembles benefit from more levels; a linear model can interpolate
between three. See [the measurement below](#the-active-ingredient-is-the-number-of-distinct-levels).

This page is the graded counterpart to [Record good training data](record-good-training-data.md),
which covers the cued protocol for classification.
[`examples/start_here/pong.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/start_here/pong.py)
records this block through its Follow the cursor button and fits it in Proportional mode.

## Error with three levels

On three 8-channel bracelet recordings of cued Down/Rest/Up, a CatBoost regressor
fitted to class values predicts rest below about 30 % effort.

A tree ensemble's output is an average of training targets, so it *cannot* emit a level
the block never asked for. A simulation of the same protocol reproduces this error:
at a true +0.50, the three-class fit emits -0.34. Fitting the same estimator on
densely covered levels cuts intermediate-effort error 14x, with CatBoost MAE
0.402 → 0.029.

!!! warning "Check monotonicity in effort"
    The same recordings also made CatBoost non-monotonic in effort: scaling every
    channel by 1.0 → 1.3 → 1.6 walked its Up prediction 1.000 → 0.882 → 0.723, so
    contracting harder drove the paddle the wrong way. This is an estimator
    failure; adding dense target levels does not fix it. Refit the same CatBoost on a full
    `Pursuit` block (411 distinct levels, the protocol below) and the same sweep still
    reads 0.811 → 0.905 → 0.849, still non-monotone, with or without the "Down was
    recorded harder" asymmetry that caused it. `directional_decoder` on the identical
    block reads 0.792 → 1.0 → 1.0. One regressor over raw features conflates effort
    and direction. No recording protocol can separate those quantities for it;
    the estimator must do so. See [Fit it](#fit-it).

## The active ingredient is the number of distinct levels

!!! warning "Distinct target levels"
    The measured factor is the number of distinct target levels. It does not
    establish a benefit from pursuit or continuity. A cued staircase of eleven holds beat the pursuit block on the
    same metric, 0.0367 against 0.0548 MAE, on 4 of 4 seed pairs.

    The gain applies to the tree ensembles this project ships. A linear model
    gains nothing because least squares interpolates between three levels.

Do not choose a followed cursor on the claim that it is more accurate than
a staircase. The reason to prefer it is human feedback.
A cursor gives participants continuous visual error feedback to reach intermediate
levels. A staircase cue such as "go to 0.6" requires them to judge what 0.6 feels like.

Choose the protocol for your estimator:

- If your estimator is linear, this protocol buys you nothing. Record whatever is
  convenient.
- A cued staircase can use eleven holds to cover intermediate levels; three holds leave sparse coverage.

## Record the block

[`Pursuit`][myogestic.tracking.Pursuit] is the trajectory: rest at exactly `0.0`, then a
smooth aperiodic wander over signed `[-1, +1]`, then rest again. It is deterministic
arithmetic on the hop index, so two sessions record the identical path and an offline
script can assert an exact value.

[`TargetSource`][myogestic.sources.TargetSource] records the cursor as a stream
on the EMG's clock, providing aligned targets for training. Reconstructing
from a start time and saved parameters would require trusting that the clocks
agree and that nobody edited the parameters between the note and the take.

```python
from myogestic import Stream
from myogestic.sources import TargetSource
from myogestic.tracking import Pursuit

# Defaults are a 58 s block: 5 s rest, 24 hops of 2 s, 5 s recover.
cursor = TargetSource(Pursuit())
target_stream = Stream("target", source=cursor, window_ms=200)
```

Follow these four wiring steps:

- Call `target_stream.reconnect()`. A software source has nothing physical to
  attach it automatically. `start_recording` silently skips a stream whose `info is None`.
- Press Record first, then start the block. `cursor.start()` restarts task time from
  zero; the stream runs from `reconnect()` to `disconnect()` either way.
- Exclude the target with `DevicePicker("emg", exclude=("target",))`.
  One stray Connect replaces the `TargetSource` with an amplifier and the recording holds
  EMG under the name `target`.
- Draw the cursor from `cursor.elapsed`, not from a fresh clock reading. It is the task
  time of the newest sample actually *emitted*, so the ghost cannot sit a frame off the
  ground truth the model is later fitted against.

`Pursuit` accepts `hop_s`, `hops` and `reps`. `hop_s` sets seconds per waypoint
segment; halving it doubles every rate while preserving levels. Fewer than about
16 `hops` can leave clustered coverage. Increase `hops` to lengthen a block;
repetitions are identical and can be learned after the first.

## Fit it

[`iter_target_windows`][myogestic.session.iter_target_windows] pairs each EMG window with
the recorded cursor value at the window's end. This trains the model to estimate
the current command from a trailing window. This is the causal target choice. A centre target is half a window
behind; a window mean introduces ramp lag.

By default it includes windows ending in followed phases. It excludes `PHASE_CODES`
`idle` and `done`, which hold target `0` before and after a block. Those
phases have no following task, and the participant may move freely, so their
zero targets do not describe the participant's effort.

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
protocol uses. It estimates effort from the row total, rescaled to 0 at rest
and 1 at full contraction. It estimates direction by projecting the
amplitude-normalized row onto a Fisher axis, then multiplies effort and direction.
A regressor over raw features can conflate the two and learn the louder cue,
causing the non-monotonic CatBoost behaviour above. It requires only NumPy. `catboost_regressor` also works on this data and is the
comparison worth running; it is the estimator the 14x number above was measured on.

## Check before the participant does

Assert that the decoder is monotonic in effort:

<!--docs:run-->
```python
probe = [-1.0, -0.5, 0.0, 0.5, 1.0]
commands = model.predict(np.stack([features(synth(np.full(400, level)).T) for level in probe]))

print([round(float(c), 2) for c in commands])  # [-1.0, -0.59, -0.0, 0.61, 1.0]
assert np.all(np.diff(commands) > 0.0), "the fit is not monotonic in effort"
```

On real data the same check is a held-out probe at a few levels, plus a global gain sweep:
multiply every channel by 1.0 / 1.3 / 1.6 and the command must not *fall*. That is the
sweep CatBoost fails even on a densely covered block. Run it against whichever estimator you
actually ship; it is a property of the model, not of the recording.

!!! note "Gain invariance has a condition"
    `directional_decoder` divides each row by its own sum, so an electrode gain cancels
    only if every feature column answers it the same way. RMS, MAV and WL all scale by
    `g`; VAR scales by `g²` and ZC not at all. Mix two of those groups and the
    cancellation fails. Selecting VAR with RMS+MAV changed the mean Up command
    0.913 → 0.837 over a 1.3 → 3.0 gain sweep where RMS+MAV held flat. `pong.py` refuses a
    mixed set in Proportional mode.

## Decoder requirements

The effort scale is fitted per window and pooled by median, over the windows whose
target reaches `abs(y) >= 0.5`:

```text
span_ = median((total - rest_) / abs(y))    over abs(y) >= 0.5,  at least 3 windows
```

Two consequences for how you record:

- Record at least three windows at half deflection or above. Below this count,
  `fit` raises with the count and largest `abs(y)` instead of fitting two windows.
  A default `Pursuit()` block provides 165 qualifying windows, 55 times the floor of 3.
- The target must be in signed `[-1, +1]`. `fit` raises on any `abs(y) > 1`, because
  nothing else in it can see a unit error: a percent-of-MVC column divides through the
  span at up to 100 instead of 1, `activation` saturates, and the graded command becomes
  a three-step staircase with no complaint. See
  [Mixing cued and cursor sessions](#mixing-cued-and-cursor-sessions).
- Cued blocks retain the same scale. Every non-rest window has `abs(y) == 1`,
  so the threshold selects the same windows as `y != 0`. Dividing by 1 is a no-op
  and the median is translation-equivariant. The scaled-target and cued-only
  rules return identical floats on the three cued recordings with odd window counts.
  With even counts, `numpy.median` averages the two middle values; the measured
  worst-case difference is 1.8e-15.

The threshold trades bias for count. Dividing by `abs(y)` multiplies a window's noise by
`1 / abs(y)`, and an EMG baseline adds to the row total without scaling with effort, so
low-target windows read *high*:

| `abs(y)` threshold | 0.25 | 0.50 | 0.75 | 0.90 |
|---|---:|---:|---:|---:|
| fitted span (reference 4.23) | 4.40 | 4.29 | 4.24 | 4.22 |
| windows used | 301 | 165 | 68 | 25 |

0.5 caps the noise gain at 2x, lands 1.3 % high and keeps a third of the block. Getting
that to 0.1 % costs four fifths of the windows, which is the wrong side of the trade on a
short recording.

The direction estimate uses every non-rest window, including quiet ones.
This choice was measured. Restricting it to the same strong windows changed mean MAE
0.0820 → 0.0812 over five seed pairs, a 1 % difference that swaps sign across levels, for
two thirds fewer rows in the covariance.

## Mixing cued and cursor sessions

Both protocols produce a signed `[-1, +1]` target column and can train together.
Cued `Down / Rest / Up` correspond to constant levels `-1 / 0 / +1`.
This compatibility is the reason for the signed target standard.
[`split_sessions_by_stream`][myogestic.session.split_sessions_by_stream] routes each
session by target-stream presence, allowing cued recordings to contribute:

```python
from myogestic.session import iter_labeled_windows, iter_target_windows, split_sessions_by_stream

split = split_sessions_by_stream(paths, "target")

for path in split.with_stream:  # cursor blocks: the recorded level
    for window, _ts, level in iter_target_windows([path], "emg", "target", 200, 100):
        ...

for path in split.without_stream:  # cued blocks: the class as a level
    for window, _ts, class_index in iter_labeled_windows([path], "emg", 200, 100):
        ...
```

Do not expect three cued sessions plus one cursor session to behave like
four cursor sessions. Distinct target levels matter, and a fit dominated
by cued data still sees mostly three levels.

!!! danger "Check target units and followed phases"
    `split.with_stream` checks stream presence only. It does not validate units
    or content. Both traps below can worsen a model without an error from
    the split itself. Check them before fitting.

    A force-ramp session is not a cursor session. The other recorded-target protocol,
    [Track a force target](track-a-force-target.md), writes its `Trapezoid` through the
    same `TargetSource`, onto a stream also called `target`, with the identical channel
    names, in percent of MVC, `0..100`. A `StreamInfo` carries no unit, so nothing
    in the recording distinguishes the two, and the same `recordings/` folder holds both.
    Concatenated with a cursor block, one such session collapsed
    `directional_decoder`'s `span_` from 4.17 to 0.046 and turned a graded transfer curve
    into a hard three-step staircase. `fit` refuses any `abs(y) > 1`, and
    `pong.py`'s `train` names and refuses each such session. Range-check any target
    column you assemble yourself.

    A cued session can carry an idle target stream. `TargetSource` keeps emitting
    baseline with phase `idle` after the block ends, by design, and the stream stays
    attached. Cued takes after a pursuit block therefore carry a `target` stream. `split_sessions_by_stream` puts it in `with_stream`; `iter_target_windows` then
    correctly drops all of it, because `idle` is not a followed phase; and its label track
    is never read. Treat the target path as the *preferred* reading and the label track as
    the fallback. If the target path yields no windows for a session,
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
