"""``TrackingTask`` in isolation — follow a trapezoid with a force channel.

The transducer here is a `SyntheticForceSource`: one channel in volts, 0.30 V at rest and
2.30 V at full effort. The **effort** slider is your hand on it — nothing follows the
target on its own, because the gap between the two traces is the measurement.

1. **Stream** and **Channel** are already on ``force``; the fake load cell has one
   channel. (``target`` is the recorded trajectory, not something to select here.)
2. With **effort** at 0, **Capture** the *Zero* row, then **Capture** *MVC* and hold the
   slider at 1.0 for the three seconds it runs — the peak is what it keeps. Until both
   exist *Start* stays disabled and says why.
3. Shape the trapezoid and press **Start**. Blue is the target, orange your force in % MVC.

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
# A fake load cell, not `SyntheticSource`: fixed sine channels have no resting level to
# zero and no peak to calibrate against.
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
    # Your hand on the transducer: nothing follows the target for you.
    changed, effort = imgui.slider_float("effort", force.effort, 0.0, 1.2, "%.2f")
    if changed:
        force.effort = effort
    task.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
