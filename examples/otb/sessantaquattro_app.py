"""Live viewer and recorder for an OTB Sessantaquattro(+), with a UI.

Run with:
    uv run python examples/otb/sessantaquattro_app.py

Setup: the PC is the TCP server and the device dials into it. Join the device's
WiFi access point, or set this PC's IP as "Server IP address" on the
sessantaquattro's internal web page, then power the device on.

Press *Connect* once the device is reachable, then *Record* to capture a
session. ``sessantaquattro_emg.py`` is the same acquisition without a UI.
"""

from myogestic import App, Fr, Grid, Stream
from myogestic.sources.otb import SessantaquattroSource
from myogestic.widgets import (
    LogPanel,
    RecordingControls,
    SessionManager,
    SignalViewer,
    StreamPanel,
)

WINDOW_MS = 200
CLASSES = ["Rest", "Contract"]

# 64-ch monopolar @ 2000 Hz. The accessory-channel count is probed from the
# device's ramp counter, so this is the same for a Sessantaquattro and a +.
source = SessantaquattroSource(nch_mode=3, fs_mode=2, mode="monopolar")

app = App("Sessantaquattro — live view and recording", ui_scale=0.85)
app.streams(
    Stream("emg", source=source, window_ms=WINDOW_MS, buffer_ms=60000)
)

grid = Grid(6, 3, row_height=[Fr(1)] * 6, col_width=[Fr(1), Fr(1), Fr(1)])

# Nothing attaches on its own: StreamPanel's connect button is what binds the
# stream to the device, and it shows the source's status and last error inline
# (an accept timeout here means the device never dialed into this PC).
streams = StreamPanel()
log = LogPanel()
viewer = SignalViewer("emg")
recording = RecordingControls(
    CLASSES,
    on_record=app.start_recording,
    on_stop=app.stop_recording,
)
sessions = SessionManager("sessions", class_names=CLASSES)


@app.ui
def sessantaquattro_ui(ctx):
    with grid[0:4, 0:2]:
        viewer.ui(ctx)
    with grid[4:6, 0:2]:
        log.ui(ctx)
    with grid[0, 2]:
        streams.ui(ctx)
    with grid[1:3, 2]:
        recording.ui(ctx)
    with grid[3:6, 2]:
        sessions.ui()


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
