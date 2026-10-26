"""``SimulatorControls`` with Rest/Fist presets for the synthetic EMG generator.

Run with:
    uv run python examples/panels/simulator_controls.py
"""

from imgui_bundle import imgui

from myogestic import App, Context, Fr, Grid, Px
from myogestic.widgets import AppHeader, SimulatorControls

app = App("panel: SimulatorControls")
header = AppHeader("SimulatorControls", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))
simulator = SimulatorControls([("Rest", 0.0), ("Fist", 1.0)])


@app.ui
def ui(ctx: Context) -> None:
    """Publish preset values and explain which signal they steer."""
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        simulator.ui(ctx)
        imgui.text_wrapped(
            "These presets steer the synthetic EMG generator through its EMG_Control stream. "
            "Run myogestic.tools.emg_generator to receive the control values."
        )


def main() -> None:
    """Run the standalone simulator demonstration."""
    app.run()


if __name__ == "__main__":
    main()
