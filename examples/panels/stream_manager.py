"""``stream_manager`` in isolation — add and remove streams while the app runs.

Type a name and press **Add**: a synthetic stream appears, starts, and connects
itself. Press the bin on any row to stop and remove it. The rows show each
stream's live state — rate, channels and the age of its newest sample — so a
stream that has stopped producing is visible without opening a viewer.

The panel only *names* the stream. The app builds it, because the geometry —
window and buffer length — is the app's decision, not the panel's.

Both actions are refused while a recording is running; there is no recorder here
to demonstrate that, but `examples/start_here/force_ramps.py` has one.

Run with:
    uv run python examples/panels/stream_manager.py
"""

from myogestic import App, Stream
from myogestic.sources import SyntheticSource
from myogestic.widgets import StreamManager

app = App("panel: stream_manager")


def add(name: str) -> None:
    """Build the stream this panel asked for, and attach it straight away.

    A real app leaves connecting to a `DevicePicker`; this one connects on the
    spot so a new row immediately shows live numbers rather than "not connected".
    """
    stream = Stream(name, source=SyntheticSource(n_channels=4), window_ms=500)
    if app.add_stream(stream):
        stream.reconnect()


app.streams(Stream("emg", source=SyntheticSource(n_channels=8), window_ms=500))
manager = StreamManager(on_add=add, on_remove=app.remove_stream)


@app.ui
def ui(ctx):
    manager.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
