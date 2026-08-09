"""Tests for `myogestic.recipes.estimators.directional_decoder`.

Data comes from `SyntheticSource`, whose `activation` / `direction` knobs model
exactly the structure the decoder assumes: `activation` scales every sine,
`direction` shifts that amplitude between the first half of the channels (-1)
and the second half (+1). Ground truth is therefore exact, and no subject
recording has to ship with the repo.
"""

from __future__ import annotations

import doctest

import numpy as np
import pytest

from myogestic.recipes.estimators import _STRONG_TARGET, directional_decoder
from myogestic.recipes.features import mav, rms, var, wl
from myogestic.sources import SyntheticSource

CHUNKS_PER_WINDOW = 4  # 4 x 64 samples = 125 ms at 2048 Hz


@pytest.fixture
def source():
    """A connected synthetic amplifier whose `read()` never blocks, on a fixed seed.

    `SyntheticSource` draws its noise from the legacy *global* RNG, so seeding here is
    the only way to make these tests reproducible — and restoring on the way out is the
    only way to keep the seed from following us into the rest of the suite. Same trick,
    and the same reason, as `tests/test_continuous_gt_beats_three_classes.py`.

    Not cosmetic. Unseeded, `test_a_global_gain_never_lowers_the_command[rms+mav+wl]`
    failed about 2 runs in 25: twelve training windows per class is occasionally not
    enough to get the *sign* right on a 40%-effort probe, and with the direction
    inverted a rising gain drives the command down, which is exactly what that test
    forbids. A statistical assertion on a noisy generator needs a fixed draw or a
    sample size nobody wants to pay for.
    """
    entry_state = np.random.get_state()
    np.random.seed(0)
    src = SyntheticSource(n_channels=8, noise=0.05, hum=0.0)
    src.connect()
    # `read()` sleeps only while the next chunk is still in the future, and it
    # advances one chunk per call. Rewinding the pacing clock an hour leaves
    # ~100k unpaced reads — far more than any test here pulls.
    src._next_tick -= 3600.0  # type: ignore
    try:
        yield src
    finally:
        np.random.set_state(entry_state)


def _windows(source: SyntheticSource, n: int, *, activation: float, direction: float):
    """Hold a contraction and return `n` raw EMG windows, each (n_channels, n_samples)."""
    source.activation = activation
    source.direction = direction
    out = []
    for _ in range(n):
        chunks = [source.read()[0] for _ in range(CHUNKS_PER_WINDOW)]
        out.append(np.concatenate(chunks).T)
    return out


def _features(windows, gain: float = 1.0, fns=(rms, mav)) -> np.ndarray:
    """Stacked features per window. Default RMS+MAV — the app default, all non-negative."""
    return np.array([np.concatenate([f(w * gain) for f in fns]) for w in windows])


def _graded(source: SyntheticSource, levels, n: int = 3, fns=(rms, mav)):
    """A block that asks for a *range* of signed levels, labelled with the level asked.

    ``activation = abs(v)`` and ``direction = sign(v)``: the spatial pattern is the same
    at every level of one sign, so the only thing that varies along the block is effort.
    That is deliberate — these tests are about the effort scale, and a shape that also
    graded with the level would let a direction error stand in for a span error.
    """
    features, targets = [], []
    for v in levels:
        windows = _windows(source, n, activation=abs(v), direction=float(np.sign(v)))
        features.append(_features(windows, fns=fns))
        targets.append(np.full(n, float(v)))
    return np.vstack(features), np.concatenate(targets)


def _fitted(source: SyntheticSource, n: int = 12, fns=(rms, mav)):
    """Fit on held Down / Rest / Up blocks, and hand back a fresh test block too."""
    down = _windows(source, n, activation=1.0, direction=-1.0)
    up = _windows(source, n, activation=1.0, direction=+1.0)
    rest = _windows(source, n, activation=0.0, direction=0.0)
    X = np.vstack([_features(down, fns=fns), _features(up, fns=fns), _features(rest, fns=fns)])
    y = np.concatenate([np.full(n, -1.0), np.full(n, 1.0), np.zeros(n)])
    return directional_decoder().fit(X, y)


def test_recovers_the_sign_of_direction(source):
    model = _fitted(source)
    held_down = _features(_windows(source, 8, activation=1.0, direction=-1.0))
    held_up = _features(_windows(source, 8, activation=1.0, direction=+1.0))
    assert np.all(model.predict(held_down) < -0.5)
    assert np.all(model.predict(held_up) > 0.5)


def test_rest_reads_as_zero(source):
    """No dead zone anywhere in the decoder — `activation` clips to 0 on its own."""
    model = _fitted(source)
    quiet = _features(_windows(source, 8, activation=0.0, direction=0.0))
    assert np.all(np.abs(model.predict(quiet)) < 0.02), model.predict(quiet)


def test_output_grows_with_activation(source):
    levels = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    model = _fitted(source)
    commands = np.array(
        [
            np.median(model.predict(_features(_windows(source, 6, activation=a, direction=1.0))))
            for a in levels
        ]
    )
    assert commands[0] < 0.02 and commands[-1] > 0.9, commands
    # Each step visibly bigger than the last, not merely non-decreasing.
    assert np.all(np.diff(commands) > 0.1), commands
    # And no pedestal under the ramp: the source's RMS grows sub-linearly with
    # `activation` (the noise floor adds in quadrature), so the command has to sit at
    # or below the effort actually commanded. Skipping the rest baseline lifts it off
    # the floor and pushes it above the line.
    assert np.all(commands <= levels + 0.05), commands


@pytest.mark.parametrize(
    "fns", [(rms, mav), (rms, mav, wl), (var,)], ids=["rms+mav", "rms+mav+wl", "var"]
)
def test_a_global_gain_never_lowers_the_command(source, fns):
    """The property the CatBoost regressor fails: contract harder, do not fall.

    A gain on every channel is what a tighter cuff or a hotter amplifier does. It
    cancels exactly out of the amplitude-normalised shape, so it leaves `direction`
    untouched and can only raise `activation` — for every feature set the recipe's
    input contract allows, which is every set whose columns all answer that gain the
    same way. RMS, MAV and WL are degree 1 and mix freely; VAR is degree 2 and is fine
    alone. Across degrees it is not — `test_mixing_feature_degrees_costs_the_invariance`.
    """
    model = _fitted(source, fns=fns)
    # Full effort, so `activation` is already clipped to 1 at every gain and the
    # command *is* `direction`. A partial direction keeps that component off its own
    # clip, where a gain leaking into it would otherwise hide.
    saturated = _windows(source, 8, activation=1.0, direction=0.35)
    held = np.array(
        [model.predict(_features(saturated, gain=g, fns=fns)) for g in (1.3, 1.6, 2.0, 4.0)]
    )
    # 1e-5, not 0: the features are float32, so `rms(w * g)` and `g * rms(w)` differ
    # in the last bit. A gain leaking into `direction` shows up two decades above that.
    assert np.allclose(held, held[0], atol=1e-5), held

    # Below saturation, a gain may only raise the command — never lower or flip it.
    submaximal = _windows(source, 8, activation=0.4, direction=+1.0)
    ramp = np.array(
        [model.predict(_features(submaximal, gain=g, fns=fns)) for g in (0.6, 1.0, 1.5, 2.5, 4.0)]
    )
    assert np.all(np.diff(ramp, axis=0) >= -1e-5), ramp
    # Not every row: a 40%-effort window at low gain can legitimately fall under the
    # fitted rest level and read a hard 0, which is `activation`'s floor, not a flip.
    # The top of the ramp anchors it, so "monotone" cannot be satisfied by all-zeros.
    assert np.all(ramp[-1] > 0.0), ramp


def test_mixing_feature_degrees_costs_the_invariance():
    """Why the input contract names *one* degree, and why the docstring is conditional.

    RMS and MAV scale by `g`, VAR by `g**2`. Mix them and the row sum stops factoring
    out of the row, so a gain moves `direction` itself — the exact failure the recipe
    exists to avoid. Written as bare arithmetic rather than off the synthetic source:
    `a` stands for a channel's amplitude, so `a` is any degree-1 feature of it and
    `a**2` is VAR, and a gain `g` on the electrodes is `a -> g * a`. Pinned so nobody
    restores the unconditional promise.
    """

    def row(amplitudes, gain=1.0, degrees=(1, 2)):
        a = np.asarray(amplitudes, dtype=np.float64) * gain
        return np.concatenate([a**d for d in degrees])

    down = [[4.0, 4.0, 1.0, 1.0], [3.0, 5.0, 1.0, 1.2], [4.2, 3.6, 0.9, 1.1]]
    up = [[1.0, 1.0, 4.0, 4.0], [1.2, 1.0, 5.0, 3.0], [0.9, 1.1, 3.6, 4.2]]
    rest = [[0.5, 0.5, 0.5, 0.5], [0.6, 0.4, 0.55, 0.45], [0.45, 0.55, 0.5, 0.5]]
    y = np.concatenate([np.full(3, -1.0), np.full(3, 1.0), np.zeros(3)])
    # Between rest and Up in shape, so `direction` is off its clip where a gain leaking
    # into it can be seen, and loud enough that `activation` is saturated at every gain.
    probe = [1.7, 2.0, 5.0, 4.3]

    for degrees, moved in ((1,), False), ((1, 2), True):
        X = np.vstack([row(a, degrees=degrees) for a in down + up + rest])
        model = directional_decoder().fit(X, y)
        held = np.array(
            [
                float(model.predict(row(probe, gain=g, degrees=degrees)[None])[0])
                for g in (1.0, 4.0)
            ]
        )
        assert bool(abs(held[1] - held[0]) > 0.1) is moved, (degrees, held)


def test_a_window_quieter_than_rest_reads_exactly_zero(source):
    """`activation` has a floor, and it is what makes rest a hard zero.

    Without it a window below the fitted rest level gets a *negative* activation, which
    multiplies the direction into a command pointing the wrong way — a paddle that
    drifts the opposite way when the subject relaxes past their own baseline. The
    existing rest test cannot see this: it asserts on `np.abs`.
    """
    model = _fitted(source)
    quiet = _features(_windows(source, 8, activation=0.0, direction=+1.0)) * 0.25
    assert np.all(model.predict(quiet) == 0.0), model.predict(quiet)


def test_the_command_never_leaves_the_unit_range(source):
    """`predict` promises [-1, +1]; an extrapolating window must not talk it out of it."""
    model = _fitted(source)
    # Ten times the training separation on the shape axis, well past anything fitted.
    far = _features(_windows(source, 6, activation=1.0, direction=+1.0))
    far = far * np.linspace(0.1, 10.0, far.shape[1])
    commands = model.predict(np.vstack([far, far[:, ::-1]]))
    assert np.all(np.abs(commands) <= 1.0), commands


def test_a_shared_within_class_mode_stays_out_of_the_direction():
    """The covariance solve is the point — a per-feature weighting cannot do this.

    Four features carrying one big shared fluctuation `v = [+1, +1, -1, -1]` and one
    small class difference `d = [+1, 0, -1, 0]`. `v` and `d` are not orthogonal, so a
    diagonal (per-feature variance) weighting leaks the shared mode straight into the
    projection and the command swings with noise the subject never produced. The Fisher
    solve finds the axis that nulls `v` and still sees `d`.
    """
    rng = np.random.default_rng(0)
    base = np.full(4, 0.25)
    v = np.array([1.0, 1.0, -1.0, -1.0])
    d = np.array([1.0, 0.0, -1.0, 0.0])

    def rows(label: float, n: int, total: float) -> np.ndarray:
        shared = np.clip(rng.normal(0.0, 0.05, size=(n, 1)), -0.15, 0.15)
        return total * (base + shared * v + label * 0.06 * d)

    X = np.vstack([rows(-1.0, 30, 1.0), rows(+1.0, 30, 1.0), rows(0.0, 30, 0.3)])
    y = np.concatenate([np.full(30, -1.0), np.full(30, +1.0), np.zeros(30)])
    model = directional_decoder().fit(X, y)

    up = base + 0.06 * d
    perturbed = np.array([up + k * 0.05 * v for k in (-3.0, -1.0, 0.0, 1.0, 3.0)])
    commands = model.predict(perturbed)
    assert np.all(commands > 0.5), commands
    assert np.ptp(commands) < 0.4, commands


def test_an_all_zero_window_reads_zero_rather_than_nan(source):
    """A disconnected amplifier delivers zeros, and `_EPS` is the floor that survives it.

    Dividing by the row sum without it is 0/0: the command comes back NaN, which the
    consumers read as a number — a clamp leaves it NaN and a nearest-pose lookup on it
    picks the first class.
    """
    model = _fitted(source)
    dead = np.zeros((1, model.w_.size))
    assert model.predict(dead)[0] == 0.0, model.predict(dead)


def test_fit_names_a_rest_that_is_louder_than_the_contractions():
    """The span guard, with the message that says which way round the blocks go."""
    loud_rest = np.full((4, 3), 3.0)
    # Three, not two: the span rule needs `_MIN_STRONG_WINDOWS` of them before it will
    # estimate anything, and that guard fires first. Nothing else here cares how many.
    quiet_work = np.array([[1.0, 0.5, 0.2], [0.2, 0.5, 1.0], [0.9, 0.4, 0.3]])
    X = np.vstack([quiet_work, loud_rest])
    y = np.array([-1.0, 1.0, -1.0, 0.0, 0.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="not louder than rest"):
        directional_decoder().fit(X, y)


def test_fit_names_two_directions_with_the_same_shape():
    """The scale guard: same spatial pattern both ways, so there is no axis to find."""
    shape = np.array([1.0, 2.0, 3.0])
    X = np.vstack([shape * 2.0, shape * 2.2, shape * 2.1, shape * 2.3, shape * 0.5, shape * 0.4])
    y = np.array([-1.0, -1.0, 1.0, 1.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="no separable spatial pattern"):
        directional_decoder().fit(X, y)


def test_fit_refuses_non_finite_features(source):
    """A NaN passes every `<= 0` guard and then returns NaN for *every* window."""
    X = _features(_windows(source, 6, activation=1.0, direction=-1.0))
    X = np.vstack([X, _features(_windows(source, 6, activation=1.0, direction=+1.0))])
    X = np.vstack([X, _features(_windows(source, 6, activation=0.0, direction=0.0))])
    y = np.concatenate([np.full(6, -1.0), np.full(6, 1.0), np.zeros(6)])
    X = X.astype(np.float64)
    X[3, 2] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        directional_decoder().fit(X, y)


@pytest.mark.parametrize("bad", [-0.1, 1.5, float("nan")])
def test_shrinkage_outside_zero_to_one_is_named(bad):
    """Out of range blamed the operator's labels before; now it blames the argument."""
    with pytest.raises(ValueError, match="shrinkage"):
        directional_decoder(shrinkage=bad)


def test_fit_names_the_missing_sign(source):
    down = _features(_windows(source, 6, activation=1.0, direction=-1.0))
    rest = _features(_windows(source, 6, activation=0.0, direction=0.0))
    X = np.vstack([down, rest])
    y = np.concatenate([np.full(6, -1.0), np.zeros(6)])
    with pytest.raises(ValueError, match=r"positive windows \(y > 0\)"):
        directional_decoder().fit(X, y)


def test_fit_names_the_missing_rest_block(source):
    down = _features(_windows(source, 6, activation=1.0, direction=-1.0))
    up = _features(_windows(source, 6, activation=1.0, direction=+1.0))
    X = np.vstack([down, up])
    y = np.concatenate([np.full(6, -1.0), np.full(6, 1.0)])
    with pytest.raises(ValueError, match=r"rest windows \(y == 0\)"):
        directional_decoder().fit(X, y)


def test_fit_refuses_a_target_that_is_not_in_the_signed_control_range(source):
    """A percent-of-MVC column passes every other guard in `fit` and ruins the span.

    `Trapezoid` records through the same `TargetSource`, onto a stream with the same name
    and the same channel names, into the same folder, in ``0..100``. `StreamInfo` carries
    no unit, so the recording itself cannot tell the two apart — and every remaining guard
    here is a ``<= 0`` test, none of which a wrong *scale* trips. Concatenated with a
    cursor block it divided the span by 90 and turned the transfer curve into a hard
    three-step staircase, silently.
    """
    down = _features(_windows(source, 6, activation=1.0, direction=-1.0))
    up = _features(_windows(source, 6, activation=1.0, direction=+1.0))
    rest = _features(_windows(source, 6, activation=0.0, direction=0.0))
    X = np.vstack([down, up, rest])
    signed = np.concatenate([np.full(6, -1.0), np.full(6, 1.0), np.zeros(6)])
    directional_decoder().fit(X, signed)  # the contract, and it still fits

    percent = signed * 30.0  # what a 30 % MVC trapezoid records
    with pytest.raises(ValueError, match=r"\[-1, \+1\] and reaches 30"):
        directional_decoder().fit(X, percent)


def test_a_cued_block_fits_exactly_the_median_of_totals(source):
    """The generalisation is free: on -1 / 0 / +1 the new span rule *is* the old one.

    ``span_`` is ``median((total - rest_) / abs(y))`` over the windows that reach
    `_STRONG_TARGET`. A cued block puts ``abs(y) == 1`` on every non-rest window, so the
    selection is the same set as ``y != 0``, the division is a no-op, and a median is
    translation-equivariant — the whole thing collapses to ``median(total) - rest_``.
    Bit-exact with an odd window count, where the median is one element rather than the
    mean of two, so nothing here is hiding behind a tolerance.
    """
    down = _features(_windows(source, 13, activation=1.0, direction=-1.0))
    up = _features(_windows(source, 12, activation=1.0, direction=+1.0))
    rest = _features(_windows(source, 11, activation=0.0, direction=0.0))
    X = np.vstack([down, up, rest])
    y = np.concatenate([np.full(13, -1.0), np.full(12, 1.0), np.zeros(11)])
    assert (np.abs(y) >= _STRONG_TARGET).sum() % 2 == 1, "the exactness claim needs an odd count"

    model = directional_decoder().fit(X, y)
    total = X.astype(np.float64).sum(axis=1)  # `fit` widens first; float32 sums differ
    # The same windows, and then the same number off them.
    assert np.array_equal(np.abs(y) >= _STRONG_TARGET, y != 0)
    assert model.rest_ == float(np.median(total[y == 0]))
    assert model.span_ == float(np.median(total[y != 0])) - model.rest_


def test_a_graded_block_fits_a_graded_command(source):
    """The bug this rule exists for: a block of part-effort targets is not all-or-nothing.

    ``median(total[y != 0]) - rest_`` reads every non-rest window as a full contraction.
    Ask a subject to track a cursor and most windows are *not* full, so that rule fits a
    span far short of the real one, `activation` saturates, and the command pegs partway
    up the range — the paddle stops answering. Asserted both ways round: the per-window
    rule recovers the full-deflection span, the old expression does not, and the
    resulting transfer curve is graded and monotone across the whole range.
    """
    levels = np.round(np.linspace(-1.0, 1.0, 21), 3)
    X, y = _graded(source, levels, n=3)
    model = directional_decoder().fit(X, y)

    total = X.astype(np.float64).sum(axis=1)
    truth = float(np.median(total[np.abs(y) == 1.0])) - model.rest_
    assert model.span_ == pytest.approx(truth, rel=0.1), (model.span_, truth)
    old_rule = float(np.median(total[y != 0])) - model.rest_
    assert old_rule < 0.7 * truth, (old_rule, truth)

    probes = np.array([-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0])
    curve = np.array(
        [
            float(
                np.median(
                    model.predict(
                        _features(_windows(source, 4, activation=abs(v), direction=np.sign(v)))
                    )
                )
            )
            for v in probes
        ]
    )
    assert np.all(np.diff(curve) > 0.1), curve  # graded, not a three-step staircase
    assert np.abs(curve - probes).mean() < 0.12, curve
    # And the extremes still reach the rails, so "graded" was not bought by compression.
    assert curve[0] < -0.9 and curve[-1] > 0.9, curve


def test_fit_refuses_a_span_read_off_a_handful_of_weak_targets(source):
    """Dividing by `abs(y)` divides the noise too, so weak targets do not get a vote.

    Two windows is the case the floor exists for: a "median" of two is their mean, so
    one bad window moves it by half its own error, and the span sets the whole output
    range. Fitting anyway and hoping is what the error message replaces.
    """
    weak, _ = _graded(source, (-0.4, -0.2, 0.2, 0.4), n=4)
    rest = _features(_windows(source, 6, activation=0.0, direction=0.0))
    y_weak = np.concatenate([np.repeat([-0.4, -0.2, 0.2, 0.4], 4), np.zeros(6)])
    with pytest.raises(ValueError, match=r"at least 3 windows.*abs\(y\) = 0.4"):
        directional_decoder().fit(np.vstack([weak, rest]), y_weak)

    # Plenty of windows, only two of them strong — the count, not the block length.
    strong = _features(_windows(source, 1, activation=1.0, direction=-1.0))
    strong = np.vstack([strong, _features(_windows(source, 1, activation=1.0, direction=+1.0))])
    X = np.vstack([weak, strong, rest])
    y = np.concatenate([np.repeat([-0.4, -0.2, 0.2, 0.4], 4), [-1.0, 1.0], np.zeros(6)])
    with pytest.raises(ValueError, match=r"this block has 2 "):
        directional_decoder().fit(X, y)


def test_a_target_of_exactly_half_deflection_counts(source):
    """`_STRONG_TARGET` is a floor, not a strict bound, and the span is *per unit of y*.

    A block cued at nothing but ±0.5 and rest — a cautious operator keeping a patient
    well inside their range. Every strong window sits exactly on the boundary, so `>`
    instead of `>=` refuses to train at all: one character, and the symptom is a hard
    refusal on a protocol somebody will plausibly run.

    It also pins what `span_` *means*. These windows asked for half a contraction and
    the decoder must say so — a rule that read the loudest thing in the block as full
    effort would report 1.0 here, which is the paddle claiming a deflection the subject
    never made.
    """
    X, y = _graded(source, (-0.5, 0.0, 0.5), n=6)
    assert np.abs(y).max() == _STRONG_TARGET, "the boundary is the whole point"

    model = directional_decoder().fit(X, y)
    half = _features(_windows(source, 6, activation=0.5, direction=+1.0))
    assert 0.35 < np.median(model.predict(half)) < 0.65, model.predict(half)


def test_docstring_example_runs():
    """The Examples block in the recipe must actually produce what it shows."""
    finder = doctest.DocTestFinder(recurse=False)
    tests = finder.find(directional_decoder, globs={})
    runner = doctest.DocTestRunner(optionflags=doctest.NORMALIZE_WHITESPACE)
    for t in tests:
        runner.run(t)
    assert runner.summarize(verbose=False).failed == 0
