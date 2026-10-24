"""``StepBar`` in isolation — navigate a workflow and mark steps complete.

Click any step to select it. The checkbox updates its completion check without
restricting navigation or changing the selection.

Run with:
    uv run python examples/panels/step_bar.py
"""

from imgui_bundle import imgui

from myogestic import App
from myogestic.widgets import StepBar, panel_header

app = App("panel: StepBar")
steps = StepBar(["Connect", "Record", "Train", "Drive"])
done = [True, False, False, False]


@app.ui
def ui(ctx):
    panel_header("Workflow")
    active = steps.ui(done)
    imgui.text(f"Selected step: {steps.steps[active]}")
    _, done[active] = imgui.checkbox("Step complete", done[active])


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
