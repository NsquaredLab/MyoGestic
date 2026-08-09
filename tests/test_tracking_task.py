"""`TrackingTask` — the imgui-free decisions, plus one render pass.

Everything the widget *decides* (which channel it reads, what a calibration capture
keeps, whether Start is allowed, what a raw sample is worth as a percentage) lives in
methods that never touch imgui, so it is tested here directly. The render pass is one
test, and it is about not raising and not corrupting the frame — the look is review.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from myogestic.tracking import Calibration, Trapezoid
from myogestic.widgets.tracking import (
    _MAX_REPS,
    _SEGMENT_ROWS,
    _TRACE_GAP_S,
    TrackingTask,
    _block_note,
    _distinct,
    _rep_corners,
    _segment_spans,
    _target_curve,
)


def _task(**kwargs) -> TrackingTask:
    return TrackingTask("emg", **kwargs)


def test_a_stream_that_shrinks_clamps_the_read_but_keeps_the_operators_pick():
    """The chosen channel must come back when the device does.

    Clamping `self._channel` in place would quietly rewrite the operator's choice to
    whatever the narrowest moment allowed — an amplifier that drops to 8 channels for
    one frame and reconnects at 72 would leave the task reading channel 7 forever, and
    nothing on screen would say so.
    """
    task = _task(channel=64)

    assert task._resolve_channel(72) == 64
    assert task._resolve_channel(8) == 7  # clamped for *this* read only
    assert task._resolve_channel(72) == 64  # ... and the pick survived it

    assert task._resolve_channel(0) == 0  # no channels at all must not go negative


def test_a_live_sample_is_the_mean_of_the_tail_not_the_last_sample():
    """One raw sample from a load cell is noise with a force in it.

    The tail is what makes the trace readable; if this collapses to a single sample the
    plotted force jitters by the channel's full noise amplitude every frame.
    """
    fs = 1000.0
    task = _task(channel=2, tail_ms=100.0)
    # Channel 2 is 0 for the first 900 ms and 4.0 for the last 100 ms; anything wider
    # than the tail drags the mean below 4, anything narrower is not an average.
    data = np.zeros((4, 1000), dtype=np.float32)
    data[2, -100:] = 4.0

    assert task._mean_tail(data, fs) == pytest.approx(4.0)
    # A different channel must not leak in.
    assert task._mean_tail(np.ones((4, 1000), dtype=np.float32) * 7.0, fs) == pytest.approx(7.0)


def test_an_unreadable_window_is_no_reading_rather_than_zero():
    """A disconnected stream reads as ``None``, so it cannot be captured as a zero.

    Returning 0.0 would let Zero/MVC capture a number nothing measured, and the task
    would then express targets as a percentage of nothing.
    """
    task = _task()
    assert task._mean_tail(np.empty((0, 0), dtype=np.float32), 1000.0) is None
    assert task._mean_tail(np.zeros((4, 0), dtype=np.float32), 1000.0) is None
    assert task._mean_tail(np.zeros((4, 10), dtype=np.float32), 0.0) is None


def test_the_mvc_capture_keeps_the_peak_over_its_whole_window():
    """MVC is the maximum over a few seconds, not whatever arrived when it ended.

    A subject's peak is brief and rarely lands on the last frame of the capture; taking
    the final sample would understate MVC and put every target above the intended force.
    """
    task = _task(mvc_capture_s=3.0)
    task._capture_mvc(now=100.0)

    task._tick(100.5, 1.0)
    task._tick(101.5, 9.0)  # the peak, mid-capture
    task._tick(102.5, 2.0)
    assert task._mvc is None, "captured before the window closed"

    task._tick(103.0, 3.0)
    assert task._mvc == pytest.approx(9.0)
    assert task._mvc_until is None


def test_a_capture_that_saw_nothing_leaves_the_previous_value_alone():
    """A capture run against a dead stream must not overwrite a good MVC."""
    task = _task(mvc_capture_s=1.0)
    task._mvc = 5.0
    task._capture_mvc(now=0.0)

    task._tick(0.5, None)
    task._tick(1.0, None)

    assert task._mvc == pytest.approx(5.0)
    assert task._mvc_until is None


def test_zero_capture_ignores_a_missing_reading():
    """Pressing Zero with nothing streaming must not pin the baseline to a guess."""
    task = _task()
    task._capture_zero(None)
    assert task._zero is None
    task._capture_zero(0.25)
    assert task._zero == pytest.approx(0.25)


def test_start_is_refused_until_both_calibration_points_exist():
    """A % MVC target is meaningless without both numbers, and the panel must say so.

    Zero alone leaves the resting offset in every reading; MVC alone leaves no scale.
    Starting anyway would record a block whose "30 %" is not 30 % of anything.
    """
    task = _task()
    assert task._start_reason(None), "no stream is also a reason"

    stream = object()  # `_start_reason` only needs it to be non-None
    assert "Zero and MVC" in task._start_reason(stream)

    task._capture_zero(0.1)
    assert task._start_reason(stream), "zero alone is not a calibration"

    task._mvc = 1.1
    assert task._start_reason(stream) == ""

    # An MVC capture in flight is also a refusal: the scale is about to change.
    task._capture_mvc(now=0.0)
    assert task._start_reason(stream)


def test_the_running_trace_is_normalised_and_ends_with_the_block():
    """The plotted force is % MVC on the target's own axis, and stops when it does.

    Without the auto-stop the trace would keep growing past the end of the block and the
    plot would run off its own x range.
    """
    trap = Trapezoid(rest_s=0.0, ramp_up_s=1.0, hold_s=1.0, ramp_down_s=1.0, recover_s=0.0)
    task = _task(trapezoid=trap)
    task._zero, task._mvc = 1.0, 3.0  # so 2.0 is exactly 50 % of MVC
    task._start()
    task._started = 0.0  # pin the clock; `_start` reads the real monotonic one

    task._tick(0.5, 2.0)
    assert task._trace_y == pytest.approx([Calibration(1.0, 3.0).normalise(2.0)])
    assert task._trace_y[0] == pytest.approx(50.0)

    task._tick(trap.total_duration, 2.0)
    assert task._started is None, "the block did not end itself"
    assert len(task._trace_t) == 1, "a sample was appended past the end of the block"


def test_the_trace_survives_the_stream_going_away_mid_block():
    """A dropout is a gap in the trace: not a crash, not a fake zero — and not a
    straight line joining the two sides of it.

    This test previously asserted only that the timestamps skipped, which left
    the plot drawing a segment straight across the hole. A non-finite point now
    breaks the polyline so the hole reads as one.
    """
    task = _task(trapezoid=Trapezoid(rest_s=0.0, ramp_up_s=10.0, hold_s=0.0, ramp_down_s=0.0))
    task._zero, task._mvc = 0.0, 1.0
    task._start()
    task._started = 0.0

    task._tick(1.0, 0.5)
    task._tick(2.0, None)  # stream gone
    task._tick(3.0, 0.5)

    assert task._trace_t == pytest.approx([1.0, 3.0, 3.0])
    assert task._trace_y[0] == pytest.approx(50.0)
    assert task._trace_y[1] != task._trace_y[1], "the hole must break the polyline"
    assert task._trace_y[2] == pytest.approx(50.0)


def test_the_target_polyline_is_the_trapezoid_it_came_from():
    """The drawn target and the evaluated one are the same trajectory.

    They are separate code paths — a polyline of corners for the plot, `value_at` for
    the read-out — and a subject tracking one while being scored against the other is
    the worst kind of silent bug.
    """
    trap = Trapezoid(
        rest_s=1.0, ramp_up_s=2.0, hold_s=3.0, ramp_down_s=2.0, recover_s=1.0,
        level_pct=40.0, reps=2,
    )
    xs, ys = _target_curve(trap)

    # Away from the corners (where a polyline and a step-wise evaluation legitimately
    # disagree by a hair), interpolating the drawn line must reproduce `value_at`.
    for t in np.arange(0.05, trap.duration, 0.13):
        assert np.interp(t, xs, ys) == pytest.approx(trap.value_at(float(t)), abs=1e-9)

    # ONE repetition, not the block: the plot reframes on each rep, because five
    # trapezoids on one axis leaves none of them readable.
    assert xs[0] == 0.0
    assert xs[-1] == pytest.approx(trap.duration)


def test_the_target_is_only_drawn_as_far_as_the_look_ahead():
    """The subject tracks the target; they do not plan around it.

    A block whose ending is visible from the first frame is a shape to memorise
    rather than follow, which is not what the task measures.
    """
    trap = Trapezoid(
        rest_s=1.0, ramp_up_s=2.0, hold_s=3.0, ramp_down_s=2.0, recover_s=1.0,
        level_pct=40.0,
    )
    xs, ys = _target_curve(trap, upto=2.5)

    assert xs[-1] == pytest.approx(2.5)
    assert ys[-1] == pytest.approx(trap.value_at(2.5)), "the cut end is off the trajectory"
    assert xs[0] == 0.0
    # Everything drawn is still the real trajectory, not a truncated redraw of it.
    for t in np.arange(0.05, 2.5, 0.11):
        assert np.interp(t, xs, ys) == pytest.approx(trap.value_at(float(t)), abs=1e-9)


def test_a_look_ahead_past_the_end_does_not_run_off_the_repetition():
    trap = Trapezoid(rest_s=1.0, ramp_up_s=1.0, hold_s=1.0, ramp_down_s=1.0, recover_s=1.0)
    xs, _ = _target_curve(trap, upto=999.0)
    assert xs[-1] == pytest.approx(trap.duration)


def test_the_trace_starts_over_on_each_repetition():
    """One rep fills the plot, so two attempts must not land on one axis."""
    trap = Trapezoid(rest_s=0.0, ramp_up_s=1.0, hold_s=0.0, ramp_down_s=1.0, recover_s=0.0, reps=3)
    task = _task(trapezoid=trap)
    task._zero, task._mvc = 0.0, 1.0
    task._start()
    task._started = 0.0

    task._tick(0.5, 0.5)  # rep 1
    assert task._trace_rep == 0
    task._tick(trap.duration + 0.5, 0.5)  # rep 2

    assert task._trace_rep == 1
    assert len(task._trace_t) == 1, "the previous repetition was left on the plot"
    assert task._trace_t[0] == pytest.approx(0.5), "trace time is not rep-local"


def test_a_zero_length_segment_draws_as_the_step_it_is():
    """``ramp_up_s=0`` is a legal square wave; the target must jump, not slope."""
    trap = Trapezoid(rest_s=1.0, ramp_up_s=0.0, hold_s=1.0, ramp_down_s=0.0, recover_s=1.0)
    xs, ys = _target_curve(trap)

    # Two points at t=1: the end of rest at 0 %, the start of hold at the level.
    at_one = [y for x, y in zip(xs, ys, strict=True) if x == pytest.approx(1.0)]
    assert 0.0 in at_one
    assert trap.level_pct in at_one


class _FakeTarget:
    """Enough of `TargetSource` to record what the task asked it to do."""

    def __init__(self):
        # Name it exactly as `TargetSource` does. A stub carrying the *old* name accepts
        # a stale write and reports it back, which is how a rename slipped past this
        # test once already — the task wrote to a stray attribute and nothing noticed.
        self.trajectory = None
        self.calls = []

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")


def test_a_driven_target_gets_the_same_shape_and_the_same_start_and_stop():
    """What is drawn and what is recorded must be one trajectory, not two.

    The target stream is the reason the block does not have to be reconstructed from a
    start time months later — which only holds if every edit reaches it, including the
    ones made while a block is already running.
    """
    target = _FakeTarget()
    trap = Trapezoid(rest_s=0.0, ramp_up_s=1.0, hold_s=0.0, ramp_down_s=0.0, recover_s=0.0)
    task = TrackingTask("emg", trapezoid=trap, target=target)
    assert target.trajectory == trap, "the target never got the shape it was built with"

    task._zero, task._mvc = 0.0, 1.0
    task._start()
    task._started = 0.0
    assert target.calls == ["start"]

    task._set_trap(replace(trap, level_pct=55.0))
    assert target.trajectory.level_pct == 55.0, "a mid-block edit did not reach the target"

    # The block running out is the same event as pressing Stop, or the recorded target
    # keeps tracing a block the widget has already finished.
    task._tick(task._trap.total_duration, 0.5)
    assert target.calls == ["start", "stop"]


def test_the_task_renders_with_and_without_its_stream_and_leaves_the_id_stack_balanced(
    implot_frame,
):
    """A plot or table left open corrupts the frame, far away from the cause.

    `implot.begin_plot` and `imgui.begin_table` push state that only their `end_*` pops,
    and the failure surfaces as ``Missing PopID()`` at whatever `end_child` the widget
    happens to sit inside. Render it in a child window so an unbalanced frame fails
    here rather than in somebody's app — and render every branch that has to survive:
    a live stream, a channel index past the end of it, and a stream that is not there.
    """
    from imgui_bundle import imgui

    from myogestic import Stream
    from myogestic.core import Context
    from myogestic.sources import SyntheticSource

    ctx = Context()
    stream = Stream("emg", source=SyntheticSource(n_channels=8, fs=500.0), window_ms=500)
    assert stream.reconnect()
    stream.status = "connected"
    ctx.streams["emg"] = stream

    live = TrackingTask("emg", channel=999, trapezoid=Trapezoid(reps=2))
    live._zero, live._mvc = 0.0, 1.0
    live._start()
    missing = TrackingTask("nope")
    empty = TrackingTask("emg")

    def draw(task, context) -> None:
        def inner() -> None:
            imgui.begin_child("cell", imgui.ImVec2(600, 700))
            task.ui(context)
            imgui.end_child()

        implot_frame(inner)

    draw(live, ctx)  # connected, channel past the end, block running
    draw(missing, ctx)  # named stream is not registered
    draw(empty, Context())  # no streams at all
    stream.disconnect()
    draw(live, ctx)  # the stream it was reading went away mid-block


def test_changing_the_measured_signal_drops_the_calibration():
    """Zero and MVC describe one channel of one transducer.

    Carrying them to another channel expresses its raw counts as a percentage of
    a different signal's span — a number that looks entirely plausible and means
    nothing.
    """
    task = TrackingTask(stream="emg", channel=3)
    task._zero, task._mvc = 0.5, 4.5
    assert task._calibration is not None

    task._forget_calibration()

    assert task._calibration is None
    assert task._zero is None and task._mvc is None


def test_a_gap_in_the_trace_is_drawn_as_a_gap():
    """The panel only accumulates while it is rendered, and it shares a tab.

    Without a break the plot joins the two sides with a straight line the
    subject never produced.
    """
    task = TrackingTask(stream="emg", channel=0)
    task._zero, task._mvc = 0.0, 10.0
    task._started = 0.0

    task._tick(now=1.0, value=4.0)
    task._tick(now=1.0 + _TRACE_GAP_S + 1.0, value=4.0)  # tab was elsewhere

    assert any(y != y for y in task._trace_y), "the hole was joined with a straight line"


def test_reps_cannot_be_driven_high_enough_to_hang_the_app():
    """Reps multiply every segment, and the target polyline is rebuilt each frame."""
    task = TrackingTask(stream="emg")
    task._set_trap(replace(task._trap, reps=min(max(10**6, 1), _MAX_REPS)))
    assert task._trap.reps <= _MAX_REPS


def test_a_block_records_what_it_was_measured_against():
    """Force is recorded in device counts, the target in %MVC.

    Without the two numbers that relate them — and the channel they were
    measured on — the tracking error is not recoverable from the session, which
    is the one number the whole task exists to produce.
    """
    from myogestic.session import Session

    task = _task()
    task._zero, task._mvc = 0.25, 3.75
    task._channel = 64
    session = Session.__new__(Session)  # no folder needed; only `extras` is read
    session.extras = {}

    task._start(session)

    blocks = session.extras["force_tracking"]
    assert len(blocks) == 1
    assert blocks[0]["zero"] == pytest.approx(0.25)
    assert blocks[0]["mvc"] == pytest.approx(3.75)
    assert blocks[0]["channel"] == 64
    assert blocks[0]["stream"] == task._stream_name
    assert blocks[0]["trapezoid"]["level_pct"] == pytest.approx(task._trap.level_pct)


def test_recalibrating_between_blocks_does_not_rewrite_the_earlier_one():
    """One last-write-wins entry would silently misdescribe every block but the last."""
    from myogestic.session import Session

    task = _task()
    session = Session.__new__(Session)
    session.extras = {}

    task._zero, task._mvc = 0.0, 1.0
    task._start(session)
    task._stop()
    task._zero, task._mvc = 0.0, 2.0  # operator recalibrated
    task._start(session)

    mvcs = [b["mvc"] for b in session.extras["force_tracking"]]
    assert mvcs == pytest.approx([1.0, 2.0])


def test_a_block_run_outside_a_recording_notes_nothing():
    """It is not in the data either, so there is nothing to describe."""
    task = _task()
    task._start(None)  # not recording
    assert task._started is not None


# --- the block's own length, which no single field states ---------------------
def test_a_single_rep_block_states_just_its_duration():
    """With one rep there is no multiplication to show, and showing it is noise."""
    trap = Trapezoid(
        rest_s=3.0, ramp_up_s=5.0, hold_s=10.0, ramp_down_s=5.0, recover_s=5.0, level_pct=30.0
    )
    assert _block_note(trap) == "28.0 s"


def test_a_repeated_block_states_the_total_the_operator_is_committing_to():
    """Five durations times a repetition count is arithmetic nobody does before Start,
    and it is the number that decides whether the subject can sit through the block."""
    trap = Trapezoid(
        rest_s=3.0,
        ramp_up_s=5.0,
        hold_s=10.0,
        ramp_down_s=5.0,
        recover_s=5.0,
        level_pct=30.0,
        reps=3,
    )
    assert _block_note(trap) == "3 x 28.0 s = 84.0 s"
    assert trap.total_duration == pytest.approx(84.0)


def test_a_block_of_nothing_is_describable_rather_than_a_division_by_zero():
    """Every segment zero is a legal `Trapezoid`, and it is what dragging one row to
    the floor produces on the way somewhere else. The sketch maps onto it each frame."""
    trap = Trapezoid(
        rest_s=0.0, ramp_up_s=0.0, hold_s=0.0, ramp_down_s=0.0, recover_s=0.0, level_pct=0.0
    )
    assert _block_note(trap) == "0.0 s"
    assert trap.duration == 0.0


# --- the sketch's segment geometry -------------------------------------------
def test_a_segment_is_the_gap_between_the_two_corners_that_bound_it():
    """The invariant the highlight rests on.

    `_light` lights the region between outline corners ``i`` and ``i + 1`` and calls it
    segment ``i``. Off by one and hovering "Hold" lights the ramp beside it — a picture
    that is wrong in the one way nobody checks, because it still looks like a trapezoid.
    """
    trap = Trapezoid(
        rest_s=3.0, ramp_up_s=5.0, hold_s=10.0, ramp_down_s=5.0, recover_s=5.0, level_pct=30.0
    )
    xs, _ = _rep_corners(trap)
    spans = _segment_spans(trap)

    assert len(spans) == len(_SEGMENT_ROWS)
    for i, (start, end) in enumerate(spans):
        assert (start, end) == (xs[i], xs[i + 1])
    # ...and each one is as long as the field it is named for.
    for (start, end), (attr, _label) in zip(spans, _SEGMENT_ROWS, strict=True):
        assert end - start == pytest.approx(getattr(trap, attr))


def test_a_zero_length_segment_keeps_its_place_in_the_order():
    """Dragging Hold to the floor must not shift Ramp down into its index."""
    trap = Trapezoid(
        rest_s=3.0, ramp_up_s=5.0, hold_s=0.0, ramp_down_s=5.0, recover_s=5.0, level_pct=30.0
    )
    spans = _segment_spans(trap)

    assert len(spans) == len(_SEGMENT_ROWS)
    assert spans[2][0] == spans[2][1] == 8.0  # hold, collapsed but still third
    assert spans[3] == (8.0, 13.0)  # ramp down, still fourth


def test_repeated_corners_are_collapsed_before_the_polygon_is_filled():
    """A zero-length segment puts one corner in twice, and the ear-clipper cannot
    triangulate that — it renders a second wedge over the segments that follow."""
    from imgui_bundle import imgui

    points = [imgui.ImVec2(0, 0), imgui.ImVec2(1, 1), imgui.ImVec2(1, 1), imgui.ImVec2(2, 0)]

    kept = _distinct(points)

    assert [(p.x, p.y) for p in kept] == [(0, 0), (1, 1), (2, 0)]


def test_distinct_keeps_corners_that_only_share_one_coordinate():
    """A vertical edge repeats x and a plateau repeats y; neither is a duplicate."""
    from imgui_bundle import imgui

    points = [imgui.ImVec2(0, 0), imgui.ImVec2(0, 5), imgui.ImVec2(3, 5)]

    assert len(_distinct(points)) == 3
