"""Tests for `iter_target_windows` — windows paired with a recorded continuous target.

The discrete sibling hands back a class index, so three cued classes stay a three-class
problem however they are fitted. This iterator pairs each window with the value of a
recorded `TargetSource` stream, and the three things that have to be right are the
*instant* the target is read at (the window's end), the *lookup* (by timestamp, because
the target runs far slower than the EMG), and the *phase filter* (idle and done are not
the subject following anything).
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence

import numpy as np
import pytest

from myogestic.session import Session, iter_labeled_windows, iter_target_windows
from myogestic.sources.target import PHASE_CODES
from myogestic.stream import StreamInfo


def _write_session(
    base: str,
    *,
    emg_fs: float,
    emg_ts: np.ndarray,
    emg: np.ndarray | None = None,
    target_fs: float = 20.0,
    target_ts: np.ndarray | None = None,
    target: np.ndarray | None = None,
    names: Sequence[str] | None = None,
    labels: Sequence[tuple[int, float]] = (),
) -> str:
    """A packed ``.session.zip`` with an ``emg`` stream and an optional ``target`` stream.

    ``target=None`` writes no target stream at all; a zero-row ``target`` writes the
    stream but records nothing into it. ``names`` overrides the recorded channel names,
    which is how a stream that is *not* a `TargetSource` recording is built.
    """
    session = Session(base_path=base)
    if emg is None:
        emg = np.tile(np.arange(len(emg_ts), dtype=np.float32)[:, None], (1, 2))
    session.init_stream(
        "emg", StreamInfo(n_channels=emg.shape[1], fs=emg_fs, dtype=np.dtype("float32"))
    )
    session.append("emg", emg, emg_ts)
    if target is not None:
        assert target_ts is not None
        session.init_stream(
            "target",
            StreamInfo(
                n_channels=target.shape[1],
                fs=target_fs,
                dtype=np.dtype("float32"),
                channel_names=(
                    list(names) if names is not None else ["target_pct", "phase"][: target.shape[1]]
                ),
            ),
        )
        if len(target):
            session.append("target", target, target_ts)
    for class_index, timestamp in labels:
        session.add_label(class_index, timestamp=timestamp)
    session.save_meta("TargetWindows")
    return str(session.pack_to_zip())


def _ramp_target(ts: np.ndarray, phase: str = "ramp_up", slope: float = 1.0) -> np.ndarray:
    """Target samples whose value is ``slope * t``, all in one phase."""
    out = np.empty((len(ts), 2), dtype=np.float32)
    out[:, 0] = slope * ts
    out[:, 1] = PHASE_CODES[phase]
    return out


def test_target_is_the_value_at_the_window_end():
    """The defining rule: a causal model answers for *now*, so the target is at the end.

    The target ramps as ``value == t``, so every window has a distinct correct answer and
    an off-by-anything is visible. The last two assertions are the point of the test: the
    yielded value must differ from what taking the window *start* or the window *mean*
    would produce.
    """
    emg_ts = np.arange(200) / 100.0
    target_ts = np.arange(40) / 20.0
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            target_fs=20.0,
            target_ts=target_ts,
            target=_ramp_target(target_ts),
        )
        windows = list(iter_target_windows([path], "emg", "target", 200, 100))

    assert windows
    values = [value for _w, _ts, value in windows]
    assert len(set(values)) == len(values), "a ramp must give every window its own target"
    for _w, w_ts, value in windows:
        assert value == pytest.approx(float(w_ts[-1]))
        assert value != pytest.approx(float(w_ts[0])), "target must not be the window start"
        assert value != pytest.approx(float(w_ts.mean())), "target must not be the window mean"


def test_windows_past_the_targets_last_sample_are_dropped_not_clamped():
    """Outside the target stream's own span there is no ground truth to interpolate.

    The EMG runs to 2.0 s, the target stops at 1.95 s. Clamping would hand the trailing
    windows the last recorded value as if the subject were still being shown it.
    """
    emg_ts = np.arange(200) / 100.0
    target_ts = np.arange(40) / 20.0  # last sample at 1.95
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            target_fs=20.0,
            target_ts=target_ts,
            target=_ramp_target(target_ts),
        )
        ends = [
            float(w_ts[-1])
            for _w, w_ts, _v in iter_target_windows([path], "emg", "target", 200, 100)
        ]

    assert ends, "the covered windows must still be yielded"
    assert max(ends) <= target_ts[-1] + 1e-9
    assert max(ends) == pytest.approx(1.89)  # 1.99 would be the clamped, invented one


def test_lookup_is_by_timestamp_not_by_index():
    """EMG at 256 Hz beside a target at 10 Hz, offset so no sample instants coincide.

    Sample *i* of one stream is nowhere near sample *i* of the other, so an
    index-aligned implementation reads a target seconds away from its window.
    """
    emg_ts = np.arange(1024) / 256.0
    target_ts = 0.017 + np.arange(20) / 10.0
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=256.0,
            emg_ts=emg_ts,
            target_fs=10.0,
            target_ts=target_ts,
            target=_ramp_target(target_ts, slope=3.0),
        )
        windows = list(iter_target_windows([path], "emg", "target", 250, 125))

    assert len(windows) > 5
    for _w, w_ts, value in windows:
        assert value == pytest.approx(3.0 * float(w_ts[-1]), rel=1e-5)


def test_idle_and_done_are_excluded_by_default_and_includable_on_request():
    """Idle and done are the subject doing whatever they like at target zero."""
    emg_ts = np.arange(300) / 100.0
    target_ts = np.arange(60) / 20.0
    target = np.zeros((60, 2), dtype=np.float32)
    target[:, 0] = target_ts
    target[:, 1] = np.where(
        target_ts < 1.0,
        PHASE_CODES["idle"],
        np.where(target_ts < 2.0, PHASE_CODES["hold"], PHASE_CODES["done"]),
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            target_fs=20.0,
            target_ts=target_ts,
            target=target,
        )
        default = [
            float(t[-1]) for _w, t, _v in iter_target_windows([path], "emg", "target", 200, 100)
        ]
        everything = [
            float(t[-1])
            for _w, t, _v in iter_target_windows(
                [path], "emg", "target", 200, 100, phases=set(PHASE_CODES)
            )
        ]
        holds_only = [
            float(t[-1])
            for _w, t, _v in iter_target_windows([path], "emg", "target", 200, 100, phases={"hold"})
        ]

    assert default, "the hold windows must survive the default filter"
    assert all(1.0 <= end < 2.0 for end in default)
    assert default == holds_only
    assert len(everything) > len(default)
    assert any(end < 1.0 for end in everything), "idle windows are includable on request"
    assert any(end >= 2.0 for end in everything), "done windows are includable on request"


def test_a_window_straddling_a_phase_boundary_is_classified_by_its_end():
    """One instant decides both the target and the phase, so the two cannot disagree.

    The boundary is at 1.0 s. The window spanning 0.90–1.09 s straddles it and is kept
    (it ends in ``hold``); the window spanning 0.80–0.99 s ends in ``idle`` and is not.
    """
    emg_ts = np.arange(200) / 100.0
    target_ts = np.arange(200) / 100.0
    target = np.empty((200, 2), dtype=np.float32)
    target[:, 0] = target_ts
    target[:, 1] = np.where(target_ts < 1.0, PHASE_CODES["idle"], PHASE_CODES["hold"])
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            target_fs=100.0,
            target_ts=target_ts,
            target=target,
        )
        windows = list(iter_target_windows([path], "emg", "target", 200, 100))

    spans = {(round(float(t[0]), 2), round(float(t[-1]), 2)): v for _w, t, v in windows}
    assert (0.90, 1.09) in spans, "a window ending in hold is kept even if it starts in idle"
    assert spans[(0.90, 1.09)] == pytest.approx(1.09), "and its target is still the end value"
    assert (0.80, 0.99) not in spans, "a window ending in idle is dropped"


def test_a_step_in_the_target_is_never_interpolated_through():
    """A value the subject was never shown must not appear as a label.

    `TargetSource.stop` — the Stop button — drops the level and switches the phase to
    ``idle`` in one sample. Interpolating the *value* forward while holding the *phase*
    backward is two rules, and between them they mint a whole ramp of intermediate
    targets out of a recording that only ever contained 30 and 0.
    """
    target_ts = np.arange(400) / 100.0
    target = np.empty((400, 2), dtype=np.float32)
    # The last "hold" sample is at 3.00 and the first "idle" one at 3.01, so the step is
    # one target period wide and windows ending inside it are still hold windows.
    step = target_ts > 3.0 + 1e-9
    target[:, 0] = np.where(step, 0.0, 30.0)
    target[:, 1] = np.where(step, PHASE_CODES["idle"], PHASE_CODES["hold"])
    emg_ts = np.arange(4000) / 1000.0
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=1000.0,
            emg_ts=emg_ts,
            emg=np.zeros((4000, 2), dtype=np.float32),
            target_fs=100.0,
            target_ts=target_ts,
            target=target,
            names=["target_pct", "phase"],
        )
        windows = list(iter_target_windows([path], "emg", "target", 200, 1))

    assert windows
    recorded = {0.0, 30.0}
    invented = sorted({v for _w, _t, v in windows} - recorded)
    assert not invented, f"targets never recorded anywhere in the session: {invented}"
    # And the windows landing inside the step are still kept, classified by their end.
    inside = [v for _w, t, v in windows if 3.0 < float(t[-1]) < 3.01]
    assert inside, "the straddling windows must still be yielded, not silently dropped"
    assert set(inside) == {30.0}, "held at the sample that gave the phase"


def test_a_hole_in_the_target_stream_is_not_bridged():
    """A gap inside the target's span is as unrecorded as the span past its end.

    Nothing was written between 1.0 s and 2.0 s, so there is no ground truth there.
    Interpolating across it invents a smooth ramp from 0 to 40 %MVC that no subject was
    ever shown, and every window in the hole would carry one of its rungs.
    """
    kept = np.concatenate([np.arange(0, 100) / 100.0, np.arange(200, 400) / 100.0])
    target = np.empty((len(kept), 2), dtype=np.float32)
    target[:, 0] = np.where(kept < 1.0, 0.0, 40.0)
    target[:, 1] = PHASE_CODES["hold"]
    emg_ts = np.arange(400) / 100.0
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            emg=np.zeros((400, 2), dtype=np.float32),
            target_fs=100.0,
            target_ts=kept,
            target=target,
            names=["target_pct", "phase"],
        )
        windows = list(iter_target_windows([path], "emg", "target", 200, 100))

    assert windows, "the covered stretches must still yield windows"
    in_hole = [(float(t[-1]), v) for _w, t, v in windows if 0.99 < float(t[-1]) < 2.0]
    assert not in_hole, f"windows ending in the hole must be dropped, got {in_hole}"
    assert {v for _w, _t, v in windows} <= {0.0, 40.0}


def test_a_window_spanning_a_signal_dropout_is_dropped():
    """A window is only causal if its samples actually sit behind the instant it answers
    for. Cut by index, twenty samples straddling a four-second dropout reach back four
    seconds — and would be labelled with the target at their last sample regardless."""
    target_ts = np.arange(900) / 100.0
    target = _ramp_target(target_ts, slope=10.0)
    emg_ts = np.concatenate([np.arange(0, 200) / 100.0, np.arange(600, 800) / 100.0])
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            emg=np.zeros((len(emg_ts), 2), dtype=np.float32),
            target_fs=100.0,
            target_ts=target_ts,
            target=target,
            names=["target_pct", "phase"],
        )
        windows = list(iter_target_windows([path], "emg", "target", 200, 100))

    assert windows, "windows inside each intact segment must survive"
    for _w, t, _v in windows:
        assert float(t[-1] - t[0]) < 0.25, f"window spans {float(t[-1] - t[0]):.2f}s of wall time"


def test_a_stream_that_is_not_a_target_recording_raises():
    """Two channels is not enough to be a `TargetSource` recording.

    A nine-DOF control stream has more than two channels and its second column rounds to
    a legal phase code, so it sails through a width check and trains the model against
    the wrong column in silence. The channel names are recorded; they are the test.
    """
    emg_ts = np.arange(400) / 100.0
    control_ts = np.arange(80) / 20.0
    control = np.zeros((80, 9), dtype=np.float32)
    control[:, 0] = np.linspace(-1.0, 1.0, 80)
    control[:, 1] = 0.4  # rounds to PHASE_CODES["rest"] == 0
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            emg=np.zeros((400, 2), dtype=np.float32),
            target_fs=20.0,
            target_ts=control_ts,
            target=control,
            names=[f"dof{i}" for i in range(9)],
        )
        with pytest.raises(ValueError, match="phase code"):
            list(iter_target_windows([path], "emg", "target", 200, 100))


def test_window_length_is_not_truncated_by_float_slop():
    """290 ms at 100 Hz is 29 samples. ``int(290 / 1000 * 100)`` is 28."""
    emg_ts = np.arange(200) / 100.0
    target_ts = np.arange(40) / 20.0
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            target_fs=20.0,
            target_ts=target_ts,
            target=_ramp_target(target_ts),
        )
        windows = list(iter_target_windows([path], "emg", "target", 290, 100))

    assert windows
    for window, w_ts, _v in windows:
        assert window.shape[1] == 29
        assert len(w_ts) == 29


def test_missing_target_stream_raises_naming_the_stream():
    """Silently skipping the one session recorded without a target is how you train on
    two thirds of your data and never find out."""
    emg_ts = np.arange(200) / 100.0
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(tmp, emg_fs=100.0, emg_ts=emg_ts)
        with pytest.raises(ValueError, match="no stream named 'target'"):
            list(iter_target_windows([path], "emg", "target", 200, 100))


def test_empty_target_stream_raises():
    """A target stream that recorded nothing gives no window a target."""
    emg_ts = np.arange(200) / 100.0
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            target_fs=20.0,
            target_ts=np.zeros(0),
            target=np.zeros((0, 2), dtype=np.float32),
        )
        with pytest.raises(ValueError, match="recorded no samples"):
            list(iter_target_windows([path], "emg", "target", 200, 100))


def test_single_channel_target_stream_raises():
    """Without the phase channel it is not a TargetSource recording."""
    emg_ts = np.arange(200) / 100.0
    target_ts = np.arange(40) / 20.0
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            target_fs=20.0,
            target_ts=target_ts,
            target=target_ts.astype(np.float32)[:, None],
        )
        with pytest.raises(ValueError, match="channel"):
            list(iter_target_windows([path], "emg", "target", 200, 100))


def test_rejects_bad_arguments():
    """Bad window/hop/phase arguments fail on the first pull, not silently."""
    with pytest.raises(ValueError, match="window_ms"):
        list(iter_target_windows([], "emg", "target", 0, 100))
    with pytest.raises(ValueError, match="hop_ms"):
        list(iter_target_windows([], "emg", "target", 200, 0))
    with pytest.raises(ValueError, match="unknown phase name"):
        list(iter_target_windows([], "emg", "target", 200, 100, phases={"holding"}))


def test_missing_signal_stream_is_skipped_like_the_sibling():
    """A missing *signal* stream is a skip, matching `iter_labeled_windows`."""
    emg_ts = np.arange(200) / 100.0
    target_ts = np.arange(40) / 20.0
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            target_fs=20.0,
            target_ts=target_ts,
            target=_ramp_target(target_ts),
        )
        assert list(iter_target_windows([path], "kinematics", "target", 200, 100)) == []


def test_the_discrete_iterator_is_untouched():
    """`iter_labeled_windows` still walks the label track, target stream present or not.

    Same session, same numbers as the shipped basic test: 0.2 s windows at a 0.1 s hop
    over two 1 s labelled segments give nine windows each, channels-first.
    """
    emg_ts = np.arange(200) / 100.0
    emg = np.arange(200 * 2, dtype=np.float32).reshape(200, 2)
    target_ts = np.arange(40) / 20.0
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_session(
            tmp,
            emg_fs=100.0,
            emg_ts=emg_ts,
            emg=emg,
            target_fs=20.0,
            target_ts=target_ts,
            target=_ramp_target(target_ts),
            labels=[(0, 0.0), (1, 1.0)],
        )
        windows = list(iter_labeled_windows([path], "emg", window_ms=200, hop_ms=100))

    assert len([1 for _w, _t, ci in windows if ci == 0]) == 9
    assert len([1 for _w, _t, ci in windows if ci == 1]) == 9
    for window, ts, class_index in windows:
        assert window.shape == (2, 20)
        assert ts.shape == (20,)
        assert isinstance(class_index, int)
