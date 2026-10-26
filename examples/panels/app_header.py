"""AppHeader with a workflow and as a simple viewer header, in bare Grid rows.

Resize the window to see titles and participant details yield to navigation and
state. Click a step or the participant chip to use the same controls as Myocontrol.

Run with:
    uv run python examples/panels/app_header.py
"""

from imgui_bundle import imgui

from myogestic import App, Context, Fr, Grid, Px
from myogestic.widgets import AppHeader, ParticipantPanel, StepBar
from myogestic.widgets.common import muted, panel_header

app = App("panel: AppHeader")
grid = Grid.areas(
    "workflow\nviewer\nbody",
    row_height=[Px(52), Px(52), Fr(1)],
    bare=("workflow", "viewer"),
)
steps = StepBar(["Connect", "Record", "Train", "Drive"], widget_id="demo-steps")
workflow = AppHeader(
    "Myocontrol", steps=steps, participant=ParticipantPanel(), widget_id="workflow-header",
)
viewer = AppHeader("Signal acquisition and analysis viewer", widget_id="viewer-header")
done = [True, False, False, False]


@app.ui
def ui(ctx: Context) -> None:
    with grid.area("workflow"):
        active = workflow.ui(ctx, done)
    with grid.area("viewer"):
        viewer.ui(ctx)
    with grid.area("body"):
        panel_header("App headers")
        imgui.text_colored(muted(), f"Selected step: {steps.steps[active]}")
        imgui.text_wrapped("Resize the window to see the title shorten. Hover over it to read the full title.")


def main() -> None:
    """Run the standalone header demonstration."""
    app.run()


if __name__ == "__main__":
    main()
