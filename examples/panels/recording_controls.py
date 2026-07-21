"""``recording_controls`` in isolation — Record toggle + per-class buttons.

One button per class plus a Record/Stop toggle and an IDLE/RECORDING state
pill. Clicking a class button writes a label and fires ``on_gesture``.

Wired here to a live synthetic stream and a **throwaway temp directory**,
so Record → (click classes) → Stop performs a real recording (pill turns
RECORDING, data is captured) without leaving anything in the repo's
``sessions/``.

Run with:
    uv run python examples/panels/recording_controls.py
"""

import tempfile

from _fixtures import SyntheticSource

from myogestic import App, Stream
from myogestic.widgets import RecordingControls

CLASSES = ["Rest", "Fist", "Open", "Pinch"]
REC_DIR = tempfile.mkdtemp(prefix="panel_recording_")

app = App("panel: recording_controls")
app.streams(Stream("emg", source=SyntheticSource(n_channels=8), window_ms=250))

controls = RecordingControls(
    CLASSES,
    on_record=lambda: app.start_recording(base_path=REC_DIR),
    on_stop=app.stop_recording,
    on_gesture=lambda i: app.ctx.log(f"gesture → {CLASSES[i]}"),
)


@app.ui
def ui(ctx):
    controls.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
