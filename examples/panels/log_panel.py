"""``log_panel`` in isolation — the app-event log.

A read-only, auto-scrolling view of whatever lines have been pushed via
``ctx.log(...)`` — high-level app events (recording saved, model loaded,
stream reconnected), distinct from the pipeline's training log. Seeded here
with a few dummy lines so the panel renders non-empty.

Run with:
    uv run python examples/panels/log_panel.py
"""

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, LogPanel

app = App("panel: log_panel")
header = AppHeader("LogPanel", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))
panel = LogPanel()
_seeded = False


@app.ui
def ui(ctx):
    global _seeded
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        if not _seeded:
            for line in (
                "App started",
                "Stream 'emg' connected — 8 ch · 2048 Hz",
                "Recording started",
                "Recording saved → sessions/2026-05-01_10-00-00",
                "Model loaded ← models/rf.joblib",
            ):
                ctx.log(line)
            _seeded = True
        panel.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
