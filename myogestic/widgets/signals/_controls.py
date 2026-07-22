from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import PALETTE, pop_selected, push_selected, segmented
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

    pause_label = f"{fa.ICON_FA_PLAY}  Resume" if v.paused else f"{fa.ICON_FA_PAUSE}  Pause"
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
        if imgui.button(f"{fa.ICON_FA_ARROWS_ROTATE}##{stream_name}_retarget"):
            v.show_retarget = not v.show_retarget
        if imgui.is_item_hovered():
            imgui.set_tooltip("Change source: scan + reconnect to a different LSL stream.")
        imgui.same_line()

    render_filter_and_scale(stream_name, v, stream.info.fs if stream.info else 0.0)

    if v.show_retarget:
        _scan_panel(active_stream, stream)

    render_resolution_controls(stream_name, stream, v)


def _render_rms_sliders(stream_name: str, v: ViewerState, fs: float) -> None:
    """The RMS-envelope window + hop sliders, shown only for the rms_env mode.

    Hop is capped at ``min(100 ms, window)`` so windows always overlap or abut
    (never leave gaps), and the invariant ``hop <= window`` is re-clamped every
    frame in case the window slider was dragged below the current hop.
    """
    imgui.push_item_width(104)
    w_changed, w_new = imgui.slider_float(
        f"##{stream_name}_rmswin",
        float(v.rms_window_ms),
        10.0,
        500.0,
        "win %.0f ms",
        flags=imgui.SliderFlags_.logarithmic,
    )
    if w_changed:
        v.rms_window_ms = w_new
    if imgui.is_item_hovered() and fs > 0:
        imgui.set_tooltip(
            f"RMS averaging window — how much signal each envelope point covers.\n"
            f"{round(v.rms_window_ms * fs / 1000)} samples at {fs:.0f} Hz."
        )
    imgui.same_line()

    hop_max = min(100.0, float(v.rms_window_ms))
    h_changed, h_new = imgui.slider_float(
        f"##{stream_name}_rmshop",
        min(float(v.rms_hop_ms), hop_max),
        1.0,
        hop_max,
        "hop %.0f ms",
    )
    if h_changed:
        v.rms_hop_ms = h_new
    if imgui.is_item_hovered() and fs > 0:
        imgui.set_tooltip(
            f"RMS shift — one envelope point every {round(v.rms_hop_ms * fs / 1000)} samples "
            f"({v.rms_hop_ms:.0f} ms).\nSmaller = denser, smoother envelope."
        )
    imgui.pop_item_width()
    # Keep hop <= min(100 ms, window) even after the window slider shrinks.
    v.rms_hop_ms = min(float(v.rms_hop_ms), hop_max)
    imgui.same_line()


def render_filter_and_scale(stream_name: str, v: ViewerState, fs: float) -> None:
    # Visual-only display transform, label on the left so it can't be mistaken
    # for the scaling controls that follow it on the row.
    df_modes = ["none", "rectify", "dc_removal", "rms_env"]
    df_labels = ["Raw", "Rectified", "DC removed", "RMS envelope"]
    df_idx = df_modes.index(v.display_filter) if v.display_filter in df_modes else 0
    imgui.text("View")
    imgui.same_line()
    imgui.push_item_width(130)
    df_changed, df_new = imgui.combo(f"##{stream_name}_df", df_idx, df_labels)
    imgui.pop_item_width()
    if df_changed:
        v.display_filter = df_modes[df_new]
    if imgui.is_item_hovered():
        imgui.set_tooltip("Visual-only transform - never affects recording or model input.")
    imgui.same_line()

    if v.display_filter == "rms_env":
        _render_rms_sliders(stream_name, v, fs)

    # Y-scaling group kept together: Auto/Manual + Rescale + Per-Ch. When Per-Ch
    # normalizes each channel into its own unit-height lane, the shared scale
    # (Auto/Manual/Rescale, manual bounds, and Gain) is inert, so those controls
    # grey out to make the active mode unambiguous.
    per_ch = v.per_channel_scale
    if v.scale_mode not in ("auto", "manual"):
        v.scale_mode = "auto"

    if per_ch:
        imgui.begin_disabled()
    # Segmented Auto/Manual instead of a cycle button — both modes visible, the
    # active one raised.
    scale_i = segmented(f"{stream_name}_scale", ["Auto", "Manual"], 1 if v.scale_mode == "manual" else 0)
    v.scale_mode = "manual" if scale_i == 1 else "auto"
    if imgui.is_item_hovered():
        imgui.set_tooltip("Y-axis scale: Auto = per-frame fit · Manual = fixed y_min/y_max.")

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
    if per_ch:
        imgui.end_disabled()

    imgui.same_line()
    ch_pc, pc = imgui.checkbox(f"Per-Ch##{stream_name}_perch", v.per_channel_scale)
    if ch_pc:
        v.per_channel_scale = pc
    if imgui.is_item_hovered():
        imgui.set_tooltip("Normalize each enabled channel into its own unit-height lane.")

    if per_ch or v.scale_mode != "manual":
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
    # Three label+slider columns in a stretch table, so each label sits
    # directly left of its own slider (no floating-between-sliders ambiguity)
    # and the widths track the panel width / DPI instead of hand-computed pixels.
    max_window = stream._buffer_seconds if hasattr(stream, "_buffer_seconds") else 60.0
    per_ch = v.per_channel_scale
    if not imgui.begin_table(f"{stream_name}_scope_row", 3, imgui.TableFlags_.sizing_stretch_same):
        return
    imgui.table_next_row()

    imgui.table_next_column()
    imgui.text("Point cap")
    imgui.same_line()
    imgui.set_next_item_width(-1)
    changed_r, new_r = imgui.slider_int(f"##{stream_name}_res", v.n_pixels, 100, 10000, "%d pts")
    if changed_r:
        v.n_pixels = new_r
    if imgui.is_item_hovered():
        imgui.set_tooltip(
            "Ceiling on the points drawn per channel — the plot-width target is\n"
            "capped here. Lower = coarser MinMax decimation, cheaper to draw."
        )

    imgui.table_next_column()
    imgui.text("Window")
    imgui.same_line()
    imgui.set_next_item_width(-1)
    changed_w, new_w = imgui.slider_float(f"##{stream_name}_win", v.window, 0.1, max_window, "%.1f s")
    if changed_w:
        v.window = new_w

    imgui.table_next_column()
    imgui.text("Gain")
    imgui.same_line()
    if per_ch:
        imgui.begin_disabled()
    imgui.set_next_item_width(-1)
    changed_g, new_g = imgui.slider_float(
        f"##{stream_name}_gain", v.gain, 0.01, 100.0, "%.2fx", flags=imgui.SliderFlags_.logarithmic
    )
    if changed_g:
        v.gain = new_g
    if per_ch:
        imgui.end_disabled()

    imgui.end_table()


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
    # Whether the floating channel-grid window is open. Driven by the
    # compact bar's `[Edit…]` button and by the window's own title-bar
    # close button (see `render_grid_window`).
    show_grid: bool = False


_grid_ui: dict[str, _GridUIState] = {}


def render_channel_controls(
    stream_name: str,
    stream: Stream,
    v: ViewerState,
    n_channels: int,
) -> tuple[set[int], list[str] | None, int]:
    """Render the compact channel bar, and mutate `v.channels` from user input.

    The bar is always drawn inline; the spatial toggle-grid itself only
    renders when `ui.show_grid` is set (via the bar's `[Edit…]` button), in
    its own floating window — see `render_grid_window`. `hovered_ch` is -1
    whenever that window is closed, since nothing can be hovered then.

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

    render_channel_bar(stream_name, ui, enabled, n_channels)

    hovered_ch = -1
    if ui.show_grid:
        hovered_ch = render_grid_window(stream_name, layout, enabled, ch_names, ui)

    # Resolve a click/drag session on mouse-up even if the window closed
    # mid-drag (e.g. the user hit the title-bar [x] while dragging) — cheap,
    # and keeps `ui.drag` from staying armed forever.
    _finalize_drag(ui, enabled)

    return enabled, ch_names, hovered_ch


def render_channel_bar(
    stream_name: str,
    ui: _GridUIState,
    enabled: set[int],
    n_channels: int,
) -> None:
    """Render the always-inline, one-line channel bar.

    `Channels {enabled}/{total}` + the global All/None/Invert ops (what the
    full-grid footer did before) + `[Edit…]`, which toggles the floating
    grid window (`ui.show_grid`) — the grid itself never renders inline.
    """
    imgui.text(f"Channels {len(enabled)}/{n_channels}")
    imgui.same_line()
    if imgui.small_button(f"All##{stream_name}_bar_all"):
        enabled.clear()
        enabled.update(range(n_channels))
    imgui.same_line()
    if imgui.small_button(f"None##{stream_name}_bar_none"):
        enabled.clear()
    imgui.same_line()
    if imgui.small_button(f"Invert##{stream_name}_bar_invert"):
        new_enabled = reduce_selection(enabled, "invert", range(n_channels))
        enabled.clear()
        enabled.update(new_enabled)
    imgui.same_line()

    # Highlight the toggle while the grid window is open — same "active
    # state" cue as the Manual scale-mode button in render_filter_and_scale.
    was_open = ui.show_grid
    if was_open:
        push_selected()
    # small_button (not button) so it matches the All/None/Invert pills — a full
    # button is taller and sits out of line with them.
    if imgui.small_button(f"Edit…##{stream_name}_bar_edit"):
        ui.show_grid = not ui.show_grid
    if was_open:
        pop_selected()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Open the spatial channel grid (click / drag / shift-click to select).")


def render_grid_window(
    stream_name: str,
    layout: list[ChannelGrid],
    enabled: set[int],
    ch_names: list[str] | None,
    ui: _GridUIState,
) -> int:
    """Render the floating per-stream channel-grid window; returns `hovered_ch`.

    A real `imgui.begin`/`imgui.end` window — movable, resizable, and
    closable via the title-bar `[x]` (which clears `ui.show_grid`) — not a
    `begin_popup`: that auto-closes on any click outside its bounds, which
    would abort a rectangle drag the instant it strays past the popup's
    edge.
    """
    # When multi-viewport is on (desktop default), open the grid as its OWN
    # native OS window instead of a panel confined to the app window. A
    # NoAutoMerge window class keeps it a separate platform window even when
    # dragged back over the app; positioned just inside the main window so it
    # opens on-screen (the user can move it, and the position persists). With
    # viewports off (browser / older build) this is skipped and it stays a
    # normal in-app floating window.
    if imgui.get_io().config_flags & imgui.ConfigFlags_.viewports_enable.value:
        wc = imgui.WindowClass()
        wc.viewport_flags_override_set = imgui.ViewportFlags_.no_auto_merge
        imgui.set_next_window_class(wc)
        mv = imgui.get_main_viewport()
        imgui.set_next_window_pos(
            imgui.ImVec2(mv.pos.x + 100.0, mv.pos.y + 100.0), imgui.Cond_.first_use_ever
        )
    imgui.set_next_window_size(imgui.ImVec2(520.0, 420.0), imgui.Cond_.first_use_ever)
    visible, still_open = imgui.begin(
        f"Channel selection — {stream_name}##{stream_name}_grid_window", True
    )
    hovered_ch = -1
    try:
        if visible:
            cell = _grid_cell_size()
            for grid_idx, grid in enumerate(layout):
                hovered_ch = render_grid(
                    stream_name, grid_idx, grid, enabled, ch_names, ui, cell, hovered_ch
                )
    finally:
        imgui.end()

    if not still_open:
        ui.show_grid = False
    return hovered_ch


def _grid_cell_size() -> float:
    """Cell edge length for the floating grid window.

    Large enough that a 3-digit channel index (``"255"``) fits centered
    without overflow — cells are no longer squeezed by the inline viewer's
    vertical budget now that they live in their own resizable window.
    """
    return imgui.get_frame_height() * 1.6


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


def _draw_cell_label(
    dl: imgui.ImDrawList, p_min: imgui.ImVec2, p_max: imgui.ImVec2, ch: int
) -> None:
    """Draw the global channel index `ch`, centered in the cell rect `p_min`-`p_max`.

    Uses the theme's plain text color (not the per-channel accent) so the
    number stays legible over *both* the enabled cell's tinted fill and the
    disabled cell's hollow background — the accent color already carries
    the on/off cue via the filled dot vs. hollow border in `render_cell`.
    A modestly reduced font size (`push_font(None, ...)`, the imgui-bundle
    idiom for a one-off size — see `prediction_label.py`) keeps a 3-digit
    index from crowding the cell.
    """
    label = str(ch)
    base_size = imgui.get_style().font_size_base
    imgui.push_font(None, base_size * 0.8)
    try:
        text_size = imgui.calc_text_size(label)
        color = imgui.color_convert_float4_to_u32(imgui.get_style_color_vec4(imgui.Col_.text))
        pos = imgui.ImVec2(
            (p_min.x + p_max.x) * 0.5 - text_size.x * 0.5,
            (p_min.y + p_max.y) * 0.5 - text_size.y * 0.5,
        )
        dl.add_text(pos, color, label)
    finally:
        imgui.pop_font()


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

    _draw_cell_label(dl, p_min, p_max, ch)

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
