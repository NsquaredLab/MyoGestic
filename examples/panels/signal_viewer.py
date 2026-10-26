"""``signal_viewer`` in isolation — a live decimated multi-channel scope.

Renders one stream's ring buffer as a min/max envelope decimated for 60
fps, with per-channel toggles, a 50/60 Hz mains-hum Notch, and optional
display filters (rectify, DC removal, RMS envelope). Fed here by an
8-channel in-process synthetic source (with a deliberate 50 Hz hum so the
Notch has something to remove) so every control works without hardware.

Click ``Edit…`` on the channel bar to open the spatial channel grid — on
desktop it opens as its own native OS window you can move beside the app.

Run with:
    uv run python examples/panels/signal_viewer.py
"""

from myogestic import App, Fr, Grid, Px, Stream
from myogestic.sources import SyntheticSource
from myogestic.widgets import AppHeader, SignalViewer

app = App("panel: signal_viewer")
header = AppHeader("SignalViewer", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))
app.streams(Stream("emg", source=SyntheticSource(n_channels=8), window_ms=2000, buffer_ms=10000))

viewer = SignalViewer("emg", selectable=True)


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
