"""Control-hand demo: sliders → the *operator's* hand, over its own stream.

Every other VHI example drives `vhi.prediction.*` — the model's hand. This one drives
`vhi.control.pose.*`, the hand an operator poses to set up a session or to show a subject
what to do. An address is only ever a name: `…index` on the wrong namespace moves the
*other* hand and nothing reports an error. Point `controls/control_hand.toml` at
`vhi.prediction.*` and this file drives that hand instead, unchanged.

Run with:
    uv run --extra grpc python examples/synthetic/vhi_control_hand.py

Launch "VHI Hand", press Connect, then drag the sliders.
"""

import pathlib
import tomllib

from imgui_bundle import imgui

from myogestic import App, Fr, Grid, Px
from myogestic.controls import ControlLink, load_control_map
from myogestic.remote import RemoteTarget
from myogestic.vhi import virtual_hand
from myogestic.widgets import AppLogo, ProcessLauncher
from myogestic.widgets.common import panel_header

vhi = virtual_hand()

# What this app controls, declared in a file: the left side is *ours*, the right side is
# VHI's. Parsing needs no VHI; resolving does, so that waits for a connection.
CONTROL_FILE = (
    pathlib.Path(__file__).resolve().parent.parent / "controls" / "control_hand.toml"
)
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

# Current slider position per alias. Keyed by *our* names, straight from the file, so
# adding a mapping there adds a slider here and nothing else changes.
levels: dict[str, float] = dict.fromkeys(CONTROL_MAP.bindings, 0.0)

vhi_control = vhi.control_client()

app = App("VHI control hand")

# `link.bus` stays None until VHI answers with what it exports.
link = ControlLink(
    CONTROL_MAP,
    [RemoteTarget(client=vhi_control, interface=vhi)],
    ctx=app.ctx,
    hz=32,
)

# `launchable` not `launcher`: an unlaunchable target must not stop this app
# from opening — a target that is already running needs no button.
PROCESSES = vhi.launchable()
processes = ProcessLauncher(PROCESSES)
logo = AppLogo()

LOGO_CELL_W = 300
WORDMARK_ASPECT = 800 / 540
grid = Grid(
    3,
    1,
    row_height=[Px(LOGO_CELL_W / WORDMARK_ASPECT), Px(80), Fr(1)],
    col_width=[Px(LOGO_CELL_W * 1.6)],
)


@app.ui
def demo_ui(ctx):
    """Sliders, one per alias in the file."""
    with grid[0, 0]:
        logo.ui()

    with grid[1, 0]:
        processes.ui()

    with grid[2, 0]:
        panel_header("CONTROL HAND")
        bus = link.bus
        if bus is None:
            if imgui.button("Connect"):
                link.ensure()
            imgui.text_disabled("Launch VHI first — resolving needs its manifest.")
            return

        changed = False
        for alias in levels:
            edited, levels[alias] = imgui.slider_float(alias, levels[alias], 0.0, 1.0)
            changed = changed or edited
        if imgui.button("Rest"):
            levels.update(dict.fromkeys(levels, 0.0))
            changed = True
        if changed:
            bus.push(levels)


def main() -> None:
    """Run until the window closes, then release the operator's hand."""
    try:
        app.run()
    finally:
        # Rest the hand and make that frame land before the outlet's thread dies.
        link.stop()
        vhi_control.stop()


if __name__ == "__main__":
    main()
