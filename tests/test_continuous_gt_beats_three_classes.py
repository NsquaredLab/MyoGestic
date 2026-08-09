"""A decoder trained on a followed cursor interpolates; one trained on three cues does not.

The claim this file exists to defend. Cueing Down / Rest / Up and fitting a regressor to
targets of -1 / 0 / +1 leaves the model three distinct target values: it has never seen an
intermediate one, so what it emits for half a contraction comes from its own inductive
bias rather than from anything the data taught it — see the paragraph on least squares
below, which is where that stops costing anything. Recording a *pursuit* block instead —
the subject follows a moving cursor, and the cursor's own position is the label — puts
training targets densely across [-1, +1], so interpolation is measured.

Both arms here are the same simulated subject, the same features, the same estimator and
(within a few windows) the same number of training windows. The **only** difference is
which target values the block asked for. So a difference in the result is a difference in
the data.

What the difference is *not* evidence for
-----------------------------------------
The active ingredient is the number of distinct levels in the training set — not pursuit,
not continuity, and not the fact that the subject was tracking something.
`test_the_mechanism_is_level_coverage_not_pursuit` runs the control that separates those:
a cued staircase of eleven holds over the identical block length, everything else held
fixed, matches the pursuit arm and generally beats it (0.037 against 0.055 intermediate
MAE on the shipped seeds, on 4 of 4 seed pairs). The ladder is monotone in level count —
3 holds 0.33, 5 holds 0.17, 7 holds 0.10, 11 holds 0.04. Three cues are not too few
*cues*; they are too few *levels*.

So the claim this file establishes is "sample the level axis densely", and that is all.
It does not by itself justify `Pursuit` over a long staircase. The reasons to prefer
pursuit are real but are not measured here: a staircase is motionless at every level, so
it confounds level with a zero rate of change and contains no transitions at all, and
eleven cued holds are eleven things for an operator to run against one block that runs
itself.

The simulated subject
---------------------
`SyntheticSource` already models the right structure: `activation` scales every sine,
`direction` shifts that amplitude between the first half of the channels and the second —
an agonist and its antagonist. A subject asked for a signed level ``v`` is mapped
``activation = |v|``, ``direction = v``: both knobs move, because someone asked for half a
deflection contracts less hard *and* biases less strongly. (The alternative,
``direction = sign(v)``, would make the generator literally the ``activation x direction``
model `directional_decoder` assumes, and any result would be about that coincidence.)

Three imperfections are layered on, because a subject who tracks a cursor perfectly makes
the whole exercise a tautology — the label would be the input:

- **A 150 ms visuomotor lag.** The recorded ground truth is the cursor at time ``t``; the
  muscle is doing what the cursor asked 150 ms ago. This mislabels the continuous arm and
  nothing else, so it handicaps the very arm under test.
- **A chronic 8% undershoot**, so the subject's full effort never quite reaches the cued
  extreme.
- **A slow correlated wobble** (two incommensurate sines, 0.079 rms and 0.15 peak).
  Correlated, not white: a human drifts off the cursor and corrects, they do not jitter
  per sample.

The estimator is a five-nearest-neighbour average written out below in five lines, on
purpose. It has no hyperparameters worth tuning and one relevant property: its output is
always an average of training targets, so it can only emit a level the block actually
asked for. That makes it an instrument for reading what target values the data contains,
which is exactly the quantity in dispute — and it keeps this test free of the `examples`
extra, which CI does not install. RandomForest and ExtraTrees give the same verdict
(discrete/continuous MAE ratios 8.7 and 3.2 against 5-NN's 6.1).

A *linear* model is the exception, and it is the informative one. Least squares fitted to
three cued levels already draws a straight line through the intermediate ones, so it never
needed intermediate targets: with plain unregularised least squares the three-class arm
wins outright (0.105 against 0.121), and the headline assertion below would fail. Ridge
only agrees once the penalty is strong enough to spoil that straight line. So the claim is
about estimators that fit local or non-linear structure — which is every estimator this app
ships, and the reason a linear decoder is not one of them — and it is not a claim about
every possible fit. "The win is a property of the data, not the model" is too strong: it is
a property of the data *as read by a model that cannot extrapolate a line*.

Caveat worth keeping in view: `hop_s` must stay slow relative to the subject's lag. At
``hop_s=0.5`` with this 150 ms lag the continuous arm collapses (the label and the effort
are a third of a segment apart) and stops beating three classes. The shipped default of
2.0 s has a wide margin; that margin is not infinite. Labelling each window with the
cursor as it was one lag *earlier* removes the constraint almost entirely — it rescues
even the ``hop_s=0.5`` block — so if the trajectory is ever sped up, shift the label
rather than shortening the hop.
"""

from __future__ import annotations

import numpy as np
import pytest

from myogestic.recipes.features import mav, rms
from myogestic.sources import SyntheticSource
from myogestic.tracking import Pursuit

FS = 2048.0
N_CHANNELS = 8
CHUNK = 64  # SyntheticSource emits this many samples per `read()`
WINDOW = int(round(0.200 * FS))  # the app's training window
HOP = int(round(0.100 * FS))  # and its hop

LAG_S = 0.15
UNDERSHOOT = 0.92
WOBBLE = ((0.10, 0.37, 0.7), (0.05, 0.91, 2.1))  # (amplitude, Hz, phase)

#: Levels the transfer curve is measured at. The six interior ones are what the cued
#: block never contains, and are the whole experiment.
PROBE_LEVELS = (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0)
INTERMEDIATE = (-0.75, -0.5, -0.25, 0.25, 0.5, 0.75)


def _subject(t: float, target_at) -> float:
    """Signed effort the simulated subject actually produces at task time `t`."""
    v = UNDERSHOOT * target_at(max(t - LAG_S, 0.0))
    for amplitude, hz, phase in WOBBLE:
        v += amplitude * np.sin(2 * np.pi * hz * t + phase)
    return float(np.clip(v, -1.0, 1.0))


def _record(target_at, duration_s: float, seed: int, *, subject: bool = True) -> np.ndarray:
    """Drive the synthetic amplifier along `target_at`, returning ``(n_samples, n_ch)``.

    Parameters
    ----------
    target_at
        Callable mapping task time in seconds to a signed level in ``[-1, +1]``.
    duration_s
        Seconds of signal to generate.
    seed
        Seed for the source's noise, which comes from the legacy global RNG.
    subject
        Apply the lag / undershoot / wobble. ``False`` drives the knobs straight from
        `target_at`, which is how the held probe levels are made: they measure the fitted
        model's transfer curve, and wobbling them would only add variance to it.
    """
    source = SyntheticSource(n_channels=N_CHANNELS, fs=FS, noise=0.10, hum=0.0)
    source.connect()
    # `read()` sleeps only while the next chunk is still in the future, and advances one
    # chunk per call. Rewinding the pacing clock an hour leaves ~100k unpaced reads —
    # far more than this file pulls. Same trick as `tests/test_directional_decoder.py`.
    source._next_tick -= 3600.0  # type: ignore
    # `SyntheticSource` draws its noise from the legacy *global* RNG, so seeding is the
    # only way to make this file reproducible — and restoring is the only way to keep
    # that seed from following us out and quietly determinising the rest of the suite.
    entry_state = np.random.get_state()
    np.random.seed(seed)
    try:
        chunks = []
        for i in range(int(duration_s * FS / CHUNK)):
            # Mid-chunk, because `read()` samples the knobs once per chunk.
            t = (i + 0.5) * CHUNK / FS
            level = _subject(t, target_at) if subject else float(np.clip(target_at(t), -1.0, 1.0))
            source.activation, source.direction = abs(level), level
            chunks.append(source.read()[0])
    finally:
        np.random.set_state(entry_state)
    return np.concatenate(chunks)


def _features(data: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """RMS+MAV per window — the app's default feature set."""
    return np.array(
        [np.concatenate([rms(data[e - WINDOW : e].T), mav(data[e - WINDOW : e].T)]) for e in ends],
        dtype=np.float64,
    )


def _window_ends(n_samples: int) -> np.ndarray:
    """Sample index one past the last sample of each window."""
    return np.arange(WINDOW, n_samples + 1, HOP)


def _continuous_set(task: Pursuit, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Follow the pursuit cursor; label each window with the cursor at the window's end.

    Alignment and phase filter both match `iter_target_windows`: the target is the value
    at the window's **last** sample, because the model is causal and the window's end is
    the instant it answers for, and windows whose phase is ``"done"`` are dropped.
    """
    data = _record(task.value_at, task.total_duration, seed)
    ends = _window_ends(len(data))
    ends = ends[[task.phase_at(e / FS) != "done" for e in ends]]
    return _features(data, ends), np.array([task.value_at(e / FS) for e in ends])


def _discrete_set(
    total_s: float, seed: int, levels: tuple[float, ...] = (-1.0, 0.0, 1.0)
) -> tuple[np.ndarray, np.ndarray]:
    """Cued holds — the protocol the app ships — over the same total block time.

    The default three levels are that protocol. `levels` exists for the control in
    `test_the_mechanism_is_level_coverage_not_pursuit`, which needs the same generator
    with a longer ladder; the block is always split evenly, so more levels means a
    shorter hold each and the same total recording time.
    """
    features, targets = [], []
    for offset, level in enumerate(levels):
        data = _record(lambda t, v=level: v, total_s / len(levels), seed + offset)
        ends = _window_ends(len(data))
        features.append(_features(data, ends))
        targets.append(np.full(len(ends), level))
    return np.vstack(features), np.concatenate(targets)


def _probe_sets(seed: int) -> dict[float, np.ndarray]:
    """Held-out feature blocks, one per level in `PROBE_LEVELS`."""
    return {
        level: _features(
            block := _record(lambda t, v=level: v, 3.0, seed + offset, subject=False),
            _window_ends(len(block)),
        )
        for offset, level in enumerate(PROBE_LEVELS)
    }


class _NearestNeighbours:
    """Five-nearest-neighbour target average. Deterministic, no hyperparameters, no deps."""

    def __init__(self, k: int = 5) -> None:
        self.k = k

    def fit(self, x: np.ndarray, y: np.ndarray) -> _NearestNeighbours:
        """Memorise the training set."""
        self.x_, self.y_ = np.asarray(x, float), np.asarray(y, float)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Mean target of the `k` closest training windows."""
        distance = ((np.asarray(x, float)[:, None, :] - self.x_[None]) ** 2).sum(-1)
        nearest = np.argsort(distance, axis=1, kind="stable")[:, : self.k]
        return self.y_[nearest].mean(axis=1)


def _transfer_curve(x: np.ndarray, y: np.ndarray, probes: dict[float, np.ndarray]) -> np.ndarray:
    """Fit on ``(x, y)`` and return the mean output at each level in `PROBE_LEVELS`."""
    model = _NearestNeighbours().fit(x, y)
    return np.array([float(model.predict(probes[level]).mean()) for level in PROBE_LEVELS])


def _intermediate_mae(curve: np.ndarray) -> float:
    """Mean absolute error over only the levels the cued block never contained."""
    keep = [PROBE_LEVELS.index(level) for level in INTERMEDIATE]
    return float(np.abs(curve[keep] - np.array(INTERMEDIATE)).mean())


@pytest.fixture(scope="module")
def probes() -> dict[float, np.ndarray]:
    """One held block of features per probe level, shared by both arms."""
    return _probe_sets(seed=901)


@pytest.fixture(scope="module")
def continuous(probes) -> np.ndarray:
    """Transfer curve of a model trained on the followed cursor."""
    task = Pursuit()
    return _transfer_curve(*_continuous_set(task, seed=11), probes)


@pytest.fixture(scope="module")
def discrete(probes) -> np.ndarray:
    """Transfer curve of a model trained on cued Down / Rest / Up, same block length."""
    return _transfer_curve(*_discrete_set(Pursuit().total_duration, seed=201), probes)


def test_continuous_ground_truth_interpolates(continuous):
    """Every intermediate level gets its own output, in the right order and near the truth."""
    steps = np.diff(continuous)
    assert np.all(steps > 0.05), f"not strictly monotone, or a plateau: {continuous}"
    assert continuous.max() - continuous.min() > 1.5, f"compressed range: {continuous}"
    assert _intermediate_mae(continuous) < 0.15, continuous


def test_three_cued_classes_buy_three_paddle_positions(discrete):
    """The control: without intermediate targets the curve is a staircase, not a ramp.

    Asserted so a fixture that quietly stopped producing a *discrete* block — the
    comparison's whole point — fails here instead of flattering the other arm.
    """
    assert np.min(np.diff(discrete)) < 0.01, f"expected a plateau, got {discrete}"
    assert len(np.unique(np.round(discrete, 1))) <= 4, f"expected ~3 plateaus, got {discrete}"
    assert _intermediate_mae(discrete) > 0.25, discrete


def test_continuous_ground_truth_beats_three_classes(continuous, discrete):
    """The headline, same estimator and same block length on both sides."""
    assert _intermediate_mae(continuous) < _intermediate_mae(discrete) / 2.0, (
        f"continuous {_intermediate_mae(continuous):.3f} vs "
        f"discrete {_intermediate_mae(discrete):.3f}"
    )


def test_the_mechanism_is_level_coverage_not_pursuit(probes, continuous):
    """The control the headline needs, and it does not go the way the framing suggests.

    Everything above is consistent with two different causes: that the subject *tracked*
    something, or merely that the training set contained more than three distinct levels.
    Only one experiment separates them — cue a longer ladder and change nothing else.

    Eleven cued holds over the identical block length interpolate about as well as the
    pursuit arm and usually better, on the same six levels neither arm was trained on
    (the ladder shares only -1, 0 and +1 with the probe grid, so there is no leak). The
    ladder is monotone in level count: 3 holds 0.33, 5 holds 0.17, 7 holds 0.10, 11 holds
    0.04. That is the mechanism, and it is worth knowing, because the cheapest possible
    protocol change buys most of what the pursuit apparatus buys.

    What survives is the narrower claim the file is named for: three levels are too few,
    and the fix is to sample the level axis densely. `Pursuit` is one way to do that and
    is preferred for reasons this file does not measure — a staircase holds still, so it
    confounds every level with a zero rate of change and says nothing about transitions,
    and eleven cued holds are eleven things for an operator to run.
    """
    eleven = tuple(np.linspace(-1.0, 1.0, 11))
    ladder = _transfer_curve(*_discrete_set(Pursuit().total_duration, 201, eleven), probes)

    assert _intermediate_mae(ladder) < 0.15, (
        f"a long cued staircase must interpolate too, else the mechanism claimed here is "
        f"wrong: {ladder}"
    )
    assert _intermediate_mae(ladder) < 2.0 * _intermediate_mae(continuous), (
        f"staircase {_intermediate_mae(ladder):.3f} vs pursuit "
        f"{_intermediate_mae(continuous):.3f} — if pursuit now dominates a long staircase "
        f"outright, the docstring's account of the mechanism needs revisiting"
    )
