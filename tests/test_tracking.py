import pytest

from myogestic.tracking import Calibration, Trapezoid

DT = 0.001


def _samples(task: Trapezoid, dt: float = DT) -> list[tuple[float, float]]:
    n = int(round(task.total_duration / dt))
    return [(i * dt, task.value_at(i * dt)) for i in range(n + 1)]


def test_the_trajectory_never_jumps_at_a_segment_boundary():
    """A step in the target is a step the subject cannot track. If this fails, the
    segment boundaries disagree about the level and the plot shows a cliff."""
    task = Trapezoid()
    slope = task.level_pct / min(task.ramp_up_s, task.ramp_down_s)  # %/s, the steepest legal rate
    values = [v for _, v in _samples(task)]
    worst = max(abs(b - a) for a, b in zip(values, values[1:], strict=False))
    assert worst <= slope * DT + 1e-9


def test_a_repetition_starts_and_ends_at_baseline():
    """The subject must be at rest at both ends, or the next rep starts pre-loaded."""
    task = Trapezoid()
    assert task.value_at(0.0) == pytest.approx(0.0)
    assert task.value_at(task.duration) == pytest.approx(0.0)


def test_the_plateau_holds_exactly_at_the_requested_level():
    """The whole hold must sit at level_pct — a sagging plateau is a different task."""
    task = Trapezoid(level_pct=42.5)
    hold_start = task.rest_s + task.ramp_up_s
    for t in (hold_start, hold_start + task.hold_s / 2, hold_start + task.hold_s - 1e-6):
        assert task.value_at(t) == pytest.approx(42.5)


def test_the_ramps_are_monotonic():
    """Up must only rise and down must only fall; a wobble would ask for a correction
    the subject cannot make."""
    task = Trapezoid()
    up = [task.value_at(task.rest_s + i * DT) for i in range(int(task.ramp_up_s / DT))]
    down_start = task.rest_s + task.ramp_up_s + task.hold_s
    down = [task.value_at(down_start + i * DT) for i in range(int(task.ramp_down_s / DT))]
    assert all(b >= a for a, b in zip(up, up[1:], strict=False))
    assert all(b <= a for a, b in zip(down, down[1:], strict=False))


def test_the_duration_is_the_sum_of_the_segments():
    task = Trapezoid(rest_s=1.0, ramp_up_s=2.0, hold_s=3.0, ramp_down_s=4.0, recover_s=5.0)
    assert task.duration == pytest.approx(15.0)
    assert Trapezoid(reps=3).total_duration == pytest.approx(Trapezoid().duration * 3)


def test_phase_at_agrees_with_value_at_at_every_boundary():
    """The label and the number come from one lookup — if they disagree, the readout
    says 'hold' while the target is still ramping."""
    task = Trapezoid(rest_s=1.0, ramp_up_s=2.0, hold_s=4.0, ramp_down_s=2.0, recover_s=1.0)
    expected = [
        (0.0, "rest", 0.0),
        (0.999, "rest", 0.0),
        (1.0, "ramp_up", 0.0),
        (2.0, "ramp_up", task.level_pct / 2),
        (3.0, "hold", task.level_pct),
        (6.999, "hold", task.level_pct),
        (7.0, "ramp_down", task.level_pct),
        (8.0, "ramp_down", task.level_pct / 2),
        (9.0, "recover", 0.0),
        (10.0, "done", 0.0),
        (99.0, "done", 0.0),
    ]
    for t, phase, value in expected:
        assert task.phase_at(t) == phase, f"phase at t={t}"
        assert task.value_at(t) == pytest.approx(value, abs=1e-2), f"value at t={t}"


def test_a_negative_task_time_reads_as_rest():
    """A countdown before the block starts must not read as 'done'."""
    task = Trapezoid()
    assert task.phase_at(-1.0) == "rest"
    assert task.value_at(-1.0) == pytest.approx(0.0)


def test_a_zero_length_hold_gives_a_triangle_without_raising():
    """hold_s=0 is a legal triangular target — the ramps must meet at the peak instead
    of dividing by zero."""
    task = Trapezoid(rest_s=0.0, ramp_up_s=2.0, hold_s=0.0, ramp_down_s=2.0, recover_s=0.0)
    assert task.duration == pytest.approx(4.0)
    assert task.value_at(2.0 - 1e-9) == pytest.approx(task.level_pct, abs=1e-6)
    assert task.value_at(2.0) == pytest.approx(task.level_pct)
    assert task.phase_at(2.0) == "ramp_down"
    assert "hold" not in {task.phase_at(i * DT) for i in range(int(4.0 / DT))}


def test_zero_length_ramps_step_straight_to_the_next_level():
    """Every segment may be zero — a square target must not divide by a zero ramp."""
    task = Trapezoid(rest_s=1.0, ramp_up_s=0.0, hold_s=2.0, ramp_down_s=0.0, recover_s=1.0)
    assert task.value_at(1.0) == pytest.approx(task.level_pct)
    assert task.phase_at(1.0) == "hold"
    assert task.value_at(3.0) == pytest.approx(0.0)
    assert task.phase_at(3.0) == "recover"


def test_reps_repeat_the_shape_exactly():
    """Rep two must be indistinguishable from rep one, or the analysis cannot pool them."""
    one = Trapezoid()
    three = Trapezoid(reps=3)
    assert three.total_duration == pytest.approx(one.duration * 3)
    step = 0.01
    for i in range(int(one.duration / step)):
        t = i * step
        for rep in range(3):
            offset = t + rep * one.duration
            assert three.value_at(offset) == pytest.approx(one.value_at(t))
            assert three.phase_at(offset) == one.phase_at(t)


def test_the_target_is_zero_once_the_last_rep_is_over():
    task = Trapezoid(reps=2)
    assert task.phase_at(task.total_duration) == "done"
    assert task.value_at(task.total_duration) == pytest.approx(0.0)
    assert task.value_at(task.total_duration + 100.0) == pytest.approx(0.0)


@pytest.mark.parametrize(
    "kwargs, field",
    [
        ({"rest_s": -1.0}, "rest_s"),
        ({"ramp_up_s": -0.1}, "ramp_up_s"),
        ({"hold_s": -1.0}, "hold_s"),
        ({"ramp_down_s": -1.0}, "ramp_down_s"),
        ({"recover_s": -1.0}, "recover_s"),
        ({"level_pct": -5.0}, "level_pct"),
        ({"reps": 0}, "reps"),
        ({"reps": -2}, "reps"),
    ],
)
def test_validation_names_the_offending_field(kwargs, field):
    """An error that does not name the field leaves the user guessing which of the
    seven arguments they got wrong."""
    with pytest.raises(ValueError, match=field):
        Trapezoid(**kwargs)


def test_calibration_maps_zero_to_nothing_and_mvc_to_full():
    """The resting offset must be subtracted from both ends, or every target sits at
    the wrong absolute force."""
    cal = Calibration(zero=0.5, mvc=2.5)
    assert cal.normalise(0.5) == pytest.approx(0.0)
    assert cal.normalise(1.5) == pytest.approx(50.0)
    assert cal.normalise(2.5) == pytest.approx(100.0)


def test_calibration_extrapolates_past_its_endpoints():
    """Overshoot and a push below rest are real subject behaviour, not errors."""
    cal = Calibration(zero=0.5, mvc=2.5)
    assert cal.normalise(3.0) == pytest.approx(125.0)
    assert cal.normalise(0.0) == pytest.approx(-25.0)


def test_calibration_survives_an_uncollected_mvc():
    """mvc == zero means nobody has calibrated yet — read as no effort, do not divide
    by zero mid-trial."""
    assert Calibration(zero=1.0, mvc=1.0).normalise(5.0) == pytest.approx(0.0)
    assert Calibration(zero=0.0, mvc=0.0).normalise(0.0) == pytest.approx(0.0)
