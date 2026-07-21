"""Watch a synthetic 256-channel EMG stream in the live signal viewer.

A minimal viewer-only app to eyeball the plot at a high channel count. Useful for feeling
the M4 acquisition-path fix: with the fix, the acquire thread never runs the whole-buffer
all-channel M4, so the socket read is not starved at 256 channels and the stream keeps up.

Run:
    uv run python examples/synthetic/high_channel_viewer.py
then click "Start" on the "EMG Generator 256ch" entry in the launcher panel.

To feel the before/after, run this same script on `feat/otb-device-sources` (M4 on the
acquire thread) versus the perf branch and compare how well the stream keeps up.
"""

import sys

from myogestic import App, Fr, Grid, Px, Stream
from myogestic.sources import LSLSource
from myogestic.widgets import (
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
            "--control",
            "EMG_Control",
        ],
    ),
]

app = App("High-channel viewer", ui_scale=0.85)
app.streams(
    Stream("emg", source=LSLSource("TestEMG256"), window_ms=1000, buffer_ms=60000),
)

grid = Grid(
    5,
    2,
    row_height=[Fr(1)] * 5,
    col_width=[Px(260), Fr(1)],
)

viewer = SignalViewer("emg", selectable=True)
processes = ProcessLauncher(PROCESSES)
streams = StreamPanel()
log = LogPanel()


@app.ui
def demo_ui(ctx):
    with grid[0:5, 1]:
        viewer.ui(ctx)
    with grid[0, 0]:
        processes.ui()
    with grid[1, 0]:
        streams.ui(ctx)
    with grid[2, 0]:
        log.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
