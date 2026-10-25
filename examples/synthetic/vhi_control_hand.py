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

from myogestic import App, Context, Fr, Grid, Px
from myogestic._theme import mono_font
from myogestic.controls import ControlLink, load_control_map
from myogestic.remote import RemoteTarget
from myogestic.vhi import virtual_hand
from myogestic.widgets import AppLogo, ProcessLauncher
from myogestic.widgets.common import (
    IDLE,
    SUCCESS,
    mono_text,
    muted,
    panel_header,
    primary_button,
    tinted_row,
    ui_px,
)

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
    col_width=[Fr(1)],
)


@app.ui
def demo_ui(ctx: Context) -> None:
    """Sliders, one per alias in the file."""
    with grid[0, 0]:
        logo.ui()

    with grid[1, 0]:
        processes.ui()

    with grid[2, 0]:
        bus = link.bus
        tone = SUCCESS if bus is not None else IDLE
        panel_header("CONTROL HAND", status=tone)
        with tinted_row(tone):
            imgui.align_text_to_frame_padding()
            imgui.text_unformatted("Connected" if bus is not None else "Not connected")
        if bus is None:
            imgui.push_style_color(imgui.Col_.text, muted())
            imgui.text_wrapped(
                "Launch VHI, then Connect to load the operator hand's controls."
                if PROCESSES else
                "Launch VHI externally, then Connect to load the operator hand's controls."
            )
            imgui.pop_style_color()
            if primary_button("Connect", size=(imgui.get_content_region_avail().x, 0)):
                link.ensure()
            return

        changed = False
        columns = 2 if imgui.get_content_region_avail().x >= ui_px(480) else 1
        if imgui.begin_table("control-hand-fields", columns, imgui.TableFlags_.sizing_stretch_same):
            for alias in levels:
                imgui.table_next_column()
                _caption(alias, levels[alias])
                imgui.set_next_item_width(imgui.get_content_region_avail().x)
                edited, levels[alias] = imgui.slider_float(f"##{alias}", levels[alias], 0.0, 1.0)
                changed = changed or edited
            imgui.end_table()
        if primary_button("Rest", size=(imgui.get_content_region_avail().x, 0)):
            levels.update(dict.fromkeys(levels, 0.0))
            changed = True
        if changed:
            bus.push(levels)


def _caption(alias: str, value: float) -> None:
    """Keep the alias readable above its slider, reserving room for the mono value."""
    style = imgui.get_style()
    room = imgui.get_content_region_avail().x
    right = imgui.get_cursor_pos_x() + room
    text = f"{value:.3f}"
    font = mono_font()
    if font is not None:
        imgui.push_font(font, style.font_size_base)
    value_w = imgui.calc_text_size(text).x
    if font is not None:
        imgui.pop_font()
    available = room - value_w - style.item_spacing.x
    shown = alias
    while shown and imgui.calc_text_size(shown + ("…" if shown != alias else "")).x > available:
        shown = shown[:-1]
    imgui.text_colored(muted(), shown + ("…" if shown != alias else ""))
    imgui.set_item_tooltip(alias)
    imgui.same_line()
    imgui.set_cursor_pos_x(right - value_w)
    mono_text(text)


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
