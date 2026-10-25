"""``StepBar`` in isolation — navigate a workflow and mark steps complete.

Click any step to select it. The completion chip updates its check without
restricting navigation or changing the selection.

Run with:
    uv run python examples/panels/step_bar.py
"""

from imgui_bundle import imgui

from myogestic import App, Context, Fr, Grid, Px
from myogestic.widgets import StepBar, panel_header
from myogestic.widgets.common import (
    IDLE,
    SUCCESS,
    mono_text,
    muted,
    pop_selected,
    push_selected,
    tinted_row,
)

app = App("panel: StepBar")
steps = StepBar(["Connect", "Record", "Train", "Drive"], widget_id="step_bar_demo")
done = [True, False, False, False]
layout = Grid.areas("workflow\nselection", row_height=[Px(90), Fr(1)])


@app.ui
def ui(ctx: Context) -> None:
    """Keep the navigation across the header and its demo state in a card."""
    with layout.area("workflow"):
        panel_header("Workflow")
        active = steps.ui(done)
    with layout.area("selection"):
        panel_header("Selected step")
        mono_text(steps.steps[active])
        imgui.text_colored(muted(), "Completion")
        complete = done[active]
        if complete:
            push_selected()
        if imgui.small_button("Complete"):
            done[active] = not complete
        if complete:
            pop_selected()
        with tinted_row(SUCCESS if done[active] else IDLE):
            imgui.align_text_to_frame_padding()
            imgui.text_unformatted("Complete" if done[active] else "Not complete")


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
