"""``session_manager`` in isolation — browse + pick recorded sessions.

Scans a folder for recorded sessions, lets the user tick which to include
and which classes are active, and returns a ``TrainingData`` for
``@pipeline.train``. Populated here from a **temp folder** holding three
mock sessions so the picker renders non-empty.

Run with:
    uv run python examples/panels/session_manager.py
"""

import json
import tempfile
import zipfile
from pathlib import Path

from myogestic import App
from myogestic.widgets import SessionManager

CLASSES = ["Rest", "Fist"]

# Mock a few recorded sessions on disk as real ``.session.zip`` archives — the
# same format App.stop_recording writes. The picker lists everything in the
# base folder on start, and these are also selectable via "Load Files...".
_tmp = Path(tempfile.mkdtemp(prefix="panel_sessions_"))
_SESSIONS = (
    ("2026-05-01_10-00-00", "2026-05-01T10:00:00", [0, 1, 0, 1, 0]),
    ("2026-05-01_10-15-00", "2026-05-01T10:15:00", [1, 1, 0]),
    ("2026-05-02_09-30-00", "2026-05-02T09:30:00", [0, 0, 1, 1]),
)
for _name, _created, _labels in _SESSIONS:
    with zipfile.ZipFile(_tmp / f"{_name}.session.zip", "w") as _zf:
        _zf.writestr(
            "meta.json",
            json.dumps(
                {
                    "class_names": CLASSES,
                    "created": _created,
                    "streams": {"emg": {"n_channels": 8, "fs": 2000.0}},
                }
            ),
        )
        _zf.writestr("labels.json", json.dumps([{"class_index": ci} for ci in _labels]))

app = App("panel: session_manager")

manager = SessionManager(str(_tmp), class_names=CLASSES)


@app.ui
def ui(ctx):
    # Returns TrainingData; a real app assigns it to pipeline.training_data.
    manager.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
