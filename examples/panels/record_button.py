"""``record_button`` in isolation — Record, Stop, then name the take.

The plain-recording counterpart to ``recording_controls``: no gesture classes,
just capture. Press **Record**, wait a few seconds (the pill counts up), press
**Stop** — capture ends right there — and a dialog asks what to call it. The
name lands in the session's ``meta.json`` and in the archive filename, so
**Discard** is the only way out that leaves nothing behind.

Wired to a live synthetic stream and a **throwaway temp directory**, so the
whole loop performs a real recording without leaving anything in the repo's
``sessions/``. The path is printed on start — the named ``.session.zip``
appears there when you save.

Run with:
    uv run python examples/panels/record_button.py
"""

import tempfile

from myogestic import App, Stream
from myogestic.sources import SyntheticSource
from myogestic.widgets import RecordButton, SessionManager

REC_DIR = tempfile.mkdtemp(prefix="panel_record_button_")

app = App("panel: record_button")
# Nothing attaches a stream on its own — see `Stream.reconnect`. This source is
# synthetic and in-process, so the script attaches its own.
stream = Stream("emg", source=SyntheticSource(n_channels=8), window_ms=250)
stream.reconnect()
app.streams(stream)

recorder = RecordButton(
    on_record=lambda: app.start_recording(base_path=REC_DIR),
    on_stop=app.stop_recording,
    on_discard=app.discard_recording,
)
# Here only to show that a saved name reaches the session list — the widget
# itself needs nothing but the three callbacks above.
sessions = SessionManager(REC_DIR, title="Saved takes")


@app.ui
def ui(ctx):
    recorder.ui(ctx)
    sessions.ui()


def main() -> None:
    print(f"recording into {REC_DIR}")
    app.run()


if __name__ == "__main__":
    main()
