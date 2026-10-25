"""Watch a synthetic 256-channel EMG stream in the live signal viewer.

A viewer-only app to eyeball the plot at a high channel count: since the M4
acquisition-path fix the acquire thread no longer runs the whole-buffer all-channel M4,
so the socket read is not starved at 256 channels and the stream keeps up.

Run:
    uv run python examples/synthetic/high_channel_viewer.py
then click "Start" on the "EMG Generator 256ch" entry in the launcher panel.
"""

import sys

from myogestic import App, Fr, Grid, Px, Stream
from myogestic.sources import LSLSource
from myogestic.widgets import (
    AppHeader,
    LogPanel,
    ProcessLauncher,
    SignalViewer,
    StreamPanel,
)

N_CHANNELS = 256
FS = 2048

PROCESSES = [
    (
        "EMG Generator 256ch",
        [
            sys.executable,
            "-m",
            "myogestic.tools.emg_generator",
            "--name",
            "TestEMG256",
            "--channels",
            str(N_CHANNELS),
            "--fs",
            str(FS),
            # No `--control`: this app only watches, so nothing here publishes
            # `EMG_Control` for the generator to find.
        ],
    ),
]

app = App("High-channel viewer")
app.streams(
    Stream("emg", source=LSLSource("TestEMG256"), window_ms=1000, buffer_ms=60000),
)

grid = Grid.areas(
    """
    header    header
    processes signal
    streams   signal
    log       signal
    .         signal
    .         signal
    """,
    # Leave room for the process picker, failure details and Launch again at 2x;
    # the rest goes to the panels that have content.
    row_height=[Px(52), Px(180), Fr(1), Fr(1), Fr(1), Fr(1)],
    col_width=[Px(260), Fr(1)],
    bare=("header",),
)

header = AppHeader("High-channel viewer", show_state=False)
viewer = SignalViewer("emg", selectable=True)
processes = ProcessLauncher(PROCESSES)
streams = StreamPanel()
log = LogPanel()


@app.ui
def demo_ui(ctx):
    with grid.area("header"):
        header.ui(ctx)
    with grid.area("signal"):
        viewer.ui(ctx)
    with grid.area("processes"):
        processes.ui()
    with grid.area("streams"):
        streams.ui(ctx)
    with grid.area("log"):
        log.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
