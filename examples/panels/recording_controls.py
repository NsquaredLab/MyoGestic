"""``RecordingControls`` in isolation — timed takes and labelled capture.

Select a gesture, then Record: a one-second warm-up precedes a five-second
capture that stops automatically. The widget's timing controls change the
duration, warm-up or Timed / Start-stop mode; its state row shows progress.
Selecting a gesture fires ``on_gesture`` and labels the captured data.

Wired here to a live synthetic stream and a **throwaway temp directory**,
so both timed takes and manual Record → (click classes) → Stop perform real
recordings without leaving anything in the repo's ``sessions/``.

Run with:
    uv run python examples/panels/recording_controls.py
"""

import tempfile

from myogestic import App, Fr, Grid, Px, Stream
from myogestic.sources import SyntheticSource
from myogestic.widgets import AppHeader, RecordingControls

CLASSES = ["Rest", "Fist", "Open", "Pinch"]
REC_DIR = tempfile.mkdtemp(prefix="panel_recording_")

app = App("panel: recording_controls")
header = AppHeader("RecordingControls", show_state=True)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))
# Nothing attaches a stream on its own — see `Stream.reconnect`. This source is
# synthetic and in-process, so there is no other producer to pick up by mistake,
# and no operator to press the button: the script attaches its own.
stream = Stream("emg", source=SyntheticSource(n_channels=8), window_ms=250)
stream.reconnect()
app.streams(stream)

controls = RecordingControls(
    CLASSES,
    on_record=lambda: app.start_recording(base_path=REC_DIR),
    on_stop=app.stop_recording,
    on_gesture=lambda i: app.ctx.log(f"gesture → {CLASSES[i]}"),
    take_lengths=(3.0, 5.0, 10.0),
    warmups=(0.0, 1.0, 2.0),
    timed=True,
    take_length=5.0,
    warmup=1.0,
)


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        controls.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
