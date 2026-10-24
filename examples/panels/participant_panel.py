"""``ParticipantPanel`` in isolation — choose an ID and recognise returning names.

Click Set participant, optionally enter a name, then Start session. Reopen the
chip and type the same name to find its ID. Names are written only to the local
``~/myogestic/participant-key.csv`` key file; this example records no data.
The checkbox demonstrates why participant changes are unavailable while busy.

Run with:
    uv run python examples/panels/participant_panel.py
"""

from imgui_bundle import imgui

from myogestic import App, Context
from myogestic.widgets import ParticipantPanel, panel_header

app = App("panel: ParticipantPanel", require_participant=True)
participant = ParticipantPanel()


@app.ui
def ui(ctx: Context) -> None:
    """Draw the selector and a simulated busy state."""
    panel_header("Participant")
    participant.ui(ctx)
    imgui.text(f"Selected ID: {ctx.participant or 'none'}")
    _, busy = imgui.checkbox("Simulate recording", ctx.state != "idle")
    ctx.state = "recording" if busy else "idle"


def main() -> None:
    """Run the standalone participant selector."""
    app.run()


if __name__ == "__main__":
    main()
