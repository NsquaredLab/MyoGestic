from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from imgui_bundle import imgui

from myogestic.widgets.common import PALETTE
from myogestic.widgets.signals._channel_grid import (
    normalize_layout,
    rect_to_channels,
    reduce_selection,
)
from myogestic.widgets.signals._scan import _scan_panel

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import ChannelGrid, Stream
    from myogestic.widgets.signals._state import ViewerState


def render_controls(
    ctx: Context,
    stream_name: str,
    active_stream: str,
    stream: Stream,
    v: ViewerState,
    selectable: bool,
) -> None:
    """Render top controls and mutate `v` from user input."""
    if selectable and ctx.streams:
        names = list(ctx.streams.keys())
        cur = names.index(active_stream) if active_stream in names else 0
        imgui.push_item_width(120)
        changed, idx = imgui.combo(f"stream##{stream_name}_sel", cur, names)
        imgui.pop_item_width()
        if changed:
            v.selected_stream = names[idx]
            # Channel selection is *not* reset here: `resolve_enabled`
            # (in `_state.py`) keys the selection by `(stream, n_channels)`
            # and restores each stream's own set the next time it runs.
            v.paused = False
            v.frozen_ts = None
            v.frozen_data = None
        imgui.same_line()

    pause_label = "▶ Resume" if v.paused else "⏸ Pause"
    if imgui.button(f"{pause_label}##{stream_name}_pause"):
        v.paused = not v.paused
        if not v.paused:
            v.frozen_ts = None
            v.frozen_data = None
    if imgui.is_item_hovered():
        imgui.set_tooltip("Freeze the display (acquisition continues).")
    imgui.same_line()

    discover_fn = getattr(stream._source, "discover", None)
    if discover_fn is not None:
        if imgui.button(f"↻##{stream_name}_retarget"):
            v.show_retarget = not v.show_retarget
        if imgui.is_item_hovered():
            imgui.set_tooltip("Change source: scan + reconnect to a different LSL stream.")
        imgui.same_line()

    render_filter_and_scale(stream_name, v)

    if v.show_retarget:
        _scan_panel(active_stream, stream)

    render_resolution_controls(stream_name, stream, v)


def render_filter_and_scale(stream_name: str, v: ViewerState) -> None:
    df_modes = ["none", "rectify", "dc_removal", "rms_env"]
    df_idx = df_modes.index(v.display_filter) if v.display_filter in df_modes else 0
    imgui.push_item_width(110)
    df_changed, df_new = imgui.combo(f"display##{stream_name}_df", df_idx, df_modes)
    imgui.pop_item_width()
    if df_changed:
        v.display_filter = df_modes[df_new]
    if imgui.is_item_hovered():
        imgui.set_tooltip("Visual-only transform - never affects recording or model input.")
    imgui.same_line()

    label_for = {"auto": "Auto", "manual": "Manual"}
    next_for = {"auto": "manual", "manual": "auto"}
    if v.scale_mode not in label_for:
        v.scale_mode = "auto"
    is_manual = v.scale_mode == "manual"
    if is_manual:
        imgui.push_style_color(
            imgui.Col_.button,
            imgui.ImVec4(0.31, 0.61, 0.98, 0.9),
        )
    if imgui.button(f"{label_for[v.scale_mode]}##{stream_name}_scale"):
        v.scale_mode = next_for[v.scale_mode]
    if is_manual:
        imgui.pop_style_color()
    if imgui.is_item_hovered():
        imgui.set_tooltip(
            "Y-axis scale mode (click to cycle):\n"
            "  Auto   — real-time per-frame fit (default)\n"
            "  Manual — fixed y_min/y_max"
        )

    # One-shot "rescale now" — captures the current visible window's
    # y-range into Manual mode. Useful when the user wants to lock in a
    # good range once and then leave it alone (cheaper visually than
    # Auto and steadier than continuous auto-fit).
    imgui.same_line()
    if imgui.button(f"Rescale##{stream_name}_rescale"):
        v.rescale_pending = True
    if imgui.is_item_hovered():
        imgui.set_tooltip(
            "Capture the current y-range into Manual mode.\n"
            "Click again any time the trace goes off-scale."
        )

    if v.scale_mode != "manual":
        return

    imgui.same_line()
    imgui.push_item_width(70)
    chmin, ymin = imgui.input_float(f"min##{stream_name}_ymin", v.y_min, 0.0, 0.0, "%.2f")
    if chmin:
        v.y_min = ymin
    imgui.same_line()
    chmax, ymax = imgui.input_float(f"max##{stream_name}_ymax", v.y_max, 0.0, 0.0, "%.2f")
    if chmax:
        v.y_max = ymax
    imgui.pop_item_width()


def render_resolution_controls(
    stream_name: str,
    stream: Stream,
    v: ViewerState,
) -> None:
    third = imgui.get_content_region_avail().x * 0.33
    imgui.push_item_width(third)
    changed_r, new_r = imgui.slider_int(f"Resolution##{stream_name}", v.n_pixels, 100, 10000)
    if changed_r:
        v.n_pixels = new_r
    imgui.pop_item_width()

    imgui.same_line()
    imgui.push_item_width(third)
    max_window = stream._buffer_seconds if hasattr(stream, "_buffer_seconds") else 60.0
    changed_w, new_w = imgui.slider_float(
        f"Window##{stream_name}_win", v.window, 0.1, max_window, "%.1f s"
    )
    if changed_w:
        v.window = new_w
    imgui.pop_item_width()

    imgui.same_line()
    imgui.push_item_width(imgui.get_content_region_avail().x)
    changed_g, new_g = imgui.slider_float(
        f"Gain##{stream_name}_gain",
        v.gain,
        0.01,
        100.0,
        "%.2fx",
        flags=imgui.SliderFlags_.logarithmic,
    )
    if changed_g:
        v.gain = new_g
    imgui.pop_item_width()


@dataclass
class _DragSession:
    """In-flight click/drag session for one grid's toggle-grid.

    Armed on mouse-down over a cell, resolved on release. `dragged`
    distinguishes a below-threshold click (single toggle, resolved from
    `op`/`ch0`) from a rectangle drag (already applied live, frame by
    frame, from `snapshot`).
    """

    armed: bool = False
    grid_idx: int = -1
    r0: int = -1
    c0: int = -1
    ch0: int = -1
    op: str = "add"
    snapshot: set[int] = field(default_factory=set)
    dragged: bool = False


@dataclass
class _GridUIState:
    """Per-stream interaction state for the channel grid.

    Mirrors the module-level per-stream-name dict pattern already used by
    `_scan.py`'s `_ScanState` for transient widget state that must survive
    across frames but doesn't belong on the shared `ViewerState`.
    """

    drag: _DragSession = field(default_factory=_DragSession)
    last_clicked: int = -1
    # `v.active_channels_key` as of the last frame this grid was rendered —
    # lets `render_channel_controls` detect a stream/channel-count change
    # and drop the shift-click anchor so it can't briefly resolve a range
    # against the *new* stream's out-of-range channel indices.
    last_key: tuple[str, int] | None = None


_grid_ui: dict[str, _GridUIState] = {}


def render_channel_controls(
    stream_name: str,
    stream: Stream,
    v: ViewerState,
    n_channels: int,
) -> tuple[set[int], list[str] | None, int]:
    """Render the spatial toggle-grid and mutate `v.channels` from user input.

    `resolve_enabled` (in `_state.py`) owns initializing `v.channels` before
    this runs each frame — this function only ever reads/mutates the
    existing selection, it never (re)seeds it.
    """
    enabled = v.channels
    ch_names = stream.info.channel_names if stream.info else None
    channel_grids = stream.info.channel_grids if stream.info else None
    layout = normalize_layout(channel_grids, n_channels)
    ui = _grid_ui.setdefault(stream_name, _GridUIState())
    if ui.last_key != v.active_channels_key:
        ui.last_clicked = -1
        ui.last_key = v.active_channels_key

    cell = imgui.get_frame_height()
    hovered_ch = -1
    for grid_idx, grid in enumerate(layout):
        hovered_ch = render_grid(
            stream_name, grid_idx, grid, enabled, ch_names, ui, cell, hovered_ch
        )

    _finalize_drag(ui, enabled)
    render_channel_footer(stream_name, enabled, n_channels)

    return enabled, ch_names, hovered_ch


def render_grid(
    stream_name: str,
    grid_idx: int,
    grid: ChannelGrid,
    enabled: set[int],
    ch_names: list[str] | None,
    ui: _GridUIState,
    cell: float,
    hovered_ch: int,
) -> int:
    """Render one grid's header + cells; returns the updated `hovered_ch`."""
    columns = grid.columns
    total = len(columns)
    sel = sum(1 for c in columns if c in enabled)
    imgui.text(f"{grid.label}  {sel}/{total}")
    imgui.same_line()
    if imgui.small_button(f"All##{stream_name}_g{grid_idx}_all"):
        enabled.update(columns)
    imgui.same_line()
    if imgui.small_button(f"None##{stream_name}_g{grid_idx}_none"):
        enabled.difference_update(columns)

    if not grid.cells or not grid.cells[0]:
        return hovered_ch

    item_spacing = imgui.get_style().item_spacing
    spacing_x = item_spacing.x
    spacing_y = item_spacing.y
    origin = imgui.get_cursor_screen_pos()

    for row_idx, row in enumerate(grid.cells):
        for col_idx, ch in enumerate(row):
            if col_idx > 0:
                imgui.same_line()
            if ch is None:
                imgui.dummy(imgui.ImVec2(cell, cell))
                continue
            hovered_ch = render_cell(
                stream_name,
                grid_idx,
                row_idx,
                col_idx,
                ch,
                enabled,
                ch_names,
                grid.label,
                ui,
                cell,
                hovered_ch,
            )

    # Live rectangle update: recompute from the mouse-down snapshot every
    # frame the drag is in progress, hit-testing the cursor against this
    # frame's own grid geometry — a hovered *item* isn't reliable here since
    # ImGui suppresses other items' hover while the origin cell is active.
    drag = ui.drag
    if drag.armed and drag.grid_idx == grid_idx and imgui.is_mouse_down(imgui.MouseButton_.left):
        io = imgui.get_io()
        if drag.dragged or imgui.is_mouse_dragging(
            imgui.MouseButton_.left, io.mouse_drag_threshold
        ):
            drag.dragged = True
            r1, c1 = _hit_test(origin, cell, spacing_x, spacing_y, imgui.get_mouse_pos())
            new_enabled = reduce_selection(
                drag.snapshot, drag.op, rect_to_channels(grid, drag.r0, drag.c0, r1, c1)
            )
            enabled.clear()
            enabled.update(new_enabled)

    return hovered_ch


def _hit_test(
    origin: imgui.ImVec2, cell: float, spacing_x: float, spacing_y: float, mouse: imgui.ImVec2
) -> tuple[int, int]:
    """Map a screen-space mouse position to a `(row, col)` cell address.

    Purely geometric (uniform grid, known origin/step) — no reliance on
    per-item hover, which ImGui suppresses for non-active items during a
    drag. Out-of-range results are expected and safe: `rect_to_channels`
    clamps them to the grid bounds.

    Cells are laid out with `same_line()` horizontally — column stride is
    `cell + spacing_x` — and wrap onto a new line vertically — row stride
    is `cell + spacing_y`. The two axes use ImGui's independent
    `item_spacing.x`/`.y`, so they must not be conflated (a single shared
    `spacing` drifts the vertical hit-test whenever `x != y`, as it does
    with this app's theme).
    """
    return _hit_test_xy(mouse.x, mouse.y, origin.x, origin.y, cell, spacing_x, spacing_y)


def _hit_test_xy(
    mouse_x: float,
    mouse_y: float,
    origin_x: float,
    origin_y: float,
    cell: float,
    spacing_x: float,
    spacing_y: float,
) -> tuple[int, int]:
    """Pure-float core of `_hit_test` (no imgui types) — see there for details."""
    step_x = cell + spacing_x
    step_y = cell + spacing_y
    if step_x <= 0 or step_y <= 0:
        return 0, 0
    row = int((mouse_y - origin_y) // step_y)
    col = int((mouse_x - origin_x) // step_x)
    return row, col


def render_cell(
    stream_name: str,
    grid_idx: int,
    row_idx: int,
    col_idx: int,
    ch: int,
    enabled: set[int],
    ch_names: list[str] | None,
    grid_label: str,
    ui: _GridUIState,
    cell: float,
    hovered_ch: int,
) -> int:
    """Render one channel cell; returns the updated `hovered_ch`."""
    imgui.invisible_button(f"##{stream_name}_g{grid_idx}_cell_{ch}", imgui.ImVec2(cell, cell))

    is_on = ch in enabled
    color = PALETTE[ch % len(PALETTE)]
    p_min = imgui.get_item_rect_min()
    p_max = imgui.get_item_rect_max()
    dl = imgui.get_window_draw_list()
    rounding = cell * 0.15

    if is_on:
        bg = imgui.color_convert_float4_to_u32(imgui.ImVec4(color[0], color[1], color[2], 0.35))
        dl.add_rect_filled(p_min, p_max, bg, rounding=rounding)
        center = imgui.ImVec2((p_min.x + p_max.x) * 0.5, (p_min.y + p_max.y) * 0.5)
        dot = imgui.color_convert_float4_to_u32(imgui.ImVec4(color[0], color[1], color[2], 1.0))
        dl.add_circle_filled(center, cell * 0.18, dot)
    else:
        # Dim + hollow border: an on/off cue beyond brightness alone
        # (colorblind-safe) — a filled dot vs. no dot, not just color.
        border = imgui.color_convert_float4_to_u32(imgui.ImVec4(0.5, 0.5, 0.5, 0.6))
        dl.add_rect(p_min, p_max, border, rounding=rounding)

    if imgui.is_item_hovered():
        hovered_ch = ch
        name = ch_names[ch] if ch_names and ch < len(ch_names) else f"ch{ch}"
        imgui.set_tooltip(f"{grid_label} · col {ch} · {name}")
        highlight = imgui.color_convert_float4_to_u32(imgui.ImVec4(1.0, 1.0, 1.0, 0.8))
        dl.add_rect(p_min, p_max, highlight, rounding=rounding, thickness=1.5)

    if imgui.is_item_focused() and imgui.is_key_pressed(imgui.Key.space, repeat=False):
        if is_on:
            enabled.discard(ch)
        else:
            enabled.add(ch)

    if imgui.is_item_activated():
        io = imgui.get_io()
        if io.key_shift and ui.last_clicked >= 0:
            lo, hi = sorted((ui.last_clicked, ch))
            new_enabled = reduce_selection(enabled, "add", range(lo, hi + 1))
            enabled.clear()
            enabled.update(new_enabled)
            ui.drag.armed = False
        else:
            ui.drag = _DragSession(
                armed=True,
                grid_idx=grid_idx,
                r0=row_idx,
                c0=col_idx,
                ch0=ch,
                op="remove" if is_on else "add",
                snapshot=set(enabled),
                dragged=False,
            )
            ui.last_clicked = ch

    return hovered_ch


def _finalize_drag(ui: _GridUIState, enabled: set[int]) -> None:
    """Resolve an armed click/drag session once the mouse button lets go.

    A rectangle drag has already been applied live (see `render_grid`), so
    only a below-threshold click needs resolving here: a plain toggle of
    the mouse-down cell via the `op` captured at mouse-down.
    """
    drag = ui.drag
    if not drag.armed or imgui.is_mouse_down(imgui.MouseButton_.left):
        return
    if not drag.dragged:
        if drag.op == "add":
            enabled.add(drag.ch0)
        else:
            enabled.discard(drag.ch0)
    drag.armed = False


def render_channel_footer(
    stream_name: str,
    enabled: set[int],
    n_channels: int,
) -> None:
    imgui.text(f"enabled {len(enabled)}/{n_channels}")
    imgui.same_line()
    if imgui.small_button(f"All##{stream_name}_foot_all"):
        enabled.clear()
        enabled.update(range(n_channels))
    imgui.same_line()
    if imgui.small_button(f"None##{stream_name}_foot_none"):
        enabled.clear()
    imgui.same_line()
    if imgui.small_button(f"Invert##{stream_name}_foot_invert"):
        new_enabled = reduce_selection(enabled, "invert", range(n_channels))
        enabled.clear()
        enabled.update(new_enabled)
