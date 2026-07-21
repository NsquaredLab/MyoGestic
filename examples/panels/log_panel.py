"""``log_panel`` in isolation — the app-event log.

A read-only, auto-scrolling view of whatever lines have been pushed via
``ctx.log(...)`` — high-level app events (recording saved, model loaded,
stream reconnected), distinct from the pipeline's training log. Seeded here
with a few dummy lines so the panel renders non-empty.

Run with:
    uv run python examples/panels/log_panel.py
"""

from myogestic import App
from myogestic.widgets import LogPanel

app = App("panel: log_panel")
panel = LogPanel()
_seeded = False


@app.ui
def ui(ctx):
    global _seeded
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
