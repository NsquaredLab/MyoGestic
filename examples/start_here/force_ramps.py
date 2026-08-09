"""Isometric force ramps: pick a device, follow the trapezoid, record.

Run with:
    uv run python examples/start_here/force_ramps.py
"""

from imgui_bundle import imgui

from myogestic import App, Fr, Grid, Stream
from myogestic.sources import SyntheticForceSource, TargetSource
from myogestic.widgets import (
    DEFAULT_DEVICES,
    DeviceParam,
    DevicePicker,
    DeviceSpec,
    LogPanel,
    RecordButton,
    SessionManager,
    SignalViewer,
    StreamManager,
    TrackingTask,
)

WINDOW_MS = 200

app = App("MyoGestic — force ramps", ui_scale=0.85)

emg = Stream("emg", source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS)

target = TargetSource()
target_stream = Stream("target", source=target, window_ms=WINDOW_MS)

force_stream = Stream("force", source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS)
app.streams(emg, force_stream, target_stream)
# The one exception to "nothing attaches on its own": `start_recording` sizes an
# array per *attached* stream, so a target going live at Start misses the take.
target_stream.reconnect()

grid = Grid(6, 3, row_height=[Fr(1)] * 6, col_width=[Fr(1), Fr(1), Fr(1)])

# A fake load cell beside the real amplifiers, so the Force tab works with
# nothing plugged in. You are the subject: drag Effort to follow the target.
SYNTHETIC_FORCE = DeviceSpec(
    "Synthetic force (no hardware)",
    SyntheticForceSource,
    live=(
        DeviceParam("effort", "Effort", 0.0, 1.2),
        DeviceParam("noise", "Noise", 0.0, 0.2, "%.3f V"),
        DeviceParam("lag_s", "Lag", 0.0, 2.0, "%.2f s"),
    ),
    hint="A stand-in transducer: 0.30 V at rest, 2.30 V at full effort.",
    steps=(
        "Press Connect, then capture Zero with Effort left at 0.",
        "Raise Effort to full, capture MVC, and drop it back.",
        "Start a block and drag Effort to follow the target — nothing follows it for you.",
    ),
)
device = DevicePicker(
    "emg",
    devices=(*DEFAULT_DEVICES, SYNTHETIC_FORCE),
    # One picker for every stream, rather than a panel each.
    selectable=True,
    # Not a device stream — connecting one here would replace the task's output.
    exclude=("target",),
)
# Add a second amplifier while the app runs. The panel names the stream; the
# app owns its geometry.
streams = StreamManager(
    on_add=lambda name: app.add_stream(
        Stream(name, source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS)
    ),
    on_remove=app.remove_stream,
)
log = LogPanel()
# The Source panel owns connecting, so the viewer offers no button of its own —
# two controls named Connect doing different things is the confusion to avoid.
# The title stays on because it carries the ‹ › arrows and names the stream
# showing, neither of which the tab label can do.
viewer = SignalViewer("emg", show_connect=False, selectable=True, show_title=True)
# Shortened so the controls and the plot both fit the cell without scrolling.
tracking = TrackingTask("force", target=target, plot_height=180.0)
# Plain capture, no gesture classes. Swap in `RecordingControls` for per-class
# labels.
recording = RecordButton(
    on_record=app.start_recording,
    on_stop=app.stop_recording,
    on_discard=app.discard_recording,
)
sessions = SessionManager("sessions")


@app.ui
def devices_ui(ctx):
    with grid[0:5, 0:2]:
        if imgui.begin_tab_bar("signal_cell"):
            selected, _ = imgui.begin_tab_item("Signal")
            if selected:
                viewer.ui(ctx)
                imgui.end_tab_item()
            selected, _ = imgui.begin_tab_item("Force")
            if selected:
                tracking.ui(ctx)
                imgui.end_tab_item()
            imgui.end_tab_bar()
    with grid[5, 0:2]:
        log.ui(ctx)
    with grid[0:3, 2]:
        if imgui.begin_tab_bar("source_cell"):
            selected, _ = imgui.begin_tab_item("Source")
            if selected:
                device.ui(ctx)
                imgui.end_tab_item()
            selected, _ = imgui.begin_tab_item("Streams")
            if selected:
                streams.ui(ctx)
                imgui.end_tab_item()
            imgui.end_tab_bar()
    with grid[3, 2]:
        recording.ui(ctx)
    with grid[4:6, 2]:
        sessions.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
