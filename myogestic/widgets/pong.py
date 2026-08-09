"""Pong as a proportional-control drill — one signed number moves the paddle.

A rally is what graded contraction actually feels like: overshoot and the ball goes
past, hold steady and it comes back. A trapezoid rewards tracking and a gesture
classifier rewards nothing continuous at all, so this is the task that holds a subject
through the tens of minutes proportional control takes to learn.

The widget is *only* the game. It reads no stream, no session and no model — `ui` takes
the command as a plain float, so whatever produces it (a regressor, a slider, a force
channel) stays the app's business. Cueing and recording already have widgets of their
own; a second mechanism in here would be two ways to do one job.

The court is ``x`` in ``[0, 1]`` with the paddle plane at 1.0, and ``y`` in ``[-1, +1]``
with **+1 at the top** — so a command of ``+1`` is a paddle at the top and no sign flip
lives anywhere in the logic. The one screen flip is the ``at(x, y)`` closure in
`PongTask._court_ui`. The physics below is module level and imgui-free, so it is tested
as arithmetic rather than through a frame.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import (
    IDLE,
    SUCCESS,
    hairline,
    mono_text,
    muted,
    panel_header,
    primary,
)

#: How much of the ball's speed the paddle offset can put sideways. Below 1.0 by
#: construction: at exactly 1.0 an edge hit leaves ``vx == 0`` and the ball parks on
#: the paddle plane forever.
_SPIN = 0.75

#: The serve's sideways fraction of the speed. Fixed rather than random so a test can
#: assert an exact trajectory, and alternating in sign so a subject cannot learn one.
_SERVE_VY = 0.35

#: The longest single frame the game simulates. A longer gap is **clamped to this, not
#: skipped and not simulated whole**. The widget only ticks while it is rendered, so a
#: hidden tab, a collapsed cell or a GC pause delivers one enormous ``dt``, and the two
#: obvious rules both fail on it: integrating it whole throws the paddle
#: ``_PADDLE_SPEED * dt`` in a single frame — 0.70 court ``y`` at half a second, 44% of
#: its entire travel — while zeroing it *freezes the game outright* for as long as
#: frames stay that slow, ball and integrator alike, with the header still showing a
#: rally in progress and no way back. Clamping does neither. The court advances a tenth
#: of a second per frame and keeps running, in slow motion, below 10 fps; at a saturated
#: command that is 0.14 court ``y`` of paddle and 0.055 of ball, a hitch rather than a
#: teleport. The swept paddles in `_step` are the second line of defence: one is a rule,
#: the other is arithmetic that stays right if the rule moves.
_MAX_STEP_S = 0.1

#: Ball and paddle in frame heights, so both follow ``ui_scale``.
_BALL_EM = 0.16
_PADDLE_EM = 0.20

#: Court ``y`` per second at a saturated command, in ``"velocity"`` control. The court
#: is 2.0 tall, so a full contraction sweeps it in a little over a second — quicker than
#: the default ball crosses and comes back, and slow enough that a twitch is not a sweep.
_PADDLE_SPEED = 1.4

#: Width of the band around zero that drives the paddle at nothing, in ``"velocity"``
#: control. A velocity controller integrates *bias* as readily as intent: a decoder
#: resting at +0.05 is +0.05 forever, and 0.05 x 1.4 court y per second walks the paddle
#: into the ceiling in about twelve seconds while the subject holds still. 0.10 is twice
#: the resting offset a decoder trained on a rest class typically shows, and because what
#: is left is rescaled back over the full speed (see `PongTask._drive`) it costs no top
#: speed at all: the only range spent is the quietest tenth, which is spent on
#: "hold still".
#:
#: **It slows the drift, it does not stop it, and no memoryless rule could.** A
#: *constant* command inside the band integrates to exactly nothing, which is the easy
#: case and the one that is easy to test. A real decoder emits bias *plus* noise, and
#: rectifying that leaves a positive mean however narrow the band is — the band clips
#: away the half of the noise that would have cancelled the bias. Measured on this
#: widget's own `PongTask._tick` at 60 Hz, ``paddle_size=0.4`` and a bias of 0.05, over
#: five seeds: noiseless the paddle never moves; at a command sd of 0.05 it is flat
#: against the wall after 122 s, at 0.10 after 30 s. That sd is post-filter — through
#: this app's own 1€ smoother it is a raw decoder sd of about 0.2. Only a leak *bounds*
#: a drifting integrator, and a leak is the fatigue `PongTask._drive` refuses; what
#: bounds it here is the court clamp, the subject driving the paddle back off the wall,
#: and Serve recentring it for the next rally. ``control="position"`` cannot drift at
#: all and is the mode to reach for when the command is genuinely continuous.
_DEAD_ZONE = 0.10

#: Floor for a court that fills its cell. Below this the paddle is taller than the
#: half-court it defends and the game stops being playable, so a cell too short
#: overflows rather than collapsing to a sliver — `_plot.py::_MIN_PLOT_H`'s argument.
_MIN_COURT_H = 80.0


@dataclass(frozen=True)
class Ball:
    """Where the ball is and where it is going, in court coordinates.

    Parameters
    ----------
    x
        Along the court, ``0.0`` at the far wall and ``1.0`` at the paddle plane.
    y
        Across the court, ``-1.0`` at the bottom and ``+1.0`` at the top.
    vx, vy
        Velocity in court units per second.
    """

    x: float
    y: float
    vx: float
    vy: float


def _bounce(y: float, vy: float) -> tuple[float, float]:
    """Fold ``y`` back into ``[-1, +1]``, flipping ``vy`` once per wall crossed.

    Folding rather than clamping, and counting the crossings rather than testing for
    one: a single frame can legitimately cross both walls, and a clamp would leave the
    ball stuck to a wall with its velocity still pointing into it.

    Parameters
    ----------
    y
        Position across the court, possibly outside the walls.
    vy
        Velocity across the court.

    Returns
    -------
    tuple of (float, float)
        The folded position and the resulting velocity. ``abs(vy)`` is unchanged.
    """
    shifted = y + 1.0
    if int(shifted // 2.0) % 2:
        vy = -vy
    fold = shifted % 4.0
    return (4.0 - fold if fold > 2.0 else fold) - 1.0, vy


def _track(opponent_y: float, ball: Ball, dt: float, *, cap: float, half: float) -> float:
    """Move the opponent's paddle one frame, at most ``cap`` court ``y`` per second.

    It chases the ball only while the ball is coming at it and drifts back to the
    centre otherwise, which is both what a player does and what keeps it beatable: a
    paddle glued to ``ball.y`` for the whole rally is already waiting wherever the
    return goes. The cap is the only difficulty knob — a ball it cannot reach in time
    is a point, and nothing else decides that.

    Parameters
    ----------
    opponent_y
        Where its paddle is now, in court ``y``.
    ball
        The ball it is playing.
    dt
        Seconds to advance by.
    cap
        Top speed, in court ``y`` per second.
    half
        Half the paddle's height, in court ``y``.

    Returns
    -------
    float
        The new centre, clamped like the subject's so the paddle stays in the court.
    """
    target = ball.y if ball.vx < 0.0 else 0.0
    reach = cap * dt
    limit = max(1.0 - half, 0.0)
    return min(max(opponent_y + min(max(target - opponent_y, -reach), reach), -limit), limit)


def _step(
    ball: Ball,
    paddle_y: float,
    dt: float,
    *,
    half: float,
    speed: float,
    paddle_vy: float = 0.0,
    opponent_y: float | None = None,
    opponent_cap: float = 0.0,
) -> tuple[Ball, list[str], float | None]:
    """Advance the ball one frame and say everything that happened to it.

    Parameters
    ----------
    ball
        Where the ball is now.
    paddle_y
        Centre of the subject's paddle, at ``x == 1``, in court ``y``, at the *start* of
        the frame.
    dt
        Seconds to advance by.
    half
        Half a paddle's height, in court ``y``. Must be positive. Both paddles are the
        same size, so there is one of these.
    speed
        The ball's speed, preserved across every bounce — a rally that accelerated
        would end itself rather than train anything.
    paddle_vy
        How fast the subject's paddle is moving this frame, in court ``y`` per second,
        so it is swept to each crossing instant exactly as `opponent_y` is. Under
        ``control="position"`` it is ``0``: the paddle is *given* a place by the command
        and there is genuinely nothing to interpolate. Under ``control="velocity"`` it
        has a defined velocity, and adjudicating a crossing against where the paddle got
        to by the *end* of the frame makes the frame rate a difficulty knob — 1.3% of
        crossings scored the wrong way at 60 Hz, 6.0% at 10 Hz, against a swept
        reference. That is the failure `_track`'s docstring names as unacceptable,
        wearing the subject's hat.
    opponent_y
        Centre of the opponent's paddle, at ``x == 0``, at the *start* of the frame, or
        ``None`` for a plain far wall that reflects everything.
    opponent_cap
        That paddle's top tracking speed, in court ``y`` per second. Tracked in here
        rather than by the caller so it is advanced *to each crossing instant* and no
        further: adjudicate a crossing against where the paddle got to by the end of
        the frame and a long frame hands it reach its cap does not have, which makes
        the frame rate a difficulty knob (see `_track`, where the cap is meant to be
        the only one).

    Returns
    -------
    tuple of (Ball, list of str, float or None)
        The new ball; every event in the order it happened, each one of ``"hit"``,
        ``"miss"``, ``"opponent_hit"`` or ``"opponent_miss"`` — the plain names are the
        subject's plane at ``x == 1``, the prefixed ones the opponent's at ``x == 0``;
        and the opponent's paddle at the end of the frame (``None`` if there is none).
        A frame fast enough to reach a plane twice reports both crossings, so a score
        counted off this list cannot be short — either miss ends the list on the spot.
    """
    x, y, vx, vy = ball.x, ball.y, ball.vx, ball.vy
    events: list[str] = []
    # Both paddles are swept, so both need the travel elapsed inside this frame and the
    # clamp `_aim` and `_track` apply to a centre — half a paddle from each wall.
    elapsed, limit = 0.0, max(1.0 - half, 0.0)

    # Swept, and swept in a *loop*: advance to each edge the ball actually reaches
    # inside this frame and resolve it there. Testing where the ball ended up lets one
    # long frame carry it clean through a paddle it was aimed at; testing only the
    # first crossing does the same to the second one, which a fast ball reaches in the
    # same frame. Looping makes "the paddle is tested at every crossing" structural
    # rather than a consequence of `_MAX_STEP_S` being small and `ball_speed` modest
    # — and `ball_speed` is a public argument with no upper bound.
    #
    # Terminates: every iteration consumes the strictly positive time to an edge, and
    # each edge either reverses `vx` or ends the rally.
    while dt > 0.0 and vx != 0.0:
        mine = vx > 0.0  # which plane this crossing is: the subject's, or the far one
        edge = 1.0 if mine else 0.0
        travel = (edge - x) / vx
        if travel > dt:
            break
        # The opponent gets only the time that has actually passed when the ball
        # arrives, so what it can cover is `cap * travel` — the one thing difficulty
        # is supposed to be. Its own docstring's promise, made structural here.
        if opponent_y is not None:
            opponent_y = _track(
                opponent_y, Ball(x, y, vx, vy), travel, cap=opponent_cap, half=half
            )
        x, dt, elapsed = edge, dt - travel, elapsed + travel
        y, vy = _bounce(y + vy * travel, vy)
        # The subject's paddle where it actually was at this instant, not where the
        # frame left it. Motion inside a frame is linear and the clamp is monotone, so
        # this reproduces `_aim` exactly at ``elapsed == dt``.
        plane = (
            min(max(paddle_y + paddle_vy * elapsed, -limit), limit) if mine else opponent_y
        )
        if plane is None:
            vx = -vx  # a plain far wall, which has nothing to miss
            continue
        offset = (y - plane) / half
        if abs(offset) > 1.0:
            events.append("miss" if mine else "opponent_miss")
            return Ball(edge, y, vx, vy), events, opponent_y
        events.append("hit" if mine else "opponent_hit")
        # `vy` is *set* from where on the paddle the ball landed, never added to:
        # adding compounds over a rally until the ball is unplayable. `_SPIN < 1`
        # keeps `vx` away from zero, so the ball can never park on the plane.
        vy = _SPIN * speed * offset
        vx = -math.copysign(math.sqrt(max(speed * speed - vy * vy, 0.0)), vx)

    if opponent_y is not None:
        opponent_y = _track(opponent_y, Ball(x, y, vx, vy), dt, cap=opponent_cap, half=half)
    y, vy = _bounce(y + vy * dt, vy)
    return Ball(x + vx * dt, y, vx, vy), events, opponent_y


class PongTask:
    """Pong driven by one signed command — a proportional-control training game.

    Call `ui` every frame with the command, in ``[-1, +1]``. What the command *means* is
    `control`: by default it sets the paddle's **velocity**, so ``+1`` drives the paddle
    up at full speed and ``0`` holds it where it is; with ``control="position"`` the
    command is the paddle's height instead, ``+1`` at the top. Nothing moves until
    **Serve** is pressed, so a layout pass, a freshly opened tab and a subject still
    finding their range all draw a still field.

    The paddle follows the command even between rallies, which is how a subject finds
    the range of their own contraction before the ball is in play. A command that is
    not finite — a diverged model reads as ``NaN`` — leaves the paddle where it was
    rather than throwing it to an end of the court.

    Pass `ui` a `target` and the reference a subject tracks while a training block
    records is drawn for that command: a line across the court at the level, and a hollow
    bracket where a paddle obeying it would sit. The line is what you follow — the error
    is the gap between it and your bar. Generating that trajectory and recording against
    it belong to the app — see `myogestic.tracking.Pursuit` — and the widget only draws
    the number it is handed.

    Parameters
    ----------
    ball_speed
        Ball speed in court widths per second. The court is 1.0 wide, so 0.55 crosses
        it in a little under two seconds.
    paddle_size
        Paddle height as a fraction of the court, which is 2.0 tall. Bigger is easier;
        this is the difficulty knob.
    control
        What the command does to the paddle. Neither mode is the right one in general.

        ``"velocity"``, the default, integrates it: ``+1`` drives the paddle up at full
        speed, ``-1`` down, ``0`` holds. That makes a *coarse* decoder into a complete
        controller — three distinct outputs become up / hold / down, which reach every
        height in the court, where by position three outputs are three places and
        nothing in between. What it buys is paid for in drift: an integrator accumulates
        a decoder's resting bias as faithfully as its intent. `_DEAD_ZONE` cuts that
        down and is not optional, but read what it says — it *slows* the drift and
        cannot stop it, because a noisy biased command still rectifies to something
        positive. Expect a paddle that wanders onto a wall while the subject holds
        still, and expect the subject to be the one correcting it.

        ``"position"`` maps the command onto the paddle's travel, ``+1`` at the top —
        the full command range across the full travel, so no band at either end is
        unreachable and none of it is two commands deep. It cannot drift and needs no
        dead zone, which makes it the honest mode to debug a model against and the
        better one whenever the command is already continuous — a force channel, a
        slider, a regressor fit on densely covered levels. Its ceiling is that the
        paddle is exactly as smooth, and reaches exactly as many places, as the command
        does.
    opponent
        Speed factor of a paddle playing back from the far wall, or ``None`` for the
        plain wall to rally against. It is the same height as the subject's and its top
        tracking speed is ``opponent * ball_speed`` in court ``y`` per second — that one
        cap is the whole difficulty: **~0.6 is a fair rally, 1.0 and above is hard**.
        Must be positive.
    court_height
        Court height in pixels, or ``0`` or less to take the height the cell has left
        over once the Serve row is reserved — the contract `SignalViewer`'s plot height
        already uses. Either way it is floored at 80 px, below which the ball is
        smaller than the paddle is thick. The width is always whatever the cell gives.
    widget_id
        ImGui id scope. Give each instance its own when an app renders more than one:
        ImGui derives a control's identity from its label plus the enclosing scope, and
        a `Grid` cell is a single child window, so two of these in one cell would
        otherwise share every control.

    Examples
    --------
    >>> from myogestic.widgets import PongTask
    >>> pong = PongTask(paddle_size=0.5)
    >>> pong.ui(0.0)
    """

    def __init__(
        self,
        *,
        ball_speed: float = 0.55,
        paddle_size: float = 0.36,
        control: str = "velocity",
        opponent: float | None = None,
        court_height: float = 260.0,
        widget_id: str = "pong",
    ) -> None:
        if control not in ("velocity", "position"):
            raise ValueError(
                "control is 'velocity' — the command drives how fast the paddle moves, "
                "so even a three-output decoder reaches every height — or 'position', "
                "where the command is the paddle's height itself and cannot drift — not "
                f"{control!r}"
            )
        if opponent is not None and not (math.isfinite(opponent) and opponent > 0.0):
            raise ValueError(
                "opponent is a speed factor times ball_speed: pass opponent=0.6 for a "
                "fair rally, opponent=1.0 or more for a hard one, or opponent=None for "
                f"a plain wall — not {opponent!r}"
            )
        if not (math.isfinite(ball_speed) and ball_speed > 0.0):
            # Non-finite: `max(nan, 0.0)` is nan, so the game would serve a NaN ball and
            # die inside `_bounce` one frame later, naming neither the argument nor the
            # constructor that took it. Zero or negative: a sign typo used to be
            # absorbed by a `max(..., 0.0)` into a ball parked at centre court with the
            # header still showing the rally dot — a permanently dead game and no
            # complaint, where every other bad argument here is refused out loud.
            raise ValueError(
                "ball_speed is court widths per second and must be positive: pass "
                f"ball_speed=0.55 for a rally of a little under two seconds — not "
                f"{ball_speed!r}"
            )
        self._speed = ball_speed
        # Floored so the offset arithmetic in `_step` always has something to divide
        # by, and capped so a paddle cannot be taller than the court it defends.
        self._half = min(max(paddle_size, 0.02), 2.0) * 0.5
        # How far the paddle's *centre* may go: half a paddle from each wall, so a
        # saturated command covers the ceiling exactly. Fixed for the widget's life,
        # like `_half`, and read by the ghost too so the reference stays reachable.
        self._limit = max(1.0 - self._half, 0.0)
        self._control = control
        # A non-positive height is the "fill the cell" sentinel and has to survive the
        # floor, which only guards a caller who asked for a specific tiny court.
        self._court_height = (
            court_height if court_height <= 0.0 else max(court_height, _MIN_COURT_H)
        )
        self._widget_id = widget_id
        self._opponent = opponent
        self._paddle = 0.0
        self._opponent_y = 0.0
        self._ball: Ball | None = None
        self._last: float | None = None
        self._serve_sign = 1.0
        self._hits = 0
        self._misses = 0
        self._opponent_misses = 0

    # --- logic (no imgui) ----------------------------------------------------
    def _aim(self, position: float) -> None:
        """Point the paddle at ``position``, clamped so it stays inside the court.

        The clamp is on the paddle's *centre*, at half a paddle from each wall, so a
        command of ``+1`` covers the ceiling exactly — anything less would leave a
        band at each end that no contraction can reach.
        """
        if not math.isfinite(position):
            return  # a diverged model reads as NaN; keep the last good place
        self._paddle = min(max(position, -self._limit), self._limit)

    def _drive(self, command: float, dt: float) -> float:
        """Move the paddle one frame of ``dt`` seconds, however `control` says to.

        In ``"position"`` the command *is* the place — mapped onto the paddle's travel,
        so ``+1`` is the ceiling exactly — and ``dt`` is irrelevant. In ``"velocity"``
        it is a speed and this integrates it, through a dead zone that is **rescaled**
        rather than gated: ``over`` is exactly zero across the whole dead band and
        climbs back to 1.0 at a saturated command, so killing the bias costs no top
        speed and leaves no step at the threshold — a control that jumped to a tenth of
        full speed the moment it woke up would be the opposite of graded.

        There is deliberately **no leak back to centre**. A leak is the only thing that
        *bounds* a drifting integrator, and `_DEAD_ZONE` is honest about not being one —
        but a leak also makes holding a position off-centre cost a sustained
        contraction, which is the fatigue velocity control is chosen to avoid: a subject
        waiting for a ball would be contracting the whole time. What is left instead is
        the court clamp, the subject driving the paddle back off the wall, and Serve
        putting it at the centre for the next rally. The worst case is a paddle parked
        visibly against a wall, not a runaway — and a command whose noise makes that
        happen in under two minutes of holding still is a reason to reach for
        ``control="position"``, which cannot drift at all.

        Parameters
        ----------
        command
            The control signal, in ``[-1, +1]``.
        dt
            Seconds since the last rendered frame, already vetted by `_tick` — zero when
            there was no previous frame, and never longer than `_MAX_STEP_S`.

        Returns
        -------
        float
            The paddle's velocity over this frame, in court ``y`` per second, for `_step`
            to sweep it with. ``0`` in ``"position"`` control, where the paddle is placed
            rather than moved, and on a command `_aim` refused.
        """
        if self._control == "position":
            self._aim(command * self._limit)
            return 0.0
        over = max(abs(command) - _DEAD_ZONE, 0.0) / (1.0 - _DEAD_ZONE)
        # A non-finite command makes this product non-finite too, and `_aim` then keeps
        # the last good place — the same rule position mode gets, from the same line.
        moving = math.copysign(over, command) * _PADDLE_SPEED
        self._aim(self._paddle + moving * dt)
        return moving if math.isfinite(moving) else 0.0

    def _serve(self, toward: float = 1.0) -> None:
        """Put a ball at the centre of the court, heading for a paddle.

        Parameters
        ----------
        toward
            ``+1`` serves at the subject, ``-1`` at the opponent. A point is served
            back at whoever conceded it, as in real pong.
        """
        vy = self._speed * _SERVE_VY * self._serve_sign
        vx = math.sqrt(max(self._speed**2 - vy * vy, 0.0))
        self._ball = Ball(0.5, 0.0, math.copysign(vx, toward), vy)

    def _restart(self) -> None:
        """A fresh court: both paddles centred, the score cleared, a new ball served.

        **Both** paddles. Under ``"velocity"`` control a decoder's resting bias parks the
        subject's against a wall — see `_DEAD_ZONE`, which slows that and cannot stop it —
        and nothing else here puts it back, so without this a rally would start from
        wherever the previous one's drift left it, with half the court already conceded.
        ``"position"`` aims again on the very next frame, so it costs that mode nothing.
        """
        self._hits = self._misses = self._opponent_misses = 0
        self._serve_sign = 1.0
        self._paddle = self._opponent_y = 0.0
        self._serve()

    def _tick(self, now: float, command: float) -> None:
        """Drive the paddle and advance the rally by one frame.

        Parameters
        ----------
        now
            A monotonic clock reading, in seconds.
        command
            The command driving the paddle.
        """
        last, self._last = self._last, now
        # Clamped rather than skipped — see `_MAX_STEP_S`. A frame slower than that runs
        # the game in slow motion, which is a thing the subject can see and play through;
        # the two alternatives are a teleported paddle and a game frozen for good.
        dt = 0.0 if last is None else min(max(now - last, 0.0), _MAX_STEP_S)
        # Where the paddle *started*, and how fast it is going, so `_step` can adjudicate
        # a crossing against where it actually was rather than where the frame left it.
        started, paddle_vy = self._paddle, self._drive(command, dt)
        if self._ball is None or dt == 0.0:
            return

        ball, events, opponent_y = _step(
            self._ball,
            started,
            dt,
            half=self._half,
            speed=self._speed,
            paddle_vy=paddle_vy,
            opponent_y=self._opponent_y if self._opponent is not None else None,
            opponent_cap=(self._opponent or 0.0) * self._speed,
        )
        if opponent_y is not None:
            self._opponent_y = opponent_y
        # Every crossing, not just the last: a frame that returns two balls is two
        # points on the board. A point is served back at whoever conceded it; the sign
        # alternates on top of that, so the serve stays something the subject cannot
        # learn instead of the game.
        for event in events:
            if event == "miss":
                self._misses += 1
                self._serve_sign = -self._serve_sign
                self._serve()
                return
            if event == "opponent_miss":
                self._opponent_misses += 1
                self._serve_sign = -self._serve_sign
                self._serve(toward=-1.0)
                return
            if event == "hit":
                self._hits += 1
        self._ball = ball

    def _ghost_y(self, target: float | None) -> float | None:
        """Where the ghost actually draws, or ``None`` for nothing to draw.

        ``target`` is a *command*, in the same ``[-1, +1]`` as `ui`'s, and it is mapped
        onto the paddle's travel by the identical line `_drive` uses in ``"position"``
        control — so a subject sitting on the ghost has produced the command the block
        recorded, and the number the model is later fitted against is the number they
        were shown. **Scaled, not clipped.** Clipping made the top and bottom 18% of the
        command range one place: a `myogestic.tracking.Pursuit` block reaching ``±1``
        spends 7.4% of its length there, and every window in it was labelled up to 0.18
        control units away from the reference actually on the court.

        A non-finite target is dropped for the reason a non-finite command is ignored:
        whatever produced it has diverged, and drawing at ``NaN`` would put garbage on
        the court instead of saying so. The clamp that is left only catches a target
        outside ``[-1, +1]``, which is outside the contract.
        """
        if target is None or not math.isfinite(target):
            return None
        return min(max(target * self._limit, -self._limit), self._limit)

    def _detail(self, ghost: float | None) -> str:
        """The one status line, so the header dot is not the only place state lives."""
        parts = [f"paddle {self._paddle:+.2f}"]
        if ghost is not None:
            # The gap the ghost exists to show, as a number for whoever is running the
            # block: the superposition on the court says *how far off*, this says how
            # far off it is. Signed paddle-minus-ghost, so positive reads "above it".
            parts.append(f"err {self._paddle - ghost:+.2f}")
        parts.append(
            "press Serve" if self._ball is None else f"ball {self._ball.x:4.2f} {self._ball.y:+.2f}"
        )
        return " · ".join(parts)

    # --- render --------------------------------------------------------------
    def ui(self, command: float, target: float | None = None) -> None:
        """Render the game. Call once per frame.

        Parameters
        ----------
        command
            The control signal, in ``[-1, +1]``. Under ``control="velocity"`` it is the
            paddle's speed as a fraction of full; under ``control="position"`` it is the
            paddle's height, ``+1`` at the top of the court. Either way values outside
            the range saturate and a non-finite one is ignored.
        target
            The **command** the subject is being asked to produce, in the same
            ``[-1, +1]`` as `command` and typically `myogestic.tracking.Pursuit.value_at`
            — drawn as a ghost paddle wherever a paddle obeying it would sit, which is
            the same mapping ``control="position"`` uses. So it is the number the block
            recorded, not a court coordinate, and a subject sitting on the ghost has
            produced exactly what the recording says they were asked for. ``None``, the
            default, draws nothing and leaves the court exactly as it was. The ghost does
            not play the ball and is not a second player.
        """
        imgui.push_id(self._widget_id)
        try:
            ghost = self._ghost_y(target)
            self._tick(time.monotonic(), command)
            panel_header(
                "Pong",
                fa.ICON_FA_TABLE_TENNIS_PADDLE_BALL,
                status=SUCCESS if self._ball is not None else IDLE,
            )
            self._court_ui(ghost)
            self._controls_ui(ghost)
        finally:
            imgui.pop_id()

    def _court_ui(self, ghost: float | None) -> None:
        """The court, the paddle, the ball and the score, on one draw list."""
        dl = imgui.get_window_draw_list()
        origin = imgui.get_cursor_screen_pos()
        avail = imgui.get_content_region_avail()
        # The Serve/Stop button plus the status line under it. Measured rather than
        # hardcoded so the reservation follows `ui_scale` with everything else.
        footer = imgui.get_frame_height_with_spacing() + imgui.get_text_line_height_with_spacing()
        height = (
            self._court_height
            if self._court_height > 0.0
            else max(avail.y - footer, _MIN_COURT_H)
        )
        size = imgui.ImVec2(max(avail.x, 1.0), height)
        # An invisible button rather than a `dummy`: both reserve the rect, but `dummy`
        # registers with id 0 and cannot answer `is_item_hovered`.
        imgui.invisible_button("##pong_court", size)

        def at(x: float, y: float) -> imgui.ImVec2:
            """Court coordinates to screen. The one place ``+1`` becomes up."""
            return imgui.ImVec2(origin.x + x * size.x, origin.y + (1.0 - y) * 0.5 * size.y)

        far = imgui.ImVec2(origin.x + size.x, origin.y + size.y)
        faint = imgui.get_color_u32(hairline())
        dl.add_rect_filled(origin, far, imgui.get_color_u32(imgui.Col_.frame_bg), rounding=4.0)
        dl.add_rect(origin, far, faint, rounding=4.0, thickness=1.0)

        # The dashed halfway line, which is what makes a rectangle read as a court.
        dashes = 9
        for i in range(0, dashes, 2):
            dl.add_line(
                at(0.5, 1.0 - 2.0 * i / dashes), at(0.5, 1.0 - 2.0 * (i + 1) / dashes), faint
            )

        frame = imgui.get_frame_height()
        thick = max(frame * _PADDLE_EM, 3.0)

        if self._opponent is not None:
            # Muted, not primary: the accent belongs to the paddle the subject drives.
            head = at(0.0, self._opponent_y + self._half)
            foot = at(0.0, self._opponent_y - self._half)
            dl.add_rect_filled(
                head,
                imgui.ImVec2(foot.x + thick, foot.y),
                imgui.get_color_u32(muted()),
                rounding=thick * 0.5,
            )

        top, bottom = at(1.0, self._paddle + self._half), at(1.0, self._paddle - self._half)
        dl.add_rect_filled(
            imgui.ImVec2(top.x - thick, top.y),
            imgui.ImVec2(bottom.x, bottom.y),
            imgui.get_color_u32(primary()),
            rounding=thick * 0.5,
        )

        if ghost is not None:
            # A reference, not a player: the paddle's own geometry so the two share one
            # mental model, hollow and in the secondary tone so it can never be mistaken
            # for something that plays the ball.
            #
            # Drawn *after* the paddle and a few pixels outside it, which is not cosmetic.
            # The obvious version — same rect, drawn first — makes the outline vanish
            # under the fill when the subject is on target, and that reads as elegant
            # until you use it: a block opens with `Pursuit.rest_s` seconds at exactly
            # 0.0, a velocity-mode paddle also starts at 0.0, so the first thing the
            # subject sees on pressing Start is *nothing at all* for five seconds. An
            # absent reference and a perfectly tracked one must not look the same. Now
            # the fill nests inside the outline, which says "on it" just as clearly and
            # is always visible. The right edge stays on the plane so the bracket cannot
            # spill outside the court.
            pad = max(3.0, thick * 0.4)
            tone = imgui.get_color_u32(muted())
            # The level line is what you actually track: it crosses the whole court, so it
            # is unmissable at a glance and the error reads as the gap between it and the
            # bar — where a bracket alone, a few pixels around a paddle sitting on it, is
            # something you have to hunt for.
            dl.add_line(at(0.0, ghost), at(1.0, ghost), tone)
            crown = at(1.0, ghost + self._half)
            base = at(1.0, ghost - self._half)
            dl.add_rect(
                imgui.ImVec2(crown.x - thick - pad, crown.y - pad),
                imgui.ImVec2(base.x, base.y + pad),
                tone,
                rounding=thick * 0.5,
                thickness=1.5,
            )

        if self._ball is not None:
            # The text tone, not a series colour: the ball is the one thing that must
            # stay legible against the court in either theme.
            dl.add_circle_filled(
                at(self._ball.x, self._ball.y),
                max(frame * _BALL_EM, 3.0),
                imgui.get_color_u32(imgui.Col_.text),
            )

        gap = imgui.get_style().item_spacing.x
        centre = at(0.5, 1.0)
        tone = imgui.get_color_u32(muted())
        # Each number on the side of the court it belongs to. Against the wall there is
        # no other side, so it stays the subject's own tally: returns, then misses.
        left, right = (
            (self._hits, self._misses)
            if self._opponent is None
            else (self._misses, self._opponent_misses)
        )
        one, two = str(left), str(right)
        dl.add_text(
            imgui.ImVec2(centre.x - gap - imgui.calc_text_size(one).x, centre.y + gap), tone, one
        )
        dl.add_text(imgui.ImVec2(centre.x + gap, centre.y + gap), tone, two)

    def _controls_ui(self, ghost: float | None) -> None:
        """Serve or stop, plus the state in words."""
        full = imgui.ImVec2(-1, 0)
        if self._ball is None:
            if imgui.button(f"{fa.ICON_FA_PLAY}  Serve##pong_serve", full):
                self._restart()
            imgui.set_item_tooltip("Start a rally from the centre, from a fresh score.")
        else:
            if imgui.button(f"{fa.ICON_FA_STOP}  Stop##pong_stop", full):
                self._ball = None
            imgui.set_item_tooltip("Take the ball off the court. The score stays up.")
        mono_text(self._detail(ghost), muted())


__all__ = ["Ball", "PongTask"]
