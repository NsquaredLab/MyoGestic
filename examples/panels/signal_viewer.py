"""``signal_viewer`` in isolation — a live decimated multi-channel scope.

Renders one stream's ring buffer as a min/max envelope decimated for 60
fps, with per-channel toggles and optional display filters (rectify, DC
removal, RMS envelope). Fed here by an 8-channel in-process synthetic
source so the traces scroll and every control works without hardware.

Run with:
    uv run python examples/panels/signal_viewer.py
"""

from _fixtures import SyntheticSource

from myogestic import App, Stream
from myogestic.widgets import SignalViewer

app = App("panel: signal_viewer")
app.streams(Stream("emg", source=SyntheticSource(n_channels=8), window_ms=2000, buffer_ms=10000))

viewer = SignalViewer("emg", selectable=True)


@app.ui
def ui(ctx):
    viewer.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
