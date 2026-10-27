"""Isometric force ramps: pick a device, follow the trapezoid, record.

Run with:
    uv run python examples/start_here/force_ramps.py
"""

from pathlib import Path

from imgui_bundle import imgui

from myogestic import App, Context, Fr, Grid, Layout, Px, Stream
from myogestic.sources import SyntheticForceSource, TargetSource
from myogestic.widgets import (
    DEFAULT_DEVICES,
    AppHeader,
    DeviceParam,
    DevicePicker,
    DeviceSpec,
    LogPanel,
    ParticipantPanel,
    RecordButton,
    SessionManager,
    SignalViewer,
    StatusBar,
    StepBar,
    TrackingTask,
)
from myogestic.widgets.common import DANGER, IDLE, SUCCESS, muted, panel_header, ui_px

WINDOW_MS = 200

app = App("MyoGestic — force ramps", require_participant=True)

emg = Stream("emg", source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS)

target = TargetSource()
target_stream = Stream("target", source=target, window_ms=WINDOW_MS)

force_stream = Stream("force", source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS)
app.streams(emg, force_stream, target_stream)
# The one exception to "nothing attaches on its own": `start_recording` sizes an
# array per *attached* stream, so a target going live at Start misses the take.
target_stream.reconnect()

layout = Layout(
    wide=Grid.areas(
        """
        header   header
        signal   step
        signal   sessions
        log      sessions
        status   status
        """,
        row_height=[Px(52), Fr(3), Fr(1), Px(110), Px(26)],
        col_width=[Fr(1), Px(400)],
        bare=("header", "status"),
    ),
    narrow=Grid.areas(
        """
        header
        signal
        step
        sessions
        log
        status
        """,
        # Keep the complete task visible. A shorter log leaves the step card
        # enough height to scroll a whole recording control into view.
        row_height=[Px(52), Px(500), Fr(3), Fr(1.5), Px(60), Px(26)],
        bare=("header", "status"),
    ),
    breakpoint=Px(1100),
)
steps = StepBar(["Connect", "Track"], widget_id="force_ramps_steps")
participant = ParticipantPanel()
header = AppHeader("Force ramps", steps=steps, participant=participant)
status = StatusBar("emg")

# A fake load cell beside the real amplifiers, so Track works with
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
    show_header=False,
    # Not a device stream — connecting one here would replace the task's output.
    exclude=("target",),
    # The picker names additional amplifiers; the app owns their geometry.
    on_add=lambda name: app.add_stream(
        Stream(name, source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS)
    ),
    on_remove=app.remove_stream,
)
log = LogPanel(title="Activity log")
# The Source panel owns connecting, so the viewer offers no button of its own —
# two controls named Connect doing different things is the confusion to avoid.
# The title carries the ‹ › arrows and names the stream showing.
viewer = SignalViewer("emg", show_connect=False, selectable=True, show_title=True)
# Shortened so the controls and the plot both fit the cell without scrolling.
tracking = TrackingTask("force", target=target, plot_height=180.0)
# Plain capture, no gesture classes. Swap in `RecordingControls` for per-class
# labels.
recording = RecordButton(
    on_record=app.start_recording,
    on_stop=app.stop_recording,
    on_discard=app.discard_recording,
    show_header=False,
)
sessions = SessionManager("sessions")


def _step_done(ctx: Context) -> list[bool]:
    """Mark connection of both devices and takes belonging to this participant."""
    return [
        all(
            (stream := ctx.streams.get(name)) is not None
            and stream.status == "connected"
            and stream.info is not None
            for name in ("emg", "force")
        ),
        bool(ctx.participant)
        and any(Path("sessions", ctx.participant).glob(f"{ctx.participant}_*")),
    ]


def track_ui(ctx: Context) -> None:
    """Record the streams together, with guidance for the synthetic transducer."""
    recording.ui(ctx)
    hints = [f"{i}. {text}" for i, text in enumerate(SYNTHETIC_FORCE.steps, start=1)]
    width = imgui.get_content_region_avail().x
    gap = imgui.get_style().item_spacing.y
    height = sum(imgui.calc_text_size(text, wrap_width=width).y + gap for text in hints)
    height += imgui.get_text_line_height() + gap
    if height + gap <= imgui.get_content_region_avail().y:
        imgui.spacing()
        imgui.text_colored(muted(), "With synthetic force")
        imgui.push_style_color(imgui.Col_.text, muted())
        for text in hints:
            imgui.text_wrapped(text)
        imgui.pop_style_color()


@app.ui
def force_ramps_ui(ctx: Context) -> None:
    done = _step_done(ctx)
    with layout["header"]:
        active = header.ui(ctx, done)
    padding = imgui.get_style().window_padding
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding.x, ui_px(4)))
    with layout["sessions"]:
        sessions.ui(participant=ctx.participant)
    with layout["step"]:
        failed = any(
            ctx.streams[name].last_error for name in ("emg", "force") if name in ctx.streams
        )
        tone = SUCCESS if done[0] else DANGER if failed else IDLE
        panel_header(steps.steps[active], status=tone if active == 0 else None)
        if active == 0:
            device.ui(ctx)
        else:
            track_ui(ctx)
    with layout["signal"]:
        if active == 0:
            viewer.ui(ctx)
        else:
            tracking.ui(ctx)
    # Plain capture runs on the acquisition threads; changing steps leaves every
    # stream attached and RecordButton's start time intact until Stop is pressed.
    with layout["log"]:
        log.ui(ctx)
    imgui.pop_style_var()
    with layout["status"]:
        status.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
