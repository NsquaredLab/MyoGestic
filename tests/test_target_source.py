"""The target trajectory as a recorded stream — geometry, pacing and live edits."""

from __future__ import annotations

import time

import numpy as np
import pytest

from myogestic.sources.target import PHASE_CODES, TargetSource
from myogestic.tracking import Trapezoid

# Fast enough that a whole test is a few hundred milliseconds, slow enough that a chunk
# still spans several samples.
FS = 200.0


def _flat(level_pct: float) -> Trapezoid:
    """A trajectory that sits at `level_pct` for long enough to read without a boundary."""
    return Trapezoid(
        rest_s=0.0,
        ramp_up_s=0.0,
        hold_s=10.0,
        ramp_down_s=0.0,
        recover_s=0.0,
        level_pct=level_pct,
    )


def test_connect_reports_two_named_channels_so_a_recording_can_be_decoded():
    """The recording is read back by name months later. If the names or the count drift,
    an analysis script silently reads the phase code as a force level."""
    source = TargetSource(Trapezoid(), fs=FS)
    info = source.connect()

    assert info.n_channels == 2
    assert info.channel_names == ["target_pct", "phase"]
    assert info.fs == FS

    data, ts = source.read()
    assert data.shape == (len(ts), 2)
    assert data.dtype == info.dtype


def test_successive_reads_advance_time_at_the_sample_rate():
    """`read` must block until its chunk is due. If it returns immediately the acquire
    thread spins, and thousands of chunks pile onto one instant in the recording."""
    source = TargetSource(Trapezoid(), fs=FS)
    source.connect()

    _, first = source.read()
    started = time.perf_counter()
    _, second = source.read()
    wall = time.perf_counter() - started

    chunk_s = len(first) / FS
    assert np.all(np.diff(first) > 0.0)
    assert np.diff(first) == pytest.approx(1.0 / FS, rel=1e-6)
    # The chunks butt up against each other: no gap, no overlap, no rewind.
    assert second[0] - first[-1] == pytest.approx(1.0 / FS, rel=1e-6)
    # It actually waited rather than spinning, but did not stall either.
    assert 0.8 * chunk_s < wall < chunk_s + 0.5


def test_a_stopped_source_still_emits_the_baseline_so_the_recording_has_no_hole():
    """Setup time is recorded too. A source that goes quiet until the operator hits
    start leaves a gap that looks exactly like a dropped connection."""
    source = TargetSource(Trapezoid(level_pct=30.0), fs=FS)
    source.connect()

    assert source.running is False
    data, _ = source.read()

    assert data[:, 0] == pytest.approx(0.0)
    assert data[:, 1] == pytest.approx(PHASE_CODES["idle"])
    assert source.elapsed == 0.0


def test_the_lead_in_is_not_confusable_with_the_blocks_own_rest_phase():
    """Where a block begins has to be answerable from the recording alone.

    Both the wait before Start and the block's rest phase hold ``target_pct`` at 0,
    so if they shared a phase code the two would be one indistinguishable run of
    zeros and the rest phase would measure however long the operator took to press
    the button.
    """
    task = Trapezoid(rest_s=0.5, ramp_up_s=0.5, hold_s=0.5, level_pct=30.0)
    source = TargetSource(task, fs=FS)
    source.connect()

    idle, _ = source.read()
    source.start()
    resting, _ = source.read()

    assert idle[:, 0] == pytest.approx(resting[:, 0])  # the value alone cannot tell them apart
    assert idle[0, 1] == PHASE_CODES["idle"]
    assert resting[-1, 1] == PHASE_CODES["rest"]
    assert PHASE_CODES["idle"] != PHASE_CODES["rest"]


def test_a_running_source_follows_the_trapezoid_for_the_elapsed_time():
    """The streamed target and the drawn target must be the same trajectory. Asserting
    against `Trapezoid` itself is what stops the source growing its own copy of the
    maths that then drifts from the one on screen."""
    task = Trapezoid(
        rest_s=0.1, ramp_up_s=0.6, hold_s=0.6, ramp_down_s=0.6, recover_s=0.1, level_pct=40.0
    )
    source = TargetSource(task, fs=FS)
    source.connect()
    source.start()
    source.read()  # discard the chunk straddling the start instant

    data, ts = source.read()
    n = len(ts)

    assert source.running is True
    assert 0.0 < source.elapsed < task.total_duration
    # `elapsed` is the task time of the newest sample; the rest sit 1/fs apart behind it.
    for i in range(n):
        t = source.elapsed - (n - 1 - i) / FS
        assert data[i, 0] == pytest.approx(task.value_at(t), abs=1e-4)
        assert data[i, 1] == pytest.approx(PHASE_CODES[task.phase_at(t)])


def test_every_phase_the_trapezoid_can_report_has_a_code():
    """The phase channel is written on the acquire thread. A phase with no code raises
    there — mid-recording, off the main thread, with the block already under way."""
    task = Trapezoid(
        rest_s=1.0, ramp_up_s=1.0, hold_s=1.0, ramp_down_s=1.0, recover_s=1.0, level_pct=30.0
    )
    seen = {task.phase_at(t) for t in np.linspace(-1.0, task.total_duration + 1.0, 2000)}

    assert seen  # the sweep found phases at all
    assert seen <= set(PHASE_CODES)
    assert len(set(PHASE_CODES.values())) == len(PHASE_CODES)  # codes are unambiguous


def test_swapping_the_trajectory_mid_run_changes_the_next_chunk():
    """The operator edits the ramp while it streams. The edit must land on a chunk
    boundary — a chunk half on the old shape and half on the new one is a trajectory
    the subject was never shown."""
    source = TargetSource(_flat(20.0), fs=FS)
    source.connect()
    source.start()
    source.read()  # discard the chunk straddling the start instant

    before, _ = source.read()
    source.trajectory = _flat(60.0)
    after, _ = source.read()

    assert before[:, 0] == pytest.approx(20.0)
    assert after[:, 0] == pytest.approx(60.0)
