"""``PongTask`` in isolation — a rally driven by one signed number.

In a real session that number is a decoder's output on wrist up/down. Here it is the
slider, which is the whole point: the widget reads no stream, no session and no model,
so anything that produces a float in ``[-1, +1]`` can play it.

1. Press **Serve**. Nothing moves until you do.
2. Drag **command** to put the paddle in front of the ball. Under ``control`` =
   *velocity* — the widget's default — the command is a **speed**: hold it at ``+1`` and
   the paddle climbs, let it go and the paddle stays where you left it. Under *position*
   the command **is** the height, ``+1`` at the top of the court. Velocity is why a
   decoder with only three outputs is still playable: integrating a coarse command
   reaches every height, where under position the paddle can only ever be in as many
   places as the model has numbers. What it costs is drift: the widget ignores commands
   inside a dead zone, which stops a steady bias and only slows a jittery one, so a noisy
   command still walks the paddle onto a wall. Serve puts it back at the centre.
3. Hit it off-centre. The return angle comes from *where* on the paddle it landed,
   which is the thing a graded contraction is being trained to control.
4. Press **Follow the cursor**. A ghost paddle traces a `Pursuit` — the signed, dense
   training trajectory — and your job becomes chasing it with the command while the
   rally carries on. The ghost never plays the ball; it only says where you should be.
5. Drag **opponent** to change who you are playing. ``0`` is the plain wall, which
   returns everything and can therefore never lose; above it a far paddle plays back at
   that fraction of the ball's speed, and the score splits — its points on the left of
   the halfway line, yours on the right.

Run with:
    uv run python examples/panels/pong.py
"""

import time

from imgui_bundle import imgui

from myogestic import App
from myogestic.tracking import Pursuit
from myogestic.widgets import PongTask
from myogestic.widgets.common import segmented

#: Bigger than the widget's own default: this demo is played with a mouse on a slider,
#: which is far coarser than the contraction the default is sized for.
PADDLE = 0.5
#: Short and quick — a demo nobody will sit through 58 s of. The shipped app uses
#: `Pursuit()`'s own defaults.
CURSOR = Pursuit(rest_s=1.0, hop_s=1.2, hops=16, recover_s=1.0)
#: `PongTask.control`'s two values, title-cased for the switch and lowered for it.
CONTROLS = ["Velocity", "Position"]


def _game(speed: float, control: int) -> PongTask:
    """A fresh court at this opponent speed and control mode. ``0`` means the wall."""
    # `speed or None` — the constructor rejects 0.0 on purpose, because a zero-speed
    # paddle is a paddle that never moves, which is not the same thing as no paddle.
    return PongTask(paddle_size=PADDLE, control=CONTROLS[control].lower(), opponent=speed or None)


app = App("panel: pong")
command = 0.0
opponent = 0.6
control = 0
#: When the cursor block started, on the monotonic clock, or ``None`` for no block.
#: A plain float here because the demo has no stream to record it on — the shipped app
#: runs the same `Pursuit` through a `TargetSource` so the ghost lands in the session.
started: float | None = None
pong = _game(opponent, control)


def _cursor() -> float | None:
    """Where the ghost is now, or ``None`` when no block is running.

    Also the thing that ends a block: `Pursuit` reports ``0.0`` forever past its own
    end, so a block that ran on would leave a ghost parked at centre court looking
    exactly like one that is still being followed.
    """
    global started
    if started is None:
        return None
    elapsed = time.monotonic() - started
    if elapsed >= CURSOR.total_duration:
        started = None
        return None
    return CURSOR.value_at(elapsed)


@app.ui
def ui(ctx):
    global command, opponent, control, pong, started
    _, command = imgui.slider_float("command", command, -1.0, 1.0, "%+.2f")

    changed = segmented("control", CONTROLS, control)
    if changed != control:
        control = changed
        # A new court, because `control` is a constructor argument — and because the
        # paddle's height means something different on either side of the switch.
        pong = _game(opponent, control)
    imgui.same_line()
    imgui.text_disabled("speed" if control == 0 else "height")

    _, opponent = imgui.slider_float("opponent", opponent, 0.0, 1.5, "%.2f")
    imgui.set_item_tooltip("0 = plain wall. 0.6 is a fair rally, 1.0 and up is hard.")
    # On release, not on every drag frame: `opponent` is a constructor argument, so each
    # change is a new court, and rebuilding mid-drag would sweep the ball off it once per
    # frame while the operator is still choosing.
    if imgui.is_item_deactivated_after_edit():
        pong = _game(opponent, control)

    ghost = _cursor()
    if imgui.button("Stop the cursor" if ghost is not None else "Follow the cursor"):
        started = None if ghost is not None else time.monotonic()
        ghost = _cursor()

    pong.ui(command, ghost)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
