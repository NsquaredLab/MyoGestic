"""Live viewer and recorder for an OTB Sessantaquattro(+), with a UI.

Run with:
    uv run python examples/otb/sessantaquattro_app.py

Setup: the PC is the TCP server and the device dials into it. Join the device's
WiFi access point, or set this PC's IP as "Server IP address" on the
sessantaquattro's internal web page, then power the device on.

Press *Connect* once the device is reachable, set a participant in the header,
then open *Record* to capture labelled takes. ``sessantaquattro_emg.py`` is the
same acquisition without a UI.
"""

import pathlib

from imgui_bundle import imgui

from myogestic import App, Context, Fr, Grid, Layout, Px, Stream
from myogestic.sources.otb import SessantaquattroSource
from myogestic.widgets import (
    AppHeader,
    LogPanel,
    ParticipantPanel,
    RecordingControls,
    SessionManager,
    SignalViewer,
    StatusBar,
    StepBar,
    StreamPanel,
)
from myogestic.widgets.common import DANGER, IDLE, SUCCESS, muted, panel_header, ui_px

WINDOW_MS = 200
CLASSES = ["Rest", "Contract"]

# 64-ch monopolar @ 2000 Hz. The accessory-channel count is probed from the
# device's ramp counter, so this is the same for a Sessantaquattro and a +.
source = SessantaquattroSource(nch_mode=3, fs_mode=2, mode="monopolar")

app = App("Sessantaquattro — live view and recording", require_participant=True)
app.streams(
    Stream("emg", source=source, window_ms=WINDOW_MS, buffer_ms=60000)
)

layout = Layout(
    wide=Grid.areas(
        """
        header header
        signal step
        signal sessions
        log    sessions
        status status
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
        row_height=[Px(52), Fr(2), Fr(2.5), Fr(2), Px(110), Px(26)],
        bare=("header", "status"),
    ),
    breakpoint=Px(1100),
)
steps = StepBar(["Connect", "Record"], widget_id="sessantaquattro_steps")
participant = ParticipantPanel()
header = AppHeader("Sessantaquattro", steps=steps, participant=participant)
status = StatusBar("emg")

# Nothing attaches on its own: StreamPanel's connect button is what binds the
# stream to the device, and it shows the source's status and last error inline
# (an accept timeout here means the device never dialed into this PC).
streams = StreamPanel(show_header=False, widget_id="sessantaquattro_streams")
log = LogPanel(title="Activity log")
viewer = SignalViewer("emg", show_connect=False)
recording = RecordingControls(
    CLASSES,
    on_record=app.start_recording,
    on_stop=app.stop_recording,
    show_header=False,
)
sessions = SessionManager("sessions", class_names=CLASSES)


def _step_done(ctx: Context) -> list[bool]:
    """Complete steps when the device connects and the participant has takes."""
    stream = ctx.streams.get("emg")
    return [
        stream is not None and stream.status == "connected" and stream.info is not None,
        bool(ctx.participant)
        and any(pathlib.Path("sessions", ctx.participant).glob(f"{ctx.participant}_*")),
    ]


@app.ui
def sessantaquattro_ui(ctx: Context) -> None:
    done = _step_done(ctx)
    with layout["header"]:
        active = header.ui(ctx, done)
    padding = imgui.get_style().window_padding
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding.x, ui_px(4)))
    # Recording state advances once per frame, even with Connect open.
    if active != 1:
        recording.ui(ctx, visible=False)
    with layout["step"]:
        stream = ctx.streams.get("emg")
        tone = SUCCESS if done[0] else DANGER if stream is not None and stream.last_error else IDLE
        panel_header(steps.steps[active], status=tone if active == 0 else None)
        if active == 0:
            streams.ui(ctx)
            imgui.push_style_color(imgui.Col_.text, muted())
            imgui.text_wrapped(
                "Stop the recording before changing connections." if ctx.state == "recording" else
                "Join the device's WiFi or set this PC as its server, then power it on and connect."
            )
            imgui.pop_style_color()
        else:
            recording.ui(ctx)
    with layout["signal"]:
        viewer.ui(ctx)
    with layout["sessions"]:
        sessions.ui(participant=ctx.participant)
    with layout["log"]:
        log.ui(ctx)
    imgui.pop_style_var()
    with layout["status"]:
        status.ui(ctx)


def main() -> None:
    try:
        app.run()
    finally:
        # The counter makes loss measurable; a session that quietly dropped
        # half its samples is indistinguishable from a clean one otherwise.
        if source.dropped_samples:
            print(
                f"WARNING: {source.dropped_samples} samples dropped in "
                f"{source.dropout_events} gaps -- the acquisition loop fell behind."
            )


if __name__ == "__main__":
    main()
