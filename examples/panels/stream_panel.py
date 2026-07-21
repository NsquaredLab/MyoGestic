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

from _fixtures import SyntheticSource

from myogestic import App, Stream
from myogestic.widgets import StreamPanel

app = App("panel: stream_panel")
app.streams(
    Stream("emg", source=SyntheticSource(n_channels=8, require_target=True), window_ms=1000)
)

panel = StreamPanel()


@app.ui
def ui(ctx):
    panel.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
