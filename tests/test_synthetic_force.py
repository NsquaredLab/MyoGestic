"""A fake load cell, so a force task can be exercised with nothing plugged in.

It stands in for the transducer only. The subject is whoever moves `effort` —
nothing here tracks the target, because that tracking is the measurement.

`SyntheticSource` cannot stand in for this: its channels are fixed sine waves,
so there is no resting level to zero and no peak to calibrate against.
"""

import numpy as np
import pytest

from myogestic.sources import SyntheticForceSource
from myogestic.tracking import Calibration


def _drain(source: SyntheticForceSource, chunks: int) -> np.ndarray:
    return np.concatenate([source.read()[0][:, 0] for _ in range(chunks)])


def test_it_reports_one_named_channel_in_its_own_units():
    force = SyntheticForceSource()
    info = force.connect()
    assert info.n_channels == 1
    assert info.channel_names == ["force"]


def test_at_rest_it_reads_the_transducer_offset_not_zero():
    """The offset is the point. A calibration that assumes rest is 0.0 is the
    mistake this source exists to let you make and then see."""
    force = SyntheticForceSource(zero=0.30, span=2.0, noise=0.0, lag_s=0.0)
    force.connect()
    assert _drain(force, 3)[-1] == pytest.approx(0.30, abs=1e-5)


def test_full_effort_reads_a_full_span_above_rest():
    """What capturing an MVC has to produce."""
    force = SyntheticForceSource(zero=0.30, span=2.0, noise=0.0, lag_s=0.0)
    force.connect()
    force.effort = 1.0
    assert _drain(force, 3)[-1] == pytest.approx(2.30, abs=1e-5)


def test_the_captured_calibration_turns_it_back_into_percent():
    """The round trip the whole task depends on: volts in, %MVC out."""
    force = SyntheticForceSource(zero=0.30, span=2.0, noise=0.0, lag_s=0.0)
    force.connect()
    zero = _drain(force, 3)[-1]
    force.effort = 1.0
    mvc = _drain(force, 3)[-1]

    cal = Calibration(zero=zero, mvc=mvc)
    force.effort = 0.5
    half = _drain(force, 3)[-1]

    assert cal.normalise(half) == pytest.approx(50.0, abs=0.5)


def test_effort_is_the_only_thing_that_moves_it():
    """No hidden driver. A channel that followed the target on its own would
    draw a tracking error nobody produced — the one number the task measures."""
    force = SyntheticForceSource(zero=0.0, span=1.0, noise=0.0, lag_s=0.0)
    force.connect()

    assert _drain(force, 3)[-1] == pytest.approx(0.0, abs=1e-5)
    force.effort = 0.4
    assert _drain(force, 3)[-1] == pytest.approx(0.4, abs=1e-5)
    force.effort = 0.0
    assert _drain(force, 3)[-1] == pytest.approx(0.0, abs=1e-5)


def test_the_lag_smooths_a_slider_drag_into_a_contraction():
    """Dragging a slider is a step; a muscle is not."""
    force = SyntheticForceSource(zero=0.0, span=1.0, noise=0.0, lag_s=5.0)
    force.connect()
    force.effort = 1.0

    first = _drain(force, 2)[-1]

    assert first < 1.0, "reached full effort instantly despite a 5 s time constant"
    assert first > 0.0, "never started moving"


def test_a_zero_lag_follows_the_slider_exactly():
    force = SyntheticForceSource(zero=0.0, span=1.0, noise=0.0, lag_s=0.0)
    force.connect()
    force.effort = 0.8
    assert _drain(force, 1)[-1] == pytest.approx(0.8, abs=1e-5)


def test_noise_is_added_on_top_and_can_be_turned_off():
    quiet = SyntheticForceSource(noise=0.0, lag_s=0.0)
    quiet.connect()
    loud = SyntheticForceSource(noise=0.2, lag_s=0.0)
    loud.connect()
    assert np.std(_drain(quiet, 4)) == pytest.approx(0.0, abs=1e-6)
    assert np.std(_drain(loud, 4)) > 0.05


def test_timestamps_advance_monotonically():
    force = SyntheticForceSource(noise=0.0)
    force.connect()
    _, first = force.read()
    _, second = force.read()
    assert (np.diff(first) > 0).all()
    assert second[0] > first[-1]
