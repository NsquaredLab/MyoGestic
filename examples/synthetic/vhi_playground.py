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

CONTROL_FILE = pathlib.Path(__file__).resolve().parent.parent / "controls" / "playground.toml"

vhi = virtual_hand()
vhi_outlet = vhi.outlet()
vhi_canonical = vhi.canonical_client()

app = App("VHI 2 playground")

# Everything below is rebuilt whenever the file changes, so none of it can be module
# state: `levels` has one entry per alias *in the file*, and the bus is resolved against
# the manifest, which needs VHI up.
levels: dict[str, float] = {}
#: alias -> the states a held control accepts, straight from the target's manifest. A
#: discrete control cannot be driven by a slider: it takes one of *its* names, and it goes
#: over gRPC rather than the pose stream. Without this, mapping `vhi.control.gesture` here
#: produced a control the app could not command at all — mapped, resolved, and inert.
states: dict[str, tuple[str, ...]] = {}
#: The state each held control is currently showing, so the picker has something to say.
chosen: dict[str, str] = {}
bus: ControlBus | None = None
status = "Launch VHI, then press Connect."
failure = ""

# `stream="output"` is the default, and stating it is the point: this app drives the
# model's hand, so the editor offers that hand's controls and refuses one from the
# operator's before it can be saved. Without it the picker would offer all 23 and the
# refusal would arrive from the bus, three layers from the click that caused it.
editor = ControlMapEditor(
    CONTROL_FILE, client=vhi_canonical, stream="output", title="EDIT THE MAP"
)
# `launchable` not `launcher`: an unlaunchable renderer must not stop this app from
# opening — a renderer that is already running needs no button, and the reason is
# logged either way.
processes = ProcessLauncher(vhi.launchable())
logo = AppLogo()

LOGO_CELL_W = 260
WORDMARK_ASPECT = 800 / 540
LOGO_H = Px(LOGO_CELL_W / WORDMARK_ASPECT)

# Two layouts, picked per frame from the window's actual width. A Grid's Fr tracks already
# stretch, but the *number* of columns and their proportions are fixed at construction —
# and a 50/50 split is the wrong answer at both ends: at 700 px each half is too narrow
# for the editor's rows, and at 2000 px the sliders get a thousand pixels they have no use
# for. So: stacked below the breakpoint, and a fixed-width control column beside a
# stretching editor above it.
#
# `Px` for the control column rather than `Fr` is the point — the sliders need a usable
# width, not a proportional one, so every pixel the window gains goes to the editor, which
# is the part that can use it.
STACK_BELOW = 900.0
CONTROLS_W = 420.0

WIDE = Grid(
    3,
    2,
    row_height=[LOGO_H, Px(90), Fr(1)],
    col_width=[Px(CONTROLS_W), Fr(1)],
)
NARROW = Grid(
    4,
    1,
    # A shorter wordmark than the wide layout gets: on a narrow window the logo, the
    # launcher and an unconnected slider panel filled better than half the height before
    # any content appeared, and the logo is the only one of the three that is decoration.
    # The editor gets twice the leftover height, because it is the part that has rows to
    # show: an even split left it cut off mid-row while the slider panel above it — often
    # empty, since it has nothing to show until Connect — sat on half the window.
    row_height=[Px(90), Px(90), Fr(1), Fr(2)],
    col_width=[Fr(1)],
)


def _connect() -> None:
    """(Re)read the file and resolve it against whatever VHI currently exports.

    Called from a button, never from a render or predict path: `capabilities()` blocks
    on an RPC. Rebuilding from scratch each time is deliberate — a stale slider for an
    alias that no longer exists would send a value nothing reads.
    """
    global bus, levels, states, status, failure
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
    levels = {
        alias: 0.0 for alias, dof in controls.dofs.items() if not hasattr(dof, "states")
    }
    states = {
        alias: tuple(dof.states)
        for alias, dof in controls.dofs.items()
        if hasattr(dof, "states")
    }
    app.ctx.control_space = control_map
    held = f" and {len(states)} held state(s)" if states else ""
    status = f"Driving {len(levels)} control(s){held} from {CONTROL_FILE.name}."


@app.ui
def playground_ui(ctx):
    """Sliders and the editor: side by side when there is room, stacked when not."""
    wide = imgui.get_content_region_avail().x >= STACK_BELOW
    grid = WIDE if wide else NARROW
    editor_cell = grid[0:3, 1] if wide else grid[3, 0]

    with grid[0, 0]:
        logo.ui()

    with grid[1, 0]:
        processes.ui()

    with grid[2, 0]:
        panel_header("DRIVE THE HAND")
        if imgui.button("Connect / Reload"):
            _connect()
        if imgui.get_content_region_avail().x >= 160.0:
            imgui.same_line()
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped(CONTROL_FILE.name)
        imgui.pop_style_color()

        if failure:
            imgui.text_colored(DANGER, "Refused:")
            imgui.text_wrapped(failure)
        else:
            imgui.push_style_color(imgui.Col_.text, SUCCESS if bus is not None else muted())
            imgui.text_wrapped(status)
            imgui.pop_style_color()

        if bus is not None:
            _sliders_ui()

    with editor_cell:
        # The editor writes the same file the sliders were built from, so a save is a
        # reason to rebuild them.
        if editor.ui():
            _connect()
        imgui.separator()
        panel_header("WHAT VHI WOULD MAKE OF IT")
        # Wrapped at the cell edge: a fan-out summary is a long line, and unwrapped it
        # would be the one thing that still overflowed a narrow column.
        imgui.push_text_wrap_pos(0.0)
        imgui.text_unformatted(editor.resolved_summary())
        imgui.pop_text_wrap_pos()


def _sliders_ui() -> None:
    """One slider per control in the file, sized to the column it is in.

    A slider is the one control here that must not be squeezed: a 60-pixel one cannot be
    dragged to a useful value. So the label goes *above* it on a narrow column rather
    than beside it, which buys back the label's width for the track itself.
    """
    assert bus is not None
    avail = imgui.get_content_region_avail().x
    inline = avail >= 260.0
    changed = False
    for alias in levels:
        if not inline:
            imgui.text_unformatted(alias)
        imgui.set_next_item_width(avail - (imgui.calc_text_size(alias).x + 12.0 if inline else 0.0))
        edited, levels[alias] = imgui.slider_float(
            alias if inline else f"##{alias}", levels[alias], -1.0, 1.0
        )
        changed = changed or edited
    if imgui.button("Rest"):
        levels.update(dict.fromkeys(levels, 0.0))
        changed = True
    if changed:
        bus.push(levels)
    _held_states_ui()


def _held_states_ui() -> None:
    """A picker per held control: choose one of the states the target declared.

    `bus.select` rather than `bus.push`: a held state is delivered on change and rebases
    its own stability gate, so the next frame's push does not re-fire what was just
    chosen. And the states are the *target's* names — this app invents none of them.
    """
    assert bus is not None
    if not states:
        return
    imgui.separator()
    for alias, options in states.items():
        imgui.set_next_item_width(imgui.get_content_region_avail().x * 0.6)
        if imgui.begin_combo(alias, chosen.get(alias, options[0])):
            for state in options:
                selected, _ = imgui.selectable(state, chosen.get(alias) == state)
                if selected:
                    chosen[alias] = state
                    bus.select(alias, state)
            imgui.end_combo()


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
