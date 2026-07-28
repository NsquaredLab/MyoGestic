"""VHI 2 playground — a slider per control, and an editor for the file behind them.

The shortest path from a TOML control map to a hand that moves. No model, no EMG, no
training: one slider per name in the file, sent straight through a `VhiTarget` to VHI's
**predicted** hand.

Run with:
    uv run --extra grpc python examples/synthetic/vhi_playground.py

Workflow:
    1. Launch "VHI Hand" → the renderer appears
    2. Click "Connect" → the file resolves against what VHI says it exports
    3. Drag a slider → that hand moves

Then try changing something. `examples/controls/playground.toml` maps a name of yours
onto a control VHI declares; `close` fans out to all five digits with the thumb at 0.6.
Edit the weight in the file and press **Reload**, or use the editor panel and press
**Save** — the file is the source of truth either way, and the sliders rebuild from it.

Needs a VHI 2.x build. A pre-2.0 renderer has no manifest to resolve against and is
refused with the upgrade command rather than driven on a guess.
"""

import pathlib
import tomllib

from imgui_bundle import imgui

from myogestic import App, Fr, Grid, Px
from myogestic.controls import ControlBus, load_control_map, resolve
from myogestic.vhi import VhiTarget, virtual_hand
from myogestic.widgets import AppLogo, ControlMapEditor, ProcessLauncher
from myogestic.widgets.common import DANGER, SUCCESS, muted, panel_header

CONTROL_FILE = (
    pathlib.Path(__file__).resolve().parent.parent / "controls" / "playground.toml"
)

vhi = virtual_hand()
vhi_outlet = vhi.outlet()
vhi_canonical = vhi.canonical_client()

app = App("VHI 2 playground")

# Everything below is rebuilt whenever the file changes, so none of it can be module
# state: `levels` has one entry per alias *in the file*, and the bus is resolved against
# the manifest, which needs VHI up.
levels: dict[str, float] = {}
bus: ControlBus | None = None
status = "Launch VHI, then press Connect."
failure = ""

editor = ControlMapEditor(CONTROL_FILE, client=vhi_canonical, title="EDIT THE MAP")
processes = ProcessLauncher([*vhi.launcher()])
logo = AppLogo()

LOGO_CELL_W = 260
WORDMARK_ASPECT = 800 / 540
grid = Grid(
    3,
    2,
    row_height=[Px(LOGO_CELL_W / WORDMARK_ASPECT), Px(90), Fr(1)],
    col_width=[Fr(1), Fr(1)],
)


def _connect() -> None:
    """(Re)read the file and resolve it against whatever VHI currently exports.

    Called from a button, never from a render or predict path: `capabilities()` blocks
    on an RPC. Rebuilding from scratch each time is deliberate — a stale slider for an
    alias that no longer exists would send a value nothing reads.
    """
    global bus, levels, status, failure
    failure = ""
    if bus is not None:
        bus.stop()
        bus = None
    with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
        control_map = load_control_map(tomllib.load(handle))
    capabilities = vhi_canonical.capabilities()
    if capabilities is None:
        status = "VHI has not answered. Launch it, then Connect again."
        return
    try:
        controls = resolve(control_map, capabilities)
        target = VhiTarget(vhi_outlet, client=vhi_canonical)
        new_bus = ControlBus(controls, targets=[target], hz=32)
        # Constructing the bus binds the target, which negotiates — but VHI may have
        # come up between the two, so settle it explicitly rather than on the next tick.
        target.negotiate()
    except ValueError as exc:
        # A refusal is the useful case: it names the address it could not place, or the
        # two aliases aiming at one control. Show it instead of leaving a dead slider.
        failure = str(exc)
        status = "That map cannot be rendered by this VHI."
        return
    bus = new_bus
    levels = dict.fromkeys(controls.dofs, 0.0)
    app.ctx.control_space = control_map
    status = f"Driving {len(levels)} control(s) from {CONTROL_FILE.name}."


@app.ui
def playground_ui(ctx):
    """Sliders on the left, the editor on the right."""
    with grid[0, 0]:
        logo.ui()

    with grid[1, 0]:
        processes.ui()

    with grid[2, 0]:
        panel_header("DRIVE THE HAND")
        if imgui.button("Connect / Reload"):
            _connect()
        imgui.same_line()
        imgui.text_colored(muted(), str(CONTROL_FILE.name))

        if failure:
            imgui.text_colored(DANGER, "Refused:")
            imgui.text_wrapped(failure)
        else:
            imgui.text_colored(SUCCESS if bus is not None else muted(), status)

        if bus is None:
            return
        changed = False
        for alias in levels:
            edited, levels[alias] = imgui.slider_float(alias, levels[alias], -1.0, 1.0)
            changed = changed or edited
        if imgui.button("Rest"):
            levels.update(dict.fromkeys(levels, 0.0))
            changed = True
        if changed:
            bus.push(levels)

    with grid[0:3, 1]:
        # The editor writes the same file the sliders were built from, so a save is a
        # reason to rebuild them.
        if editor.ui():
            _connect()
        imgui.separator()
        panel_header("WHAT VHI WOULD MAKE OF IT")
        imgui.text_unformatted(editor.resolved_summary())


def main() -> None:
    """Run until the window closes, then rest the hand."""
    try:
        app.run()
    finally:
        # Rest the hand and make that frame land before the outlet's thread dies.
        if bus is not None:
            bus.stop()
        vhi_outlet.stop()
        vhi_canonical.stop()


if __name__ == "__main__":
    main()
