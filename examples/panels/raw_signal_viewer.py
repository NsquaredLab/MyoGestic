"""``raw_signal_viewer`` in isolation — every sample, no decimation.

The zero-decimation counterpart to ``signal_viewer``: it plots every
sample exactly, for debugging glitches, validating timestamps, or
sanity-checking acquisition. Best kept to a few channels / short windows;
fed here by a 4-channel synthetic source.

Run with:
    uv run python examples/panels/raw_signal_viewer.py
"""

from myogestic import App, Fr, Grid, Px, Stream
from myogestic.sources import SyntheticSource
from myogestic.widgets import AppHeader, RawSignalViewer

app = App("panel: raw_signal_viewer")
header = AppHeader("RawSignalViewer", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))
# Nothing attaches a stream on its own — see `Stream.reconnect`. This source is
# synthetic and in-process, so there is no other producer to pick up by mistake,
# and no operator to press the button: the script attaches its own.
stream = Stream("emg", source=SyntheticSource(n_channels=4), window_ms=1000, buffer_ms=5000)
stream.reconnect()
app.streams(stream)

viewer = RawSignalViewer("emg")


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        viewer.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
