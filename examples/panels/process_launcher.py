"""``process_launcher`` in isolation — start/stop external subprocesses.

Launch / stop helper processes (synthetic generator, Virtual Hand, custom
acquisition tools) from the GUI, with live per-entry state. The framework
adopts the children so they exit cleanly with the app.

Here the two entries are harmless ``sleep 60`` placeholders you can Launch
and Stop to watch the state pills change.

Run with:
    uv run python examples/panels/process_launcher.py
"""

import sys

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, ProcessLauncher

PROCESSES = [
    ("EMG Generator", [sys.executable, "-c", "import time; time.sleep(60)"]),
    ("VHI Hand", [sys.executable, "-c", "import time; time.sleep(60)"]),
]

app = App("panel: process_launcher")
header = AppHeader("ProcessLauncher", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))

launcher = ProcessLauncher(PROCESSES)


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        launcher.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
