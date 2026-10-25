"""``stream_panel`` in isolation — per-stream status + connect flow.

A compact "device setup" replacement: source class, connection status,
sample rate, channel count, last-sample age, plus inline Scan / Connect
buttons for whatever the source's ``discover()`` reports.

To show that flow, the synthetic source here starts with **no target**, so
the stream comes up *disconnected*. Click **Scan** → a "Synthetic EMG"
target appears → **Connect** and it starts streaming (status flips to
connected with live metadata). Reconnect while connected is available too.

Run with:
    uv run python examples/panels/stream_panel.py
"""

from myogestic import App, Fr, Grid, Px, Stream
from myogestic.sources import SyntheticSource
from myogestic.widgets import AppHeader, StreamPanel

app = App("panel: stream_panel")
header = AppHeader("StreamPanel", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))
app.streams(
    Stream("emg", source=SyntheticSource(n_channels=8, require_target=True), window_ms=1000)
)

panel = StreamPanel()


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        panel.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
