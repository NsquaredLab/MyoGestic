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
from pathlib import Path

from myogestic import App
from myogestic.widgets import SessionManager

CLASSES = ["Rest", "Fist"]

# Mock a few sessions on disk: a meta.json + empty zarr-shaped dirs is
# enough for the picker to list them.
_tmp = Path(tempfile.mkdtemp(prefix="panel_sessions_"))
for _name in ("2026-05-01_10-00-00", "2026-05-01_10-15-00", "2026-05-02_09-30-00"):
    _d = _tmp / _name
    _d.mkdir()
    (_d / "meta.json").write_text(json.dumps({"class_names": CLASSES}))
    (_d / "emg.zarr").mkdir()
    (_d / "emg_timestamps.zarr").mkdir()

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
