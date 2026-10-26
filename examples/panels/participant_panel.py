"""``ParticipantPanel`` in isolation — choose an ID and recognise returning names.

Click Set participant, optionally enter a name, then Start session. Reopen the
chip and type the same name to find its ID. Names are written only to the local
``~/myogestic/participant-key.csv`` key file; this example records no data.
The recording chip demonstrates why participant changes are unavailable while busy.

Run with:
    uv run python examples/panels/participant_panel.py
"""

from imgui_bundle import imgui

from myogestic import App, Context, Fr, Grid, Px
from myogestic.widgets import AppHeader, ParticipantPanel, panel_header
from myogestic.widgets.common import IDLE, WARNING, muted, pop_selected, push_selected, tinted_row

app = App("panel: ParticipantPanel", require_participant=True)
header = AppHeader("ParticipantPanel", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))
participant = ParticipantPanel()


@app.ui
def ui(ctx: Context) -> None:
    """Draw the selector and a simulated busy state."""
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        panel_header("Participant")
        participant.ui(ctx)
        imgui.text_colored(muted(), "Demo state")
        busy = ctx.state != "idle"
        if busy:
            push_selected()
        if imgui.small_button("Recording"):
            ctx.state = "idle" if busy else "recording"
        if busy:
            pop_selected()
        with tinted_row(WARNING if ctx.state != "idle" else IDLE):
            imgui.align_text_to_frame_padding()
            imgui.text_unformatted("Recording" if ctx.state != "idle" else "Idle")
        if ctx.state != "idle":
            imgui.push_style_color(imgui.Col_.text, muted())
            imgui.text_wrapped("Turn off Recording to change participant.")
            imgui.pop_style_color()


def main() -> None:
    """Run the standalone participant selector."""
    app.run()


if __name__ == "__main__":
    main()
