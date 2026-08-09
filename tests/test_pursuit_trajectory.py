"""The signed pursuit target — the cursor a subject follows to label effort continuously.

The trapezoid block this replaces only ever asks for three levels, so a model fitted to
it has no evidence about anything in between. These tests hold `Pursuit` to the
properties that make its recordings usable as *proportional* training data: it really is
signed, it really does rest at zero, it covers the range instead of visiting three
points, and it is reproducible so two sessions can be pooled.
"""

from __future__ import annotations

import doctest

import numpy as np
import pytest

from myogestic.tracking import Pursuit

DT = 0.001
#: Bins over [-1, +1] for the coverage tests. Twenty means uniform coverage is 5% each.
BINS = 20


def _wander_samples(task: Pursuit, dt: float = DT) -> np.ndarray:
    """Values over one repetition's moving part, excluding rest and recover.

    Coverage is a property of the wander. Including the baseline segments would pile
    a fifth of the block into whichever bin contains zero and say nothing about the
    shape being tested.
    """
    span = task.hops * task.hop_s
    ts = task.rest_s + np.arange(0.0, span, dt)
    return np.array([task.value_at(float(t)) for t in ts])


def _waypoints(task: Pursuit) -> list[float]:
    """The level at the start of each hop, plus the level the last hop ends on."""
    return [task.value_at(task.rest_s + i * task.hop_s) for i in range(task.hops + 1)]


def test_the_target_stays_inside_the_signed_unit_range():
    """The value drives a cursor on a [-1, +1] axis and is recorded as a training
    target. Out of range means the subject is asked for a deflection the display cannot
    show and the decoder is fitted to a target it can never emit."""
    task = Pursuit()
    values = [task.value_at(i * DT) for i in range(int(task.total_duration / DT))]
    assert min(values) >= -1.0
    assert max(values) <= 1.0


def test_every_repetition_reaches_full_deflection_in_both_directions():
    """Down has to be a real -1, not a near miss. If the extremes are only approached,
    the recording never contains a full contraction and the decoder's own extremes are
    extrapolation — the exact failure this trajectory exists to remove."""
    task = Pursuit()
    levels = _waypoints(task)
    assert min(levels) == -1.0
    assert max(levels) == 1.0


def test_rest_and_recover_are_exactly_zero_and_stay_there():
    """A decoder estimates its baseline from the rest windows. 'Nearly zero' is a
    baseline offset that shifts every prediction, and a rest window that is quietly
    drifting is not a rest window."""
    task = Pursuit(rest_s=3.0, hop_s=0.5, hops=8, recover_s=3.0)
    rest = [task.value_at(i * DT) for i in range(int(3.0 / DT))]
    recover_start = task.rest_s + task.hops * task.hop_s
    recover = [task.value_at(recover_start + i * DT) for i in range(int(3.0 / DT))]

    assert set(rest) == {0.0}
    assert set(recover) == {0.0}
    assert task.phase_at(1.5) == "rest"
    assert task.phase_at(recover_start + 1.5) == "recover"


def test_the_trajectory_covers_the_range_instead_of_visiting_three_levels():
    """The whole point. Split [-1, +1] into twentieths and ask how long the target
    spends in each: a shape that only visits -1, 0 and +1 piles up around those three
    (measured: 19% of the block in one twentieth) and reproduces the bug. Uniform would
    be 5% per bin; the assertions below leave room either side of what `Pursuit`
    actually does, which is 2.0% in the thinnest bin and 8.2% in the fattest."""
    task = Pursuit()
    counts, _ = np.histogram(_wander_samples(task), bins=BINS, range=(-1.0, 1.0))
    share = 100.0 * counts / counts.sum()

    assert share.min() > 1.5, f"a level the subject barely visits: {share.round(2)}"
    assert share.max() < 10.0, f"the target clumps at a few levels: {share.round(2)}"


def test_coverage_is_quoted_against_the_wander_not_against_the_block():
    """The class docstring cites both shares, and they are not the same number.

    The thinnest twentieth is 2.0% of the *wander* but 1.7% of the block, the gap being
    rest and recover — ten of the default fifty-eight seconds parked at exactly zero.
    Quoting the wander figure as if it were the block's overstates how much of a
    recording sits at the sparsest level, which is the figure that decides whether a
    block is long enough to train on.
    """
    task = Pursuit()
    wander, _ = np.histogram(_wander_samples(task), bins=BINS, range=(-1.0, 1.0))
    whole = np.array([task.value_at(i * DT) for i in range(int(task.total_duration / DT))])
    block, _ = np.histogram(whole, bins=BINS, range=(-1.0, 1.0))

    assert 100.0 * wander.min() / wander.sum() == pytest.approx(2.0, abs=0.15)
    assert 100.0 * block.min() / len(whole) == pytest.approx(1.7, abs=0.15)


def test_the_extremes_are_still_only_ever_reached_slowly():
    """Rate is decoupled from level, but not decorrelated — the docstring says so.

    ±1 are waypoints and smootherstep eases to a standstill at every waypoint, so full
    deflection is structurally slow. Claiming otherwise would invite speeding the block
    up on the belief that the confound is gone; it is reduced, from a sinusoid's -0.92
    to -0.21, and the residue lives exactly where a decoder reads its own extremes.
    """
    task = Pursuit()
    dt = 0.0005
    span = task.hops * task.hop_s
    ts = task.rest_s + np.arange(0.0, span, dt)
    values = np.array([task.value_at(float(t)) for t in ts])
    rate = np.abs(np.gradient(values, dt))

    fast = rate[np.abs(values) < 0.5].mean()
    slow = rate[np.abs(values) > 0.9].mean()
    assert slow < fast / 2.0, f"extremes not slower: {slow:.3f} vs {fast:.3f}"

    correlation = float(np.corrcoef(np.abs(values), rate)[0, 1])
    sine = np.sin(2 * np.pi * 0.1 * ts)
    sine_correlation = float(np.corrcoef(np.abs(sine), np.abs(np.gradient(sine, dt)))[0, 1])
    assert correlation == pytest.approx(-0.21, abs=0.05)
    assert sine_correlation == pytest.approx(-0.92, abs=0.05)
    assert correlation > sine_correlation, "must still beat a single sinusoid"


def test_the_rate_of_change_varies_by_more_than_a_factor_of_three():
    """If every hop moved at one speed, rate would be a constant and the decoder could
    not tell a slow crossing of a level from a fast one — worse, under a single sinusoid
    rate is a *function* of level and the model can learn that confound instead."""
    task = Pursuit()
    steps = [abs(b - a) for a, b in zip(_waypoints(task), _waypoints(task)[1:], strict=False)]
    assert min(steps) > 0.0
    assert max(steps) / min(steps) > 3.0


def test_the_trajectory_never_jumps():
    """A step in the target cannot be tracked, and lands in the training set as effort
    the subject never produced. The bound is the steepest slope the shape allows:
    smootherstep peaks at 1.875x the average rate of its hop."""
    task = Pursuit()
    levels = _waypoints(task)
    tallest = max(abs(b - a) for a, b in zip(levels, levels[1:], strict=False))
    fastest = 1.875 * tallest / task.hop_s

    values = [task.value_at(i * DT) for i in range(int(task.total_duration / DT))]
    worst = max(abs(b - a) for a, b in zip(values, values[1:], strict=False))
    assert worst <= fastest * DT + 1e-12


def test_each_hop_moves_in_one_direction_only():
    """A wobble inside a hop asks for a correction the subject cannot make in time, and
    it would make the phase label a lie for part of the segment."""
    task = Pursuit(rest_s=0.0, hop_s=1.0, hops=12, recover_s=0.0)
    for i in range(task.hops):
        start = i * task.hop_s
        inside = [task.value_at(start + k * DT) for k in range(int(task.hop_s / DT) + 1)]
        rising = task.phase_at(start + task.hop_s / 2) == "ramp_up"
        pairs = list(zip(inside, inside[1:], strict=False))
        if rising:
            assert all(b >= a for a, b in pairs), f"hop {i} labelled up but falls"
        else:
            assert all(b <= a for a, b in pairs), f"hop {i} labelled down but rises"


def test_the_phase_label_matches_the_direction_the_target_is_moving():
    """The label is what an analysis script selects on. If it disagrees with the number,
    a script asking for the rising windows gets the falling ones."""
    task = Pursuit(rest_s=1.0, hop_s=1.0, hops=10, recover_s=1.0)
    for i in range(task.hops):
        here = task.value_at(task.rest_s + i * task.hop_s)
        later = task.value_at(task.rest_s + i * task.hop_s + 0.5)
        phase = task.phase_at(task.rest_s + i * task.hop_s)
        assert phase == ("ramp_up" if later > here else "ramp_down")


def test_a_hop_reaches_the_midpoint_of_its_ends_at_its_own_midpoint():
    """An exact value, not an approximation: smootherstep is 0.5 at 0.5. If the easing
    is swapped for something asymmetric the target still looks smooth on screen but the
    time spent at each level changes, and with it the coverage the fit depends on."""
    task = Pursuit(rest_s=0.0, hop_s=1.0, hops=12, recover_s=0.0)
    for i in range(task.hops):
        a = task.value_at(i * task.hop_s)
        b = task.value_at((i + 1) * task.hop_s) if i + 1 < task.hops else 0.0
        assert task.value_at(i * task.hop_s + 0.5) == pytest.approx((a + b) / 2.0, abs=1e-12)


def test_the_same_parameters_give_a_bit_for_bit_identical_trajectory():
    """No RNG anywhere. Two recordings made a week apart must be poolable, and a
    regression in the shape must show up as a failing assertion rather than as noise."""
    one = Pursuit(rest_s=1.0, hop_s=0.7, hops=17, recover_s=2.0)
    two = Pursuit(rest_s=1.0, hop_s=0.7, hops=17, recover_s=2.0)
    ts = [i * 0.013 for i in range(1200)]
    assert [one.value_at(t) for t in ts] == [two.value_at(t) for t in ts]
    assert [one.phase_at(t) for t in ts] == [two.phase_at(t) for t in ts]
    # And stable within one object, so nothing is being consumed as it is read.
    assert [one.value_at(t) for t in ts] == [one.value_at(t) for t in ts]


def test_every_repetition_traces_the_same_path():
    """Reps are the unit the operator adds when they want more data. If they differed,
    'three reps' would silently be three different tasks and rep-wise comparison of the
    subject's tracking error would be meaningless."""
    one = Pursuit(hops=6, hop_s=0.5)
    three = Pursuit(hops=6, hop_s=0.5, reps=3)
    assert three.total_duration == pytest.approx(one.duration * 3)
    for rep in range(3):
        for k in range(200):
            t = k * one.duration / 200.0
            offset = rep * one.duration + t
            assert three.value_at(offset) == pytest.approx(one.value_at(t))
            assert three.phase_at(offset) == one.phase_at(t)


def test_the_duration_is_rest_plus_the_hops_plus_recover():
    task = Pursuit(rest_s=1.5, hop_s=0.25, hops=8, recover_s=2.5)
    assert task.duration == pytest.approx(1.5 + 2.0 + 2.5)
    assert task.total_duration == pytest.approx(task.duration)
    assert Pursuit(reps=4).total_duration == pytest.approx(Pursuit().duration * 4)


def test_before_the_block_reads_as_rest_and_after_it_reads_as_done():
    """The widget asks for a value before the operator presses start and after the block
    has run out. Neither may throw, and neither may leave the cursor off centre."""
    task = Pursuit(hops=4, hop_s=0.5, reps=2)
    assert task.phase_at(-1.0) == "rest"
    assert task.value_at(-1.0) == 0.0
    assert task.phase_at(task.total_duration) == "done"
    assert task.value_at(task.total_duration) == 0.0
    assert task.value_at(task.total_duration + 100.0) == 0.0


def test_a_zero_length_rest_starts_the_wander_immediately():
    """Zero-length segments are legal on `Trapezoid` and must stay legal here, or the
    only way to record a back-to-back block is a 1 ms fudge factor."""
    task = Pursuit(rest_s=0.0, hop_s=1.0, hops=4, recover_s=0.0)
    assert task.duration == pytest.approx(4.0)
    assert task.phase_at(0.0) in {"ramp_up", "ramp_down"}
    assert "rest" not in {task.phase_at(i * DT) for i in range(int(4.0 / DT))}
    assert "recover" not in {task.phase_at(i * DT) for i in range(int(4.0 / DT))}


def test_a_zero_length_hop_skips_the_wander_without_dividing_by_zero():
    """`hop_s=0` collapses the moving part. The arithmetic divides by `hop_s`, so this
    is the case that raises ZeroDivisionError if the segment is not skipped outright."""
    task = Pursuit(rest_s=1.0, hop_s=0.0, hops=8, recover_s=1.0)
    assert task.duration == pytest.approx(2.0)
    assert task.phase_at(0.5) == "rest"
    assert task.phase_at(1.0) == "recover"
    assert task.value_at(1.0) == 0.0


def test_an_empty_block_is_done_rather_than_a_crash():
    """Every segment zero leaves nothing to modulo by."""
    task = Pursuit(rest_s=0.0, hop_s=0.0, hops=1, recover_s=0.0)
    assert task.duration == 0.0
    assert task.phase_at(0.0) == "done"
    assert task.value_at(0.0) == 0.0


def test_a_single_hop_is_flat_rather_than_undefined():
    """One hop has no interior waypoint to move to. It must read as a hold at baseline,
    not index past the end of the waypoint list."""
    task = Pursuit(rest_s=0.0, hop_s=2.0, hops=1, recover_s=0.0)
    assert task.value_at(1.0) == 0.0
    assert task.phase_at(1.0) == "hold"


def test_two_hops_are_one_full_excursion_out_and_back():
    """The smallest trajectory that moves. With a single interior waypoint there is no
    spread to normalise against, so it must still be a full-scale excursion."""
    task = Pursuit(rest_s=0.0, hop_s=1.0, hops=2, recover_s=0.0)
    assert task.value_at(0.0) == 0.0
    assert task.value_at(1.0) == 1.0
    assert task.value_at(2.0 - 1e-9) == pytest.approx(0.0, abs=1e-6)
    assert task.phase_at(0.5) == "ramp_up"
    assert task.phase_at(1.5) == "ramp_down"


@pytest.mark.parametrize(
    "kwargs, field",
    [
        ({"rest_s": -1.0}, "rest_s"),
        ({"hop_s": -0.1}, "hop_s"),
        ({"recover_s": -2.0}, "recover_s"),
        ({"hops": 0}, "hops"),
        ({"hops": -3}, "hops"),
        ({"reps": 0}, "reps"),
        ({"reps": -2}, "reps"),
    ],
)
def test_validation_names_the_offending_field(kwargs, field):
    """An error that does not name the field leaves the user guessing which of the five
    arguments they got wrong."""
    with pytest.raises(ValueError, match=field):
        Pursuit(**kwargs)


def test_the_docstring_example_runs():
    """The class docstring is the reference. `tests/test_docstring_examples.py` collects
    the other pure-computation objects; this keeps `Pursuit` honest the same way."""
    results = doctest.testmod(
        m=__import__("myogestic.tracking", fromlist=["tracking"]),
        extraglobs={},
        verbose=False,
        optionflags=doctest.ELLIPSIS,
    )
    assert results.failed == 0
    assert results.attempted > 0


def test_target_source_streams_the_pursuit_as_a_signed_two_channel_signal():
    """`TargetSource` drives a task through `value_at` / `phase_at` / `total_duration`
    only — the three members `Trajectory` names — so a new shape should record with no
    change to the streaming path. This is the test that fails if `Pursuit` drifts off
    that protocol, or emits a phase name that is not in the frozen `PHASE_CODES` table.

    Passed by keyword: the parameter is `trajectory`, not the name of any one shape, and
    a rename back to a shape's name is a break for every caller."""
    from myogestic.sources.target import PHASE_CODES, TargetSource

    task = Pursuit(rest_s=0.1, hop_s=0.05, hops=12, recover_s=0.1)
    source = TargetSource(trajectory=task, fs=200.0)
    info = source.connect()
    source.start()

    chunks = []
    # Enough reads to run past the end of the block and see it stop itself.
    for _ in range(int(task.total_duration * 200.0 / 10.0) + 4):
        data, _ = source.read()
        chunks.append(data)
    source.disconnect()

    out = np.concatenate(chunks)
    assert info.n_channels == 2
    assert out[:, 0].min() < -0.5, "the recorded target never went negative"
    assert out[:, 0].max() > 0.5, "the recorded target never went positive"
    assert np.all(np.abs(out[:, 0]) <= 1.0)

    seen = set(out[:, 1].astype(int).tolist())
    assert {PHASE_CODES["ramp_up"], PHASE_CODES["ramp_down"]} <= seen
    assert PHASE_CODES["idle"] in seen, "the block never ended on its own"
    assert seen <= set(PHASE_CODES.values()), "an unknown phase code reached the stream"
