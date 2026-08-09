"""`PongTask` — the physics, which is the whole widget, plus one render pass.

`_bounce` and `_step` are module level and imgui-free precisely so they can be tested
as arithmetic: a rally that bounces wrong is a game the subject cannot learn from, and
nothing about it fails loudly. The render pass is one test and it is about not raising
and not corrupting the frame — the look is review.
"""

from __future__ import annotations

import math
import random
import time

import pytest
from imgui_bundle import imgui

from myogestic.widgets.pong import (
    _DEAD_ZONE,
    _MAX_STEP_S,
    _PADDLE_SPEED,
    _SPIN,
    Ball,
    PongTask,
    _bounce,
    _step,
    _track,
)


def _speed(ball: Ball) -> float:
    return math.hypot(ball.vx, ball.vy)


def _play(task: PongTask, ball: Ball, *, until: float, dt: float = 0.02) -> PongTask:
    """Run a rally on a fake clock with the subject holding still, and return the task.

    Holding still is the point: everything that happens on the far side of the court is
    then the opponent's own doing, and the only thing that differs between two of these
    is the speed cap. A command of zero is what "hold still" means in *either* control
    mode — inside the dead zone by velocity, dead centre by position.
    """
    task._ball = ball
    task._last = 0.0
    now = 0.0
    while now < until:
        now += dt
        task._tick(now, 0.0)
    return task


def test_the_ball_reflects_off_every_wall_and_keeps_its_speed():
    """A rally that gains or loses speed ends itself instead of training anything.

    Folding rather than clamping is what makes this hold: a clamped ball sits on the
    wall with its velocity still pointing into it, and the next frame clamps again.
    """
    assert _bounce(1.2, 0.5) == pytest.approx((0.8, -0.5))  # the ceiling
    assert _bounce(-1.3, -0.4) == pytest.approx((-0.7, 0.4))  # the floor
    assert _bounce(0.5, 0.4) == pytest.approx((0.5, 0.4))  # untouched in range
    # Both walls in one frame: two flips, so the direction comes back to itself.
    assert _bounce(3.5, 0.6) == pytest.approx((-0.5, 0.6))

    # A whole step over the ceiling, away from the paddle plane.
    ball, events, _ = _step(Ball(0.5, 0.9, -0.3, 0.4), 0.0, 0.5, half=0.2, speed=0.5)
    assert events == []
    assert (ball.x, ball.y) == pytest.approx((0.35, 0.9))
    assert ball.vy == pytest.approx(-0.4)
    assert _speed(ball) == pytest.approx(0.5)

    # The far wall reflects like the other two rather than losing the ball.
    ball, events, _ = _step(Ball(0.1, 0.0, -0.5, 0.0), 0.0, 0.4, half=0.2, speed=0.5)
    assert events == []
    assert ball.x == pytest.approx(0.1)
    assert ball.vx == pytest.approx(0.5)
    assert _speed(ball) == pytest.approx(0.5)


def test_the_return_angle_is_set_by_where_on_the_paddle_it_landed():
    """This is the training signal — the whole reason a rally teaches graded control.

    ``vy`` is *set* from the offset, never added to: adding compounds over a rally
    until the ball is unplayable, and the subject is then being scored on a game that
    ran away from them rather than on their contraction.
    """
    # Off-centre, high: the ball goes back up, and faster across than it came.
    ball, events, _ = _step(Ball(0.9, 0.1, 0.5, 0.0), 0.0, 0.4, half=0.2, speed=0.5)
    assert events == ["hit"]
    assert ball.vy == pytest.approx(_SPIN * 0.5 * 0.5)
    assert ball.vx < 0.0, "the ball did not turn around"
    assert _speed(ball) == pytest.approx(0.5)

    # An edge hit is the steepest return there is, and `_SPIN < 1` keeps `vx` off
    # zero — at exactly 1.0 the ball would park on the paddle plane forever.
    edge, events, _ = _step(Ball(0.9, 0.2, 0.5, 0.0), 0.0, 0.4, half=0.2, speed=0.5)
    assert events == ["hit"]
    assert edge.vy == pytest.approx(_SPIN * 0.5)
    assert edge.vx < -1e-3

    # Set, not added: this one arrives at the paddle's centre carrying a large `vy`
    # of its own (0.3 over the 0.25 s it takes to reach the plane from y=-0.075),
    # and must leave flat regardless.
    centred, events, _ = _step(Ball(0.9, -0.075, 0.4, 0.3), 0.0, 0.4, half=0.2, speed=0.5)
    assert events == ["hit"]
    assert centred.vy == pytest.approx(0.0)
    assert centred.vx == pytest.approx(-0.5)


def test_a_miss_scores_and_re_serves_from_the_centre():
    """The rally continues by itself; only Serve and Stop are the operator's."""
    task = PongTask(ball_speed=0.5, paddle_size=0.2)
    task._ball = Ball(0.96, 0.8, 0.5, 0.0)  # 0.08 s out, inside one `_MAX_STEP_S` frame
    task._paddle = -0.5
    task._last = 0.0

    task._tick(_MAX_STEP_S, -0.5)

    assert task._misses == 1
    assert task._hits == 0
    assert task._ball is not None
    assert (task._ball.x, task._ball.y) == pytest.approx((0.5, 0.0)), "not re-served from centre"
    assert _speed(task._ball) == pytest.approx(0.5)
    # Alternating, so a subject cannot learn the serve instead of the game.
    assert task._serve_sign == -1.0
    assert task._ball.vy < 0.0


def test_the_paddle_clamps_to_the_court_and_ignores_a_diverged_model():
    """A `NaN` command must leave the paddle where it was, not throw it to an end.

    A regressor that diverges emits `NaN` for as long as it takes to notice, and a
    paddle that jumps on the first one takes the game with it.
    """
    task = PongTask(paddle_size=0.4)  # half a paddle is 0.2, so the centre stops at 0.8

    task._aim(5.0)
    assert task._paddle == pytest.approx(0.8)
    task._aim(-5.0)
    assert task._paddle == pytest.approx(-0.8)

    task._aim(float("nan"))
    assert task._paddle == pytest.approx(-0.8)
    task._aim(float("inf"))
    assert task._paddle == pytest.approx(-0.8)

    task._aim(0.25)
    assert task._paddle == pytest.approx(0.25)

    # The clamp still lets the paddle cover the ceiling exactly — anything tighter
    # leaves a band at each end that no contraction can reach.
    task._aim(1.0)
    assert task._paddle + task._half == pytest.approx(1.0)


def test_a_frame_gap_is_clamped_rather_than_simulated_or_skipped():
    """Both halves of the defence, because either alone is a bug waiting.

    The rule: a gap longer than `_MAX_STEP_S` is *clamped* to it. A hidden tab or a
    collapsed cell delivers one enormous ``dt``; simulating it whole would run seconds of
    rally the subject never saw, and zeroing it — the rule this replaced — froze the game
    outright for as long as the frames stayed that slow, which is the failure below.

    The arithmetic: `_step` sweeps for the instant the ball reaches the paddle plane
    instead of sampling where it ended up, so the rule moving cannot bring tunnelling
    back.
    """
    task = PongTask(ball_speed=0.5, paddle_size=0.2)
    task._ball = Ball(0.5, 0.0, -0.5, 0.0)  # away from the paddle, so nothing is scored
    task._last = 0.0

    task._tick(100.0, 0.0)
    assert task._ball is not None
    assert task._ball.x == pytest.approx(0.5 - 0.5 * _MAX_STEP_S), (
        "a 100 s gap advanced the ball by more than one clamped step"
    )
    assert (task._hits, task._misses) == (0, 0)


def test_frames_slower_than_the_clamp_keep_the_game_running():
    """The rule this replaced zeroed `dt`, and a *sustained* slow frame then froze it.

    Every frame longer than the bar meant every frame's `dt` was zero: ball frozen,
    paddle frozen, integrator frozen, `panel_header` still showing the rally dot and the
    status line still reporting a ball on court, with no recovery path and nothing said.
    Clamping degrades to slow motion instead, which is a thing a subject can see and play
    through.
    """
    task = PongTask(ball_speed=0.5, paddle_size=0.4)
    task._last = 0.0
    task._serve()
    served = task._ball

    for frame in range(1, 21):  # 20 frames at 1.9 fps
        task._tick(frame * 0.526, 1.0)

    assert task._ball != served, "the ball never moved through twenty slow frames"
    assert task._paddle > 0.0, "a saturated command never reached the integrator"
    # ...and slow motion, not a teleport: each frame is worth `_MAX_STEP_S`, no more.
    assert task._paddle == pytest.approx(min(_PADDLE_SPEED * 20 * _MAX_STEP_S, task._limit))

    # A ball aimed straight at the paddle is a hit however long the frame was. Its
    # straight-line endpoint is nowhere near the paddle — sampling there reports a
    # miss, which is the bug this sweep exists to make impossible.
    # 100 s at 0.5 court widths per second is 25 crossings, and every one of them is
    # a return: the point is that not one of them is a miss.
    ball, events, _ = _step(Ball(0.5, 0.0, 0.4, 0.3), 0.375, 100.0, half=0.2, speed=0.5)
    assert set(events) == {"hit"}, events
    assert _speed(ball) == pytest.approx(0.5)
    endpoint, _vy = _bounce(0.0 + 0.3 * 100.0, 0.3)
    assert abs(endpoint - 0.375) > 0.2, "the endpoint happened to sit on the paddle"


def _substeps(
    ball: Ball,
    paddle_y: float,
    dt: float,
    *,
    half: float,
    speed: float,
    opponent_y: float | None = None,
    opponent_cap: float = 0.0,
):
    """The same motion integrated finely — the reference `_step` has to agree with.

    Returns the ball, every event, and where the opponent's paddle ended up, so a
    single long frame can be checked against 4000 short ones on all three.
    """
    events: list[str] = []
    for _ in range(4000):
        ball, step_events, opponent_y = _step(
            ball,
            paddle_y,
            dt / 4000.0,
            half=half,
            speed=speed,
            opponent_y=opponent_y,
            opponent_cap=opponent_cap,
        )
        events.extend(step_events)
        if events and events[-1] in ("miss", "opponent_miss"):
            break
    return ball, events, opponent_y


@pytest.mark.parametrize(
    ("ball", "expected"),
    [
        # Two crossings in one frame. Resolving only the first leaves the second
        # untested, so the return leg passes through a paddle that was not there and
        # the subject keeps a rally they had already lost.
        (Ball(0.9, 0.0, 7.0, -2.5), "miss"),
        # Starts *away* from the paddle: a test that only fires when the ball begins
        # the frame heading right never runs at all, and the whole crossing is a ghost.
        (Ball(0.1, 0.0, -5.0, 0.0), "hit"),
    ],
    ids=["returns-and-misses", "off-the-far-wall"],
)
def test_one_long_frame_lands_where_many_short_ones_do(ball: Ball, expected: str):
    """Which is the whole claim: the arithmetic holds however large `dt` is.

    `_MAX_STEP_S` bounds `dt` but not `dt x ball_speed`, and `ball_speed` is a public
    argument with no upper bound — so "one crossing per frame" would be an assumption
    about the caller, not a property of the physics. These speeds are absurd on purpose.
    """
    speed = _speed(ball)
    one, one_events, _ = _step(ball, 0.0, 0.4, half=0.18, speed=speed)
    many, events, _ = _substeps(ball, 0.0, 0.4, half=0.18, speed=speed)

    assert events and events[-1] == expected, "the reference itself moved"
    assert one_events == events
    assert (one.x, one.y, one.vx) == pytest.approx((many.x, many.y, many.vx), abs=1e-6)
    assert _speed(one) == pytest.approx(speed)


@pytest.mark.parametrize("bad", [0.0, -0.5, float("nan")], ids=["zero", "negative", "nan"])
def test_an_opponent_that_cannot_move_is_refused_rather_than_shipped(bad: float):
    """A cap of zero is a paddle that never plays, which reads as a bug in the game."""
    with pytest.raises(ValueError, match="opponent"):
        PongTask(opponent=bad)


def test_the_opponent_chases_only_while_the_ball_is_coming_at_it():
    """Which is what makes it beatable, and what makes it look like it is playing.

    A paddle glued to ``ball.y`` for the whole rally is already sitting wherever the
    return goes, so there is no shot to place — the game stops being about aim.
    """
    coming, going = Ball(0.5, 0.9, -0.5, 0.0), Ball(0.5, 0.9, 0.5, 0.0)

    assert _track(0.0, coming, 1.0, cap=0.3, half=0.1) == pytest.approx(0.3), "not capped"
    # Far enough to overshoot, but the paddle stops where it still covers the court.
    assert _track(0.0, coming, 10.0, cap=0.3, half=0.1) == pytest.approx(0.9)
    # Heading away: back toward the middle, and stopping there rather than crossing it.
    assert _track(0.5, going, 1.0, cap=0.3, half=0.1) == pytest.approx(0.2)
    assert _track(0.1, going, 10.0, cap=0.3, half=0.1) == pytest.approx(0.0)


def test_the_opponent_returns_what_its_speed_cap_reaches_and_concedes_what_it_does_not():
    """Difficulty is that one cap. Two identical rallies, one number apart.

    The ball is 1.8 s from the far wall and 0.8 of court above the paddle's rest
    position, so 0.4 (0.2 court y per second, 0.36 of travel) cannot get there and 1.5
    can. Nothing else differs, which is the claim: the cap alone decides the point.
    """
    ball = Ball(0.9, 0.8, -0.5, 0.0)
    slow = _play(PongTask(ball_speed=0.5, paddle_size=0.2, opponent=0.4), ball, until=2.0)
    fast = _play(PongTask(ball_speed=0.5, paddle_size=0.2, opponent=1.5), ball, until=2.0)

    assert (slow._opponent_misses, slow._misses) == (1, 0), "the slow paddle got there"
    assert (fast._opponent_misses, fast._misses) == (0, 0), "the fast paddle did not"
    assert fast._ball is not None and fast._ball.vx > 0.0, "the ball was not returned"
    assert _speed(fast._ball) == pytest.approx(0.5)


def test_a_point_is_scored_on_the_conceding_side_and_served_back_at_them():
    """As in real pong: whoever let it past gets the next ball.

    Serving away from the conceder would hand the point's winner the next rally too,
    and a subject who is behind never sees a ball again.
    """
    won = PongTask(ball_speed=0.5, paddle_size=0.2, opponent=0.6)
    won._opponent_y = -0.9  # nowhere near the ball, and too slow to close it
    won._ball = Ball(0.03, 0.9, -0.5, 0.0)  # 0.06 s out, inside one `_MAX_STEP_S` frame
    won._last = 0.0
    won._tick(_MAX_STEP_S, 0.0)

    assert (won._opponent_misses, won._misses) == (1, 0)
    assert won._ball is not None and won._ball.x == pytest.approx(0.5)
    assert won._ball.vx < 0.0, "the subject's point was not served back at the opponent"

    lost = PongTask(ball_speed=0.5, paddle_size=0.2, opponent=0.6)
    lost._ball = Ball(0.97, 0.9, 0.5, 0.0)
    lost._paddle = -0.5
    lost._last = 0.0
    lost._tick(_MAX_STEP_S, -0.5)

    assert (lost._misses, lost._opponent_misses) == (1, 0)
    assert lost._ball is not None and lost._ball.vx > 0.0, "not served back at the subject"


@pytest.mark.parametrize(
    ("opponent_y", "expected"),
    [
        (0.0, ["hit", "opponent_hit", "miss"]),
        (0.5, ["hit", "opponent_miss"]),
    ],
    ids=["returned-then-past-the-subject", "returned-then-past-the-opponent"],
)
def test_one_frame_reaching_both_paddles_is_resolved_at_both_in_order(
    opponent_y: float, expected: list[str]
):
    """With two planes a single frame can cross both, and the second is the one lost.

    A test that only fires when the ball *starts* the frame heading at a plane never
    runs for the return leg, so the ball passes through the paddle that was there —
    and the outcome the subject sees is the one from the crossing before it.
    """
    ball = Ball(0.9, 0.0, 6.0, 1.0)
    speed = _speed(ball)
    one, one_events, _ = _step(ball, 0.0, 0.4, half=0.18, speed=speed, opponent_y=opponent_y)
    many, events, _ = _substeps(ball, 0.0, 0.4, half=0.18, speed=speed, opponent_y=opponent_y)

    assert events == expected, "the reference itself moved"
    assert one_events == expected, "a crossing inside the frame went unreported"
    assert (one.x, one.y, one.vx) == pytest.approx((many.x, many.y, many.vx), abs=1e-6)
    assert _speed(one) == pytest.approx(speed)


def test_a_huge_frame_cannot_buy_the_opponent_a_return():
    """Both halves again, and this time it is the *opponent* they keep honest.

    Simulating a hidden tab whole would let the far paddle cross the court in one frame
    and make it unbeatable, which is the same tunnelling bug wearing the other hat:
    `_MAX_STEP_S` clamps the frame, and inside a frame the cap bounds it.
    """
    task = PongTask(ball_speed=0.5, paddle_size=0.2, opponent=0.4)
    task._ball = Ball(0.35, 0.9, -0.5, 0.0)
    task._last = 0.0
    cap = 0.4 * 0.5  # `opponent` x `ball_speed`, 0.2 court y per second

    task._tick(1000.0, 0.0)  # sixteen minutes hidden, resumed in one frame
    assert task._opponent_y == pytest.approx(cap * _MAX_STEP_S), (
        "a hidden tab bought the far paddle reach its cap does not have"
    )

    # ...and the rest of the flight is the cap too. The ball is 0.30 from the plane after
    # that first clamped step and 0.8 above the paddle, so 0.6 s of chase at 0.2 court y
    # per second leaves it 0.14 up and 0.66 short — the point is the subject's.
    now = 1000.0
    while task._opponent_misses == 0 and now < 1002.0:
        now += 0.1
        task._tick(now, 0.0)

    assert task._opponent_y == pytest.approx(0.14), "the cap did not bound the long frame"
    assert (task._opponent_misses, task._misses) == (1, 0)


@pytest.mark.parametrize("y", [0.30, 0.35, 0.39], ids=["y30", "y35", "y39"])
def test_the_opponent_is_judged_where_it_was_when_the_ball_arrived(y: float):
    """One hitch frame must not buy the far paddle a return its cap cannot reach.

    Shipped Hard settings, and the ball is 0.036 s from the far plane — 0.020 of court
    at a cap of 0.55, so `y` is out of reach and the point is the subject's. Advancing
    the paddle by the whole 0.4 s frame *before* adjudicating hands it 0.22 instead,
    which reaches, and the same rally at 60 Hz then scores the other way. `_track`'s
    contract is that the cap is the only thing deciding this; frame rate is not.
    """
    hitched = PongTask(opponent=1.0)
    hitched._ball = Ball(0.02, y, -0.55, 0.0)
    hitched._last = 0.0
    hitched._tick(0.4, 0.0)

    smooth = PongTask(opponent=1.0)
    smooth._ball = Ball(0.02, y, -0.55, 0.0)
    smooth._last = 0.0
    for frame in range(10):
        smooth._tick((frame + 1) / 60.0, 0.0)

    assert hitched._opponent_y <= 0.020 + 1e-9, "the paddle covered more than its cap allows"
    assert hitched._opponent_misses == 1, "a hitch frame bought the opponent a return"
    assert smooth._opponent_misses == 1, "the reference rally itself moved"


def test_two_returns_in_one_frame_are_two_points():
    """`_hits` is the left number on the wall-mode scoreboard, so a dropped one is a lie.

    Reachable only at a `ball_speed` that crosses the court twice inside a legal frame
    — nothing ships at that speed, but `ball_speed` is a public argument with no upper
    bound, and the sweep loop above is already written for exactly this case.
    """
    # 2.05 court widths from the first crossing to the second, so the speed that fits
    # both into one legal `_MAX_STEP_S` frame is 20.5 and up.
    one = PongTask(ball_speed=30.0, paddle_size=0.6)
    one._ball = Ball(0.95, 0.0, 30.0, 0.0)
    one._last = 0.0
    one._tick(_MAX_STEP_S, 0.0)

    fine = PongTask(ball_speed=30.0, paddle_size=0.6)
    fine._ball = Ball(0.95, 0.0, 30.0, 0.0)
    fine._last = 0.0
    for frame in range(100):
        fine._tick(_MAX_STEP_S * (frame + 1) / 100.0, 0.0)

    assert fine._hits == 2, "the reference itself moved"
    assert one._hits == fine._hits, "one long frame scored fewer returns than many short ones"


@pytest.mark.parametrize(
    ("arrival", "arriving", "swept", "naive"),
    [
        (0.01, 0.30, "miss", "end"),
        (0.01, -0.15, "hit", "end"),
        # Reordering `_step` ahead of `_drive` is not the fix — it swaps which end of the
        # frame is wrong. A crossing *late* in the frame is where that shows.
        (0.09, 0.30, "hit", "start"),
    ],
    ids=["false-hit", "false-miss", "not-just-reordered"],
)
def test_the_subjects_paddle_is_judged_where_it_was_when_the_ball_arrived(
    arrival: float, arriving: float, swept: str, naive: str
):
    """The opponent's rule, applied to the paddle that actually matters.

    `_drive` runs before `_step`, so handing `_step` ``self._paddle`` adjudicates a
    crossing against the position the paddle reached by the *end* of the frame — one it
    was never at when the ball got there. Under ``control="velocity"`` the paddle has a
    defined velocity and there is nothing to excuse that with, and the consequence is the
    one `_track`'s docstring calls unacceptable: 1.3% of crossings scored the wrong way at
    60 Hz, 6.0% at 10 Hz, in *both* directions. Each case here is a crossing where the
    swept answer and one naive one differ, with the paddle driving up at full speed.
    """
    task = PongTask(ball_speed=0.5, paddle_size=0.4)  # half 0.2, `_PADDLE_SPEED` 1.4
    task._ball = Ball(1.0 - 0.5 * arrival, arriving, 0.5, 0.0)
    task._paddle = 0.0
    task._last = 0.0

    task._tick(_MAX_STEP_S, 1.0)

    def verdict(plane: float) -> str:
        """What the rally scores with the paddle's centre at ``plane``."""
        return "miss" if abs(arriving - plane) / 0.2 > 1.0 else "hit"

    assert verdict(_PADDLE_SPEED * arrival) == swept, "the swept reference itself moved"
    guessed = 0.0 if naive == "start" else task._paddle
    assert verdict(guessed) != swept, f"the {naive}-of-frame paddle agrees here — proves nothing"
    assert ("miss" if task._misses else "hit") == swept, (
        f"scored against the {naive} of the frame rather than where the paddle was"
    )


@pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), 0.0, -0.55], ids=["nan", "inf", "zero", "negative"]
)
def test_a_ball_speed_that_cannot_produce_a_rally_is_refused(bad: float):
    """Non-finite dies in `_bounce` two calls later; a sign typo used to die silently.

    ``max(ball_speed, 0.0)`` absorbed a negative into a zero-velocity ball parked at
    centre court — a permanently dead game with the header still showing the rally dot,
    where `control` and `opponent` are both refused out loud for far less.
    """
    with pytest.raises(ValueError, match="ball_speed"):
        PongTask(ball_speed=bad)


def test_it_renders_idle_mid_rally_and_twice_in_one_cell(imgui_frame):
    """An unbalanced id stack surfaces as ``Missing PopID()`` far from its cause.

    `imgui_frame`, not `implot_frame`: this widget opens no plot, and a fixture that
    supplies contexts the widget never asks for hides the day it starts needing one.
    """
    idle = PongTask(widget_id="pong_a")
    rally = PongTask(widget_id="pong_b")
    rally._serve()
    rally._last = time.monotonic() - 0.05
    twin = PongTask(widget_id="pong_c")

    def draw() -> None:
        imgui.begin_child("cell", imgui.ImVec2(600, 700))
        idle.ui(0.0)
        rally.ui(0.4)
        twin.ui(-0.4)  # two of them in one cell, told apart only by `widget_id`
        imgui.end_child()

    imgui_frame(draw)

    assert idle._ball is None, "a still field served itself"
    assert rally._ball is not None and rally._ball.x != 0.5, "the rally did not advance"


def test_a_court_with_an_opponent_draws_it_where_it_tracked_to(imgui_frame):
    """The second paddle is drawn from widget state, which the frame is the only test of.

    Its position comes out of the physics, so the thing worth asserting after the frame
    is that the two agree: it chased the ball rather than staying at its rest position.
    """
    task = PongTask(opponent=0.6, widget_id="pong_vs")
    task._ball = Ball(0.5, 0.8, -0.4, 0.0)  # coming at it, so it has somewhere to be
    task._last = time.monotonic() - 0.05

    imgui_frame(lambda: task.ui(0.2))

    assert task._opponent_y > 0.0, "the opponent sat still through a ball aimed at it"


def test_a_court_height_of_zero_fills_the_cell(imgui_frame):
    """``court_height=0`` is the "take what is left" sentinel `SignalViewer` also uses.

    The app that matters gives this widget five grid rows, and a court pinned to its
    default left most of them dead grey below the Serve row. Measured through the
    cursor, because how much of the cell a widget consumed is the only part of "it
    fills its cell" a headless frame can see.
    """
    # One cell per frame: the fixture's window is shorter than two of them stacked,
    # and a fully clipped child lays nothing out, which reads as a court of no height.
    cell = 400.0
    spans: dict[float, float] = {}

    def draw_one(height: float) -> None:
        imgui.begin_child("cell", imgui.ImVec2(600, cell))
        top = imgui.get_cursor_screen_pos().y
        PongTask(court_height=height, widget_id="pong").ui(0.0)
        spans[height] = imgui.get_cursor_screen_pos().y - top
        imgui.end_child()

    imgui_frame(lambda: draw_one(120.0))
    imgui_frame(lambda: draw_one(0.0))

    assert spans[120.0] < cell * 0.5, "a fixed court grew to fit"
    assert spans[0.0] == pytest.approx(cell, abs=cell * 0.05), "the court left the cell empty"


# --- velocity control ---------------------------------------------------------
def _frames(task: PongTask, command: float, *, seconds: float, hz: float = 60.0) -> PongTask:
    """Hold ``command`` for ``seconds`` of steady frames on a fake clock.

    Steady on purpose: a velocity controller's paddle is the integral of the command, so
    the frame rate must not be part of the answer, and a test that fed it jitter could
    not tell a wrong gain from a wrong clock.
    """
    task._last = 0.0
    for frame in range(round(seconds * hz)):
        task._tick((frame + 1) / hz, command)
    return task


def test_velocity_integrates_the_command_and_a_resting_one_holds_the_paddle():
    """The mode's whole claim: three outputs become up / hold / down, so every height.

    Position mode can only put the paddle where the decoder has an output; integrating
    supplies the continuum in between. Holding is the half people forget — a command of
    zero must cost the subject nothing, or waiting for the ball is a contraction too.
    """
    task = PongTask(paddle_size=0.4)  # half a paddle is 0.2, so the centre stops at 0.8
    assert task._control == "velocity", "the default is not the mode the app asks for"

    _frames(task, 1.0, seconds=0.25)
    assert task._paddle == pytest.approx(_PADDLE_SPEED * 0.25, abs=1e-9), "not the full speed"

    parked = task._paddle
    _frames(task, 0.0, seconds=2.0)
    assert task._paddle == parked, "holding position cost a contraction, or leaked to centre"

    _frames(task, -1.0, seconds=0.25)
    assert task._paddle == pytest.approx(0.0, abs=1e-9), "the command's sign did not reverse it"

    # The dead zone is *rescaled*, not gated: what is left of the command still spans
    # the full speed, so a command halfway up the live range is half speed and not
    # (0.55 - 0.10) of it. A gate would also step from nothing to a tenth of full speed
    # the instant it woke up, which is the opposite of graded.
    live = _DEAD_ZONE + 0.5 * (1.0 - _DEAD_ZONE)
    half = _frames(PongTask(paddle_size=0.4), live, seconds=0.25)
    assert half._paddle == pytest.approx(_PADDLE_SPEED * 0.5 * 0.25, abs=1e-9)


def test_the_dead_zone_stops_a_constant_resting_bias_and_only_slows_a_noisy_one():
    """An integrator integrates bias as faithfully as intent — this is the mode's cost.

    A decoder that rests at +0.05 rather than 0.0 is an ordinary decoder, not a broken
    one. Without a dead zone that +0.05 is a standing order to climb, and the subject has
    to hold a counter-contraction for the whole block just to stay still.

    Both halves, because the first alone reads as "the dead zone stops drift" — which is
    what `_DEAD_ZONE` used to claim and is false of every command a real decoder emits.
    A *constant* command inside the band integrates to exactly nothing. Bias **plus
    noise** does not: rectifying it clips away the half of the noise that would have
    cancelled the bias, so what is left has a positive mean however narrow the band. No
    memoryless rule can do better, only a leak, and `_drive` gives the reason there is
    none. What bounds the paddle is the court clamp and `_restart`.
    """
    bias, block = 0.05, 30.0
    task = PongTask(paddle_size=0.4)
    _frames(task, bias, seconds=block)

    assert task._paddle == 0.0, "a resting bias walked the paddle"
    # ...and the run was long enough to have proved it: ungated, this bias covers more
    # than twice the travel the paddle has, so "it did not move" is not "it ran short".
    assert bias * _PADDLE_SPEED * block > 2.0 * task._limit, "too short a block to show drift"

    # The dead zone is not simply a paddle that never moves: just past it, it drives.
    nudged = _frames(PongTask(paddle_size=0.4), _DEAD_ZONE + 0.05, seconds=1.0)
    assert nudged._paddle > 0.0, "the dead zone swallowed a command that was above it"

    # The same bias with ordinary decoder noise on it, subject holding perfectly still:
    # flat against the ceiling inside a minute. Seeded, so this is a measurement and not
    # a coin toss.
    rng = random.Random(0)
    noisy = PongTask(paddle_size=0.4)
    noisy._last = 0.0
    for frame in range(60 * 60):
        noisy._tick((frame + 1) / 60.0, bias + rng.gauss(0.0, 0.10))
    assert noisy._paddle == pytest.approx(noisy._limit), (
        "the drift `_DEAD_ZONE` documents no longer reproduces — check the wording too"
    )


def test_serve_recentres_both_paddles_so_a_drifted_one_gets_a_fresh_rally():
    """The only way back from the wall `_DEAD_ZONE` cannot keep the paddle off.

    Nothing else recentres the subject's paddle: `_serve` deliberately does not, because
    it also runs on every point and would fight the subject mid-rally. So it is the Serve
    press — which already clears the score, the serve sign and the far paddle — and
    without it a rally starts with half the court conceded to whatever the last one's
    drift left behind.
    """
    task = PongTask(paddle_size=0.4, opponent=0.6)
    task._paddle, task._opponent_y = task._limit, -0.7
    task._hits, task._misses, task._opponent_misses = 3, 4, 5
    task._serve_sign = -1.0

    task._restart()

    assert task._paddle == 0.0, "Serve left the subject's paddle pinned where it drifted"
    assert task._opponent_y == 0.0
    assert (task._hits, task._misses, task._opponent_misses) == (0, 0, 0)
    assert task._serve_sign == 1.0
    assert task._ball is not None and (task._ball.x, task._ball.y) == pytest.approx((0.5, 0.0))

    # A point mid-rally must *not* do this — the subject keeps the paddle they earned.
    playing = PongTask(paddle_size=0.4)
    playing._paddle = 0.6
    playing._serve()
    assert playing._paddle == 0.6, "a re-serve teleported the subject's paddle to centre"


def test_the_velocity_paddle_clamps_inside_the_court():
    """Integration is unbounded; the court is not. The clamp is the only thing between.

    And it clamps where position mode does — half a paddle from the wall, so a sustained
    contraction covers the ceiling exactly rather than stopping a band short of it.
    """
    task = PongTask(paddle_size=0.4)

    _frames(task, 1.0, seconds=5.0)  # far longer than crossing the court takes
    assert task._paddle == pytest.approx(0.8), "the paddle left the court"
    assert task._paddle + task._half == pytest.approx(1.0), "a band at the ceiling is unreachable"

    _frames(task, -1.0, seconds=5.0)
    assert task._paddle == pytest.approx(-0.8), "the paddle left the court through the floor"


@pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"]
)
def test_a_non_finite_command_leaves_the_velocity_paddle_where_it_was(bad: float):
    """A diverged model emits `NaN` for as long as it takes to notice.

    Position mode already refuses to jump on one. Velocity mode must refuse to *keep*
    integrating one, which is worse: a single infinite step is the end of the game.
    """
    task = PongTask(paddle_size=0.4)
    _frames(task, 1.0, seconds=0.1)
    parked = task._paddle
    assert parked > 0.0, "the paddle never moved, so there is nothing here to preserve"

    _frames(task, bad, seconds=1.0)
    assert task._paddle == parked, "a diverged model moved the paddle"


def test_a_frame_gap_does_not_integrate_the_paddle():
    """The rule that protects the ball has to protect the integrator with it.

    A hidden tab or a collapsed cell delivers one enormous `dt`. Handing that to a
    velocity controller is a paddle flat against a wall the moment the tab comes back —
    the same tunnelling bug as the ball's, wearing the paddle's hat. And the bar it is
    held to has to be a fraction of the paddle's travel, not a fraction of a second: at
    the half-second this rule used to allow, one *legal* frame moved the paddle 0.70
    court y, 44% of everything it has, which is the very outcome the rule is for.
    """
    task = PongTask(paddle_size=0.4)
    task._last = 0.0
    task._tick(60.0, 1.0)
    step = _PADDLE_SPEED * _MAX_STEP_S
    assert task._paddle == pytest.approx(step), "a hidden tab integrated a whole minute"
    assert step < 0.1 * 2.0 * task._limit, "one frame moves the paddle a tenth of its travel"

    # ...and the clock re-anchored, so the next real frame drives normally.
    task._tick(60.02, 1.0)
    assert task._paddle == pytest.approx(step + _PADDLE_SPEED * 0.02, abs=1e-9)

    # The first frame of all has no previous one to measure against, and a monotonic
    # clock's absolute reading is minutes of uptime — integrating it is the same wall.
    fresh = PongTask(paddle_size=0.4)
    fresh._tick(1234.5, 1.0)
    assert fresh._paddle == 0.0, "the first frame integrated the clock itself"


def test_position_mode_maps_the_command_range_onto_the_paddles_travel():
    """The other mode still exists and still ignores `dt` entirely.

    It is the honest one to debug a model against, so it must not quietly acquire an
    integrator, a dead zone or a frame-rate dependence from the mode next to it. And the
    map is a **scale**, not a clip: the paddle's centre stops half a paddle from each
    wall, so mapping the command straight onto court ``y`` and clamping made every
    command from 0.82 up one single place — the top and bottom 18% of the range dead,
    which is the same complaint `_aim`'s docstring makes about the court's own ends.
    """
    task = PongTask(paddle_size=0.4, control="position")  # half 0.2, so travel is ±0.8
    task._last = 0.0

    task._tick(1.0 / 60.0, 0.5)
    assert task._paddle == pytest.approx(0.5 * 0.8), "position mode integrated instead of aiming"
    task._tick(2.0 / 60.0, -0.3)
    assert task._paddle == pytest.approx(-0.3 * 0.8), "the paddle did not follow the command down"

    # Small commands are places, not noise: nothing here has a dead zone.
    task._tick(3.0 / 60.0, 0.5 * _DEAD_ZONE)
    assert task._paddle == pytest.approx(0.5 * _DEAD_ZONE * 0.8), "position mode grew a dead zone"

    # `dt` is irrelevant to it, so a clamped frame still aims — only the ball is limited
    # to one step across a gap.
    task._tick(3.0 / 60.0 + 30.0, 0.7)
    assert task._paddle == pytest.approx(0.7 * 0.8), "a long frame stopped the paddle aiming"

    # Every command is its own place, right up to the ends: no band of the range is dead.
    assert task._limit == pytest.approx(0.8)
    ends = []
    for command in (0.85, 0.90, 0.95, 1.0):
        task._tick(1.0, command)
        ends.append(task._paddle)
    assert ends == sorted(ends) and len(set(ends)) == 4, f"the top of the range collapsed: {ends}"
    assert ends[-1] == pytest.approx(0.8), "a saturated command did not cover the ceiling"

    # Including the very first frame, which has no previous one to measure against.
    fresh = PongTask(paddle_size=0.4, control="position")
    fresh._tick(1234.5, -0.6)
    assert fresh._paddle == pytest.approx(-0.6 * 0.8), "the first frame did not aim"
    fresh._tick(1234.52, 5.0)
    assert fresh._paddle == pytest.approx(0.8), "position mode stopped clamping out of contract"


@pytest.mark.parametrize(
    "bad", ["speed", "Velocity", "", None], ids=["speed", "case", "empty", "none"]
)
def test_an_unknown_control_mode_is_refused_and_names_the_two_that_exist(bad: object):
    """A typo that silently picked a mode is a block recorded under the wrong task."""
    with pytest.raises(ValueError, match="velocity.*position"):
        PongTask(control=bad)  # type: ignore


# --- the pursuit ghost --------------------------------------------------------
def test_the_ghost_is_the_command_mapped_onto_the_paddles_travel():
    """The ghost and a position-mode paddle must be the *same* map, or the label is wrong.

    `Pursuit` is signed ``[-1, +1]`` and the paddle's centre stops half a paddle short of
    each wall, so the ends of a trajectory are exactly where this matters. Clipping the
    ghost there put the reference and the recorded level up to 0.18 control units apart —
    7.4% of a default `Pursuit()` block, all of it at the extremes, which is where a
    proportional decoder's gain is set. A subject on the ghost has now produced the
    number the session recorded, at every level.
    """
    task = PongTask(paddle_size=0.4)  # half a paddle is 0.2, so the centre stops at 0.8
    aiming = PongTask(paddle_size=0.4, control="position")
    aiming._last = 0.0

    assert task._ghost_y(1.0) == pytest.approx(0.8), "a full deflection did not reach the ceiling"
    assert task._ghost_y(-1.0) == pytest.approx(-0.8)
    assert task._ghost_y(0.25) == pytest.approx(0.25 * 0.8)
    assert task._ghost_y(None) is None
    assert task._ghost_y(float("nan")) is None, "a diverged trajectory drew at NaN"

    for i, level in enumerate((-1.0, -0.9, -0.5, 0.0, 0.5, 0.9, 1.0)):
        aiming._tick(float(i + 1), level)
        assert aiming._paddle == pytest.approx(task._ghost_y(level)), (
            f"tracking the ghost at {level} does not mean emitting {level}"
        )


def test_the_tracking_error_joins_the_status_line_only_when_there_is_a_ghost():
    """The gap is the feedback; the number is for whoever is running the block.

    It rides the line that already exists rather than adding anything to the court, so
    the default read-out is unchanged to the character.
    """
    task = PongTask(paddle_size=0.4)
    task._paddle = 0.5

    assert task._detail(None) == "paddle +0.50 · press Serve"
    assert task._detail(0.2) == "paddle +0.50 · err +0.30 · press Serve"
    assert task._detail(0.8) == "paddle +0.50 · err -0.30 · press Serve", "the sign is inverted"


def test_the_ghost_marks_the_court_only_when_a_target_is_given(imgui_frame):
    """Drawn straight through `_court_ui`, so the status line's `err` cannot fake it.

    Counting the draw list is the only thing a headless frame can see of "something was
    drawn". Comparing whole `ui` passes would count the extra `err` text as well, and
    the test would pass with the marker deleted.
    """
    drawn: dict[str, int] = {}

    def draw_one(key: str, ghost: float | None) -> None:
        imgui.begin_child("cell", imgui.ImVec2(600, 400))
        before = imgui.get_window_draw_list().vtx_buffer.size()
        PongTask(widget_id="pong")._court_ui(ghost)
        drawn[key] = imgui.get_window_draw_list().vtx_buffer.size() - before
        imgui.end_child()

    imgui_frame(lambda: draw_one("bare", None))
    imgui_frame(lambda: draw_one("ghost", 0.5))

    assert drawn["bare"] > 0, "the court itself drew nothing; the count means nothing"
    assert drawn["ghost"] > drawn["bare"], "the target put no marker on the court"


def test_a_ghost_renders_through_the_public_call_and_leaves_the_id_stack_alone(imgui_frame):
    """An unbalanced id stack surfaces as ``Missing PopID()`` far from its cause.

    The optional argument is the new way in, so it gets the same frame the widget's own
    render pass gets — and the id probe pins the balance to *this* call rather than to
    whatever `end_frame` happens to notice.
    """
    task = PongTask(widget_id="pong_ghost")
    probes: list[int] = []

    def draw() -> None:
        imgui.begin_child("cell", imgui.ImVec2(600, 700))
        probes.append(imgui.get_id("probe"))
        task.ui(0.0, 0.6)
        probes.append(imgui.get_id("probe"))
        task.ui(0.0)  # and back to no ghost, on the same widget, without complaint
        probes.append(imgui.get_id("probe"))
        imgui.end_child()

    imgui_frame(draw)

    assert len(set(probes)) == 1, "the ghost left the id stack pushed"
