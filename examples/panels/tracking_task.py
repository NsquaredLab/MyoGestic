"""``TrackingTask`` in isolation — follow a trapezoid with a force channel.

The real thing reads a force transducer on an auxiliary channel. Here that transducer is
a `SyntheticForceSource`: one channel, in volts, reading 0.30 V at rest and 2.30 V at
full effort. The **effort** slider at the top of the window is your hand on it — nothing
follows the target on its own, because the gap between the two traces is the whole
measurement.

1. **Stream** and **Channel** are already on ``force``; the fake load cell has the one
   channel, so there is nothing to pick. (``target`` is the second registered stream —
   it is the trajectory being recorded, not something to select here.)
2. With **effort** at 0, press **Capture** on the *Zero* row: that reads the 0.30 V
   offset. Then press **Capture** on the *MVC* row and hold the slider at 1.0 for the
   three seconds it runs — the peak is what it keeps. Until both exist *Start* stays
   disabled and says why.
3. Shape the trapezoid — every segment, the level, the repetition count — and press
   **Start**. The blue line is the target and the orange one is your force in % MVC, so
   drag the slider to chase it.

Run with:
    uv run python examples/panels/tracking_task.py
"""

from imgui_bundle import imgui

from myogestic import App, Stream
from myogestic.sources import SyntheticForceSource, TargetSource
from myogestic.tracking import Trapezoid
from myogestic.widgets import TrackingTask

TRAPEZOID = Trapezoid(rest_s=2.0, ramp_up_s=3.0, hold_s=5.0, ramp_down_s=3.0, recover_s=2.0)

app = App("panel: tracking_task")
# A fake load cell rather than `SyntheticSource`: its channels are fixed sine
# waves, so there would be no resting level to zero and no peak to calibrate
# against. This one reads 0.30 V at rest and 2.30 V at full effort, so the
# calibration does real work. You are the subject — the slider below is your
# hand, and nothing follows the target on its own.
target = TargetSource(trajectory=TRAPEZOID)
force = SyntheticForceSource()
app.streams(
    Stream("force", source=force, window_ms=1000),
    Stream("target", source=target, window_ms=1000),
)
for stream in app.ctx.streams.values():
    stream.reconnect()  # software, not hardware: nothing to plug in

task = TrackingTask("force", target=target, trapezoid=TRAPEZOID)


@app.ui
def ui(ctx):
    # Your hand on the transducer. Raise it to capture an MVC, then drag it to
    # follow the target once a block is running — that tracking is the thing the
    # plot measures, so nothing does it for you.
    changed, effort = imgui.slider_float("effort", force.effort, 0.0, 1.2, "%.2f")
    if changed:
        force.effort = effort
    task.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
