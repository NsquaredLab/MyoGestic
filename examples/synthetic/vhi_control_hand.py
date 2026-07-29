"""Control-hand demo: sliders → the *operator's* hand, over its own stream.

Every other VHI example drives `vhi.prediction.*` — the model's hand. This one drives
`vhi.control.pose.*`, the hand an operator poses by hand to set up a session or to show
a subject what to do. Two hands, two namespaces, two streams, one handshake.

The distinction is not cosmetic: both namespaces number their channels from 0, so a
control-pose address sent on the prediction stream would land on the *other* hand's
channel. `VhiTarget(..., stream="control_pose")` is what keeps them apart, and it also
declares the stream during negotiation, which is how the renderer knows to read its pose
from `MyoGestic_ControlPose` instead of animating its own movements.

Run with:
    uv run --extra grpc python examples/synthetic/vhi_control_hand.py

Workflow:
    1. Launch "VHI Hand" → the renderer appears
    2. Click "Connect" → the mapping resolves against what VHI says it exports
    3. Drag the sliders → the control hand follows
"""

import pathlib
import tomllib

from imgui_bundle import imgui

from myogestic import App, Fr, Grid, Px
from myogestic.controls import ControlBus, load_control_map, resolve
from myogestic.vhi import VhiTarget, virtual_hand
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

vhi_canonical = vhi.canonical_client()
bus: ControlBus | None = None

app = App("VHI control hand")

# `launchable` not `launcher`: an unlaunchable renderer must not stop this app
# from opening — a renderer that is already running needs no button.
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


def _connect() -> None:
    """Resolve the mapping once VHI is up and can say what it exports."""
    global bus
    if bus is not None:
        return
    capabilities = vhi_canonical.capabilities()
    if capabilities is None:
        app.ctx.log("VHI not reachable yet — launch it, then Connect again")
        return
    controls = resolve(CONTROL_MAP, capabilities)
    # `stream="control_pose"` is the whole point: it routes onto the control hand's
    # outlet and declares that stream, rather than the predicted hand's.
    target = VhiTarget(vhi.control_outlet(), client=vhi_canonical, stream="control_pose")
    bus = ControlBus(controls, targets=[target], hz=32)
    app.ctx.control_space = CONTROL_MAP
    app.ctx.log(f"resolved {len(controls.dofs)} control-hand controls against VHI")


@app.ui
def demo_ui(ctx):
    """Sliders, one per alias in the file."""
    with grid[0, 0]:
        logo.ui()

    with grid[1, 0]:
        processes.ui()

    with grid[2, 0]:
        panel_header("CONTROL HAND")
        if bus is None:
            if imgui.button("Connect"):
                _connect()
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
        if bus is not None:
            bus.stop()
        vhi_canonical.stop()


if __name__ == "__main__":
    main()
