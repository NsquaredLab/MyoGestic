"""Follow trajectories, offline scores and the card's recorded lifecycle."""

import dataclasses

import numpy as np
import pytest

from myogestic import App
from myogestic.sources.target import PHASE_CODES, TargetSource
from myogestic.tracking import Sinusoid, blend_pose, score_tracking
from myogestic.widgets import FollowRun


def test_sinusoid_edges_and_repetitions():
    shape = Sinusoid(move_s=2, hold_low_s=1, hold_high_s=3, peak=0.8, reps=2, lead_s=2)
    assert shape.duration == 8 and shape.total_duration == 18
    for t, phase, value in [
        (-1, "rest", 0),
        (2, "rest", 0),
        (3, "ramp_up", 0),
        (4, "ramp_up", 0.4),
        (5, "hold", 0.8),
        (8, "ramp_down", 0.8),
        (9, "ramp_down", 0.4),
        (10, "rest", 0),
        (18, "done", 0),
    ]:
        assert shape.phase_at(t) == phase
        assert shape.value_at(t) == pytest.approx(value)
    values = [shape.value_at(t) for t in np.linspace(-2, 20, 1001)]
    assert min(values) >= 0 and max(values) <= 0.8
    assert all(shape.phase_at(t) in PHASE_CODES for t in np.linspace(-2, 20, 1001))
    with pytest.raises(dataclasses.FrozenInstanceError):
        shape.peak = 1
    source = TargetSource(shape, fs=100000)
    source.connect()
    source.start()
    data, _ = source.read()
    assert np.all(data[:, 0] == 0) and np.all(data[:, 1] == PHASE_CODES["rest"])
    source.disconnect()


def test_sinusoid_zero_holds_and_smooth_boundaries():
    shape = Sinusoid(move_s=1, hold_low_s=0, hold_high_s=0, lead_s=0, reps=2)
    assert shape.phase_at(0) == "ramp_up"
    assert shape.value_at(1) == 1 and shape.phase_at(1) == "ramp_down"
    assert shape.value_at(2) == 0
    for edge in (0, 1, 2, 3, 4):
        assert abs(shape.value_at(edge + 1e-5) - shape.value_at(edge)) < 1e-8
    assert Sinusoid(peak=0).value_at(7) == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"move_s": 0},
        {"move_s": -1},
        {"hold_low_s": -1},
        {"hold_high_s": -1},
        {"lead_s": -1},
        {"peak": -0.1},
        {"peak": 1.1},
        {"reps": 0},
        {"reps": 1.5},
        {"reps": True},
        *[
            {name: value}
            for name in ("move_s", "hold_low_s", "hold_high_s", "lead_s", "peak")
            for value in (np.nan, np.inf)
        ],
    ],
)
def test_sinusoid_validation(kwargs):
    with pytest.raises(ValueError):
        Sinusoid(**kwargs)


@pytest.mark.parametrize("lag", [-0.3, 0, 0.4])
def test_score_known_lag_on_different_clocks(lag):
    tt = np.arange(0, 20, 0.013)
    tp = np.arange(0, 20, 0.021)

    def signal(t):
        return np.sin(t * 1.3) + 0.25 * np.sin(t * 3.7)

    score = score_tracking(tt, signal(tt), tp, signal(tp - lag), start_s=2, end_s=18)
    assert score["lag_s"] == pytest.approx(lag, abs=0.01)
    assert score["rmse"] == pytest.approx(
        np.sqrt(np.mean((signal(tt[tt > 2]) - signal(tt[tt > 2] - lag)) ** 2)), abs=0.03
    )
    assert score["r"] > 0.8


def test_score_excludes_lead_and_after_run_for_all_metrics():
    t = np.arange(0, 12, 0.01)
    y = np.sin(t)
    p = y.copy()
    p[(t < 2) | (t > 10)] = 10000
    assert score_tracking(t, y, t, p, start_s=2, end_s=10) == pytest.approx(
        {"rmse": 0, "r": 1, "lag_s": 0}
    )
    assert abs(score_tracking(t, y, t, np.sin(t - 0.8), max_lag_s=0.2)["lag_s"]) <= 0.2


def test_score_undefined_and_validation():
    empty = {"rmse": None, "r": None, "lag_s": None}
    assert score_tracking([], [], [], []) == empty
    assert score_tracking([0, 1], [0, 1], [2, 3], [0, 1]) == empty
    assert score_tracking([0, 1], [0, 0], [0, 1], [1, 1]) == {"rmse": 1, "r": None, "lag_s": None}
    assert score_tracking([0], [0], [0], [0]) == {"rmse": 0, "r": None, "lag_s": None}
    for args in (([0, 0], [0, 1], [0, 1], [0, 1]), ([np.nan], [0], [0], [0]), ([0], [], [0], [0])):
        with pytest.raises(ValueError):
            score_tracking(*args)
    for kwargs in ({"step_s": 0}, {"max_lag_s": -1}, {"start_s": 2, "end_s": 1}):
        with pytest.raises(ValueError):
            score_tracking([], [], [], [], **kwargs)


def test_blend_pose():
    a, b = [0, -1, 2], [1, 1, 4]
    np.testing.assert_allclose(blend_pose(a, b, 0.5), [0.5, 0, 3])
    assert a == [0, -1, 2]
    for args in (([], [], 0), ([0], [0, 1], 0), ([np.nan], [1], 0), ([0], [1], 1.1)):
        with pytest.raises(ValueError):
            blend_pose(*args)


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr("myogestic._browser.IS_BROWSER", True)
    from myogestic.widgets.training import _session_state

    monkeypatch.setattr(_session_state, "_states", {})
    app = App("follow test")
    now = [100.0]
    monkeypatch.setattr("myogestic.widgets.follow.local_clock", lambda: now[0])
    widget = FollowRun(
        ["Fist", "Pinch"],
        drive=lambda index, level: None,
        on_record=lambda: app.start_recording(str(tmp_path)),
        on_stop=lambda: app.stop_recording(wait=True),
        trajectory=Sinusoid(move_s=1, hold_low_s=1, hold_high_s=1, lead_s=1, reps=1),
    )
    monkeypatch.setattr(widget, "_run", lambda ctx: None)
    yield widget, app, now
    widget.stop(app.ctx)


@pytest.mark.parametrize("stop_at", [0.5, 3.5, 5.0])
def test_record_saved_target_score_and_unticked_take(run, stop_at):
    from myogestic.session import open_session_store
    from myogestic.widgets.training._session_state import get_state

    widget, app, now = run
    assert widget.start(app.ctx)
    assert not widget.start(app.ctx)
    session = app.ctx.session
    for t in np.arange(0.05, stop_at, 0.05):
        now[0] = 100 + t
        index, level = widget._step(app.ctx)
        session.append_event(
            "controls", [level, level], now[0], channel_names=["prediction", "control"]
        )
    now[0] = 100 + stop_at
    widget.stop(app.ctx)
    assert not app.ctx.recording and widget.target is None
    assert widget._step(app.ctx) is None
    with open_session_store(session.path) as saved:
        target, timestamps = saved.get_continuous("follow.target")
        assert target.shape[1] == 3 and timestamps[0] == 100
        assert saved.extras["follow"]["ended"] == now[0]
    session.extras.clear()  # Scores must come from disk.
    widget.sync(app.ctx)
    assert widget.score["rmse"] == (None if stop_at < 1 else pytest.approx(0))
    row = get_state("Sessions_sessions").sessions[0]
    assert row["follow"] and row["drive"] and not row["selected"]


def test_external_stop_saves_actual_follow_end_and_score_window(run, monkeypatch):
    from myogestic.session import open_session_store
    from myogestic.widgets import _follow_state

    widget, app, now = run
    assert widget.start(app.ctx)
    session = app.ctx.session
    for timestamp in np.linspace(100.05, 103.5, 70):
        now[0] = timestamp
        _, level = widget._step(app.ctx)
        session.append_event("controls", [level], timestamp, channel_names=["prediction"])
    app.stop_recording(wait=True)
    assert widget.running  # Finalization must not depend on the next UI frame.
    with open_session_store(session.path) as saved:
        assert saved.extras["follow"]["ended"] == 103.5
        _, timestamps = saved.get_continuous("follow.target")
        assert timestamps[-1] == 103.5

    bounds = []

    def score(*args, **kwargs):
        bounds.append((kwargs["start_s"], kwargs["end_s"]))
        return score_tracking(*args, **kwargs)

    monkeypatch.setattr(_follow_state, "score_tracking", score)
    now[0] = 104.5
    widget.sync(app.ctx)
    assert bounds == [(101.0, 103.5)]
    assert widget.score == pytest.approx({"rmse": 0, "r": 1, "lag_s": 0})
    assert session.extras["follow"]["ended"] == 103.5


@pytest.mark.parametrize(
    "last_target, expected_end", [(103.5, 103.5), (110.0, 105.0), (None, 104.0)]
)
def test_external_stop_uses_last_target_or_finalize_clock(
    run, monkeypatch, last_target, expected_end
):
    from myogestic.session import open_session_store

    widget, app, now = run
    if last_target is None:
        monkeypatch.setattr(widget, "_step", lambda ctx: None)
    assert widget.start(app.ctx)
    if last_target is not None:
        now[0] = last_target
        widget._step(app.ctx)
    now[0] = 104.0 if last_target is None else last_target + 1
    app.stop_recording(wait=True)
    with open_session_store(app.ctx.session.path) as saved:
        assert saved.extras["follow"]["ended"] == expected_end


def test_external_stop_finalizes_after_sync_without_extending_end(run, monkeypatch):
    from threading import Event, current_thread

    from myogestic.session import open_session_store

    widget, app, now = run
    entered, release = Event(), Event()
    finalizers = []

    def pause_finalize(session):
        finalizers.append(current_thread())
        entered.set()
        assert release.wait(3)

    app.finalize_hooks.append(pause_finalize)
    monkeypatch.setattr("myogestic._browser.IS_BROWSER", False)
    assert widget.start(app.ctx)
    session = app.ctx.session
    now[0] = 103.5
    widget._step(app.ctx)
    app.stop_recording()
    try:
        assert entered.wait(1)
        now[0] = 104.5
        widget.sync(app.ctx)
        assert not widget.running and widget.score is None
    finally:
        release.set()
        for thread in finalizers:
            thread.join(3)
            assert not thread.is_alive()
    with open_session_store(session.path) as saved:
        assert saved.extras["follow"]["ended"] == 103.5
    widget.sync(app.ctx)
    assert app.finalize_hooks == [pause_finalize]


@pytest.mark.parametrize("settle_first", [False, True])
def test_follow_finalize_hook_leaves_other_takes_alone_and_does_not_accumulate(run, settle_first):
    from myogestic.session import open_session_store

    widget, app, now = run
    hooks = list(app.finalize_hooks)
    for _ in range(2):
        assert widget.start(app.ctx)
        assert len(app.finalize_hooks) == len(hooks) + 1
        assert not widget.start(app.ctx)
        assert len(app.finalize_hooks) == len(hooks) + 1
        now[0] += 0.5
        widget._step(app.ctx)
        app.stop_recording(wait=True)
        if settle_first:
            widget.sync(app.ctx)
            assert app.finalize_hooks == hooks

        app.start_recording(str(app.ctx.session.path.parent))
        other = app.ctx.session
        app.stop_recording(wait=True)
        with open_session_store(other.path) as saved:
            assert "follow" not in saved.extras
        widget.sync(app.ctx)
        assert app.finalize_hooks == hooks


def test_deadline_hidden_card_and_take_ownership(run):
    widget, app, now = run
    assert widget.start(app.ctx)
    now[0] = 110
    assert widget._step(app.ctx) == (0, 0)
    widget.sync(app.ctx)
    assert not widget.running and not app.ctx.recording
    app.start_recording(str(app.ctx.session.path.parent))
    other = app.ctx.session
    widget.stop(app.ctx)
    assert app.ctx.recording and app.ctx.session is other
    app.stop_recording(wait=True)


@pytest.mark.parametrize("scale", [1, 2])
@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("state", ["idle", "running", "results"])
def test_card_draws_narrow_with_real_clicks(run, imgui_frame, monkeypatch, scale, dark, state):
    from imgui_bundle import imgui

    from myogestic import _scale, _theme
    from myogestic.widgets import _follow_ui

    widget, app, now = run
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    if state != "idle":
        widget.start(app.ctx)
        if state == "results":
            widget.stop(app.ctx)
            widget.sync(app.ctx)
    bounds = []
    field_bounds = []
    for name in ("input_float", "input_int", "slider_float", "text_colored", "text_unformatted"):
        real = getattr(imgui, name)

        def measured(*args, _real=real, **kwargs):
            result = _real(*args, **kwargs)
            field_bounds.append(
                (imgui.get_item_rect_max().x, imgui.get_window_pos().x + imgui.get_window_size().x)
            )
            return result

        monkeypatch.setattr(imgui, name, measured)
    real_button = _follow_ui.primary_button

    def button(label, size):
        clicked = real_button(label, size)
        bounds.append(
            (imgui.get_item_rect_min().x, imgui.get_item_rect_max().x, imgui.get_window_pos().x)
        )
        return clicked or (label == "Stop")

    monkeypatch.setattr(_follow_ui, "primary_button", button)

    def draw():
        imgui.begin_child("narrow", imgui.ImVec2(320, 0))
        widget.ui(app.ctx)
        imgui.end_child()

    imgui_frame(draw)
    imgui_frame(draw)
    assert bounds and all(x0 >= left and x1 <= left + 320 for x0, x1, left in bounds)
    assert not widget.running
    assert all(right <= edge + 1 for right, edge in field_bounds), field_bounds


def test_chips_are_isolated_and_locked_during_a_run(run, imgui_frame, monkeypatch):
    from imgui_bundle import imgui

    widget, app, now = run
    other = FollowRun(
        widget.gestures,
        drive=lambda index, level: None,
        on_record=lambda: None,
        on_stop=lambda: None,
        widget_id="other",
    )
    real = imgui.button

    def click(label, *args):
        result = real(label, *args)
        return result or "gesture-1" in label

    monkeypatch.setattr(imgui, "button", click)
    imgui_frame(lambda: widget.ui(app.ctx))
    assert widget._state.gesture == 1 and other._state.gesture == 0
    assert widget.start(app.ctx)
    imgui_frame(lambda: widget.ui(app.ctx))
    assert widget.target[0] == 1
    widget.stop(app.ctx)


def test_save_waits_and_missing_predictions_are_undefined(run):
    widget, app, now = run
    assert widget.start(app.ctx)
    now[0] += 2
    widget._step(app.ctx)
    widget.stop(app.ctx)
    app.ctx.pending_saves.add(widget._state.source_path)
    widget.sync(app.ctx)
    assert widget.score is None
    app.ctx.pending_saves.clear()
    widget.sync(app.ctx)
    assert widget.score == {"rmse": None, "r": None, "lag_s": None}


@pytest.mark.parametrize("hz", [0, -1, float("nan"), float("inf"), -float("inf")])
def test_follow_rate_must_be_finite_and_positive(hz):
    with pytest.raises(ValueError, match="hz"):
        FollowRun(
            ["Fist"],
            drive=lambda index, level: None,
            on_record=lambda: None,
            on_stop=lambda: None,
            hz=hz,
        )


def test_drive_failure_logs_once_and_keeps_running(tmp_path, monkeypatch):
    from threading import Event

    monkeypatch.setattr("myogestic._browser.IS_BROWSER", True)
    app, attempts, ready = App("drive failure"), [], Event()

    def drive(index, level):
        attempts.append((index, level))
        if len(attempts) == 4:
            ready.set()
        raise RuntimeError("offline hand")

    messages = []
    monkeypatch.setattr(type(app.ctx), "log", lambda self, text: messages.append(text))
    widget = FollowRun(
        ["Fist"],
        drive=drive,
        hz=64,
        on_record=lambda: app.start_recording(str(tmp_path)),
        on_stop=lambda: app.stop_recording(wait=True),
    )
    try:
        assert widget.start(app.ctx)
        assert ready.wait(3)
    finally:
        widget.stop(app.ctx)
    assert len(attempts) >= 4
    assert len([text for text in messages if "Follow drive failed" in text]) == 1
    assert not widget._state.worker.is_alive()


@pytest.mark.parametrize(
    "options, message",
    [
        ({}, "exactly one"),
        ({"drive": lambda i, x: None, "operator": object()}, "exactly one"),
        ({"operator": object()}, "aliases="),
        ({"poses": {"Other": [1, 1]}}, "Fist"),
        ({"poses": {"Fist": [1]}}, "same shape"),
        ({"rest": [0]}, "same shape"),
        ({"aliases": ["only"]}, "one value per alias"),
        ({"poses": {"Fist": [[1, 1]]}}, "pose vectors"),
        ({"rest": [[0, 0]], "poses": {"Fist": [[1, 1]]}}, "pose vectors"),
        ({"poses": {"Fist": [np.nan, 1]}}, "finite pose"),
        ({"rest": [0, np.inf]}, "finite pose"),
    ],
)
def test_operator_configuration_is_validated_at_construction(options, message):
    defaults = {
        "operator": object(),
        "aliases": ("x", "y"),
        "poses": {"Fist": [1, 1]},
        "rest": [0, 0],
    }
    if not options or "operator" in options:
        defaults = {}
    with pytest.raises(ValueError, match=message):
        FollowRun(["Fist"], **(defaults | options), on_record=lambda: None, on_stop=lambda: None)


def test_operator_hold_returns_delivery_and_never_binds():
    from types import SimpleNamespace

    from myogestic.controls import Continuous, ControlBus, ControlSet

    link = SimpleNamespace(bus=None, ensure=lambda: pytest.fail("hold must never bind"))
    widget = FollowRun(
        ["Fist"],
        operator=link,
        aliases=("x", "y"),
        poses={"Fist": [1, 1]},
        rest=[0.2, -0.2],
        on_record=lambda: None,
        on_stop=lambda: None,
    )
    assert widget.hold() is None
    widget._drive(0, 0.5)  # unbound is also a no-op on the driver thread
    link.bus = ControlBus(ControlSet({"x": Continuous("x"), "y": Continuous("y")}))
    assert widget.hold([2, -2]) == {"x": 1.0, "y": -1.0}
    assert widget.hold() == {"x": 0.2, "y": -0.2}
    widget._state.phase = "running"
    assert widget.hold([1, 1]) is None


@pytest.mark.parametrize("external_stop", [False, True])
def test_operator_drives_without_prediction_and_rests_after_join(
    tmp_path, monkeypatch, external_stop
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from types import SimpleNamespace

    monkeypatch.setattr("myogestic._browser.IS_BROWSER", True)
    app = App("operator follow")
    frames, callbacks = [], []
    entered, release, stopping = Event(), Event(), Event()
    widget = None

    def push(frame):
        if not entered.is_set():
            entered.set()
            assert release.wait(3)
        frames.append(dict(frame))
        return frame

    def stop_recording():
        assert not widget._state.worker.is_alive()
        assert frames[-1] == {"x": 0.2, "y": -0.2}
        callbacks.append("stopped")
        app.stop_recording(wait=True)

    link = SimpleNamespace(bus=SimpleNamespace(push=push))
    widget = FollowRun(
        ["Fist"],
        operator=link,
        aliases=("x", "y"),
        poses={"Fist": [1, 1]},
        rest=[0.2, -0.2],
        trajectory=Sinusoid(move_s=1, lead_s=0, hold_low_s=0),
        hz=64,
        on_record=lambda: app.start_recording(str(tmp_path)),
        on_stop=stop_recording,
    )
    assert widget.start(app.ctx)
    assert entered.wait(1)
    assert widget.hold([1, 1]) is None and frames == []
    if external_stop:
        app.stop_recording(wait=True)

    def stop():
        stopping.set()
        widget.stop(app.ctx)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(stop)
        try:
            assert stopping.wait(1)
            assert not Event().wait(0.05) and not pending.done()
        finally:
            release.set()
        pending.result(timeout=3)
    assert not widget._state.worker.is_alive()
    assert frames[-1] == {"x": 0.2, "y": -0.2}
    assert len(frames) >= 2
    assert callbacks == ([] if external_stop else ["stopped"])
    assert not widget.running and not app.ctx.recording
