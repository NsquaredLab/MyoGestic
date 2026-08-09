from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import (
    PALETTE,
    hairline,
    pop_selected,
    primary,
    push_selected,
    segmented,
)
from myogestic.widgets.signals._channel_grid import (
    grid_arrangement,
    normalize_layout,
    rect_to_channels,
    reduce_selection,
)
from myogestic.widgets.signals._scan import _scan_panel
from myogestic.widgets.signals._state import _DETAIL_FULL, _DETAIL_MIN, select_stream

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import ChannelGrid, Stream
    from myogestic.widgets.signals._state import ViewerState


# Each control row is a borderless table: the button groups keep their natural
# width while the sliders stretch to whatever is left, so a row stays one line
# at any panel width. Grouping is carried by hairline rules, not table chrome.
_ROW_FLAGS = imgui.TableFlags_.sizing_fixed_fit | imgui.TableFlags_.no_pad_outer_x


def _group_rule() -> None:
    """A faint vertical rule between two control groups on the same row."""
    style = imgui.get_style()
    imgui.same_line()
    height = imgui.get_frame_height()
    pos = imgui.get_cursor_screen_pos()
    x = pos.x + style.item_spacing.x * 0.5
    imgui.get_window_draw_list().add_line(
        imgui.ImVec2(x, pos.y + 3.0),
        imgui.ImVec2(x, pos.y + height - 3.0),
        imgui.get_color_u32(hairline(0.8)),
    )
    imgui.dummy(imgui.ImVec2(style.item_spacing.x, height))
    imgui.same_line()


def _slider_label(text: str) -> None:
    """Label to the left of a full-width slider, the layout every slider cell uses."""
    imgui.align_text_to_frame_padding()
    imgui.text(text)
    imgui.same_line()
    imgui.set_next_item_width(-1)


def render_controls(
    ctx: Context,
    stream_name: str,
    active_stream: str,
    stream: Stream,
    v: ViewerState,
    selectable: bool,
    enabled: set[int] | None = None,
    scope: list[int] | None = None,
) -> None:
    """Render the control rows and mutate `v` from user input.

    Two rows, split by what they act on rather than by what fits: row one is the
    **signal and the time axis** (freeze, source, notch, view transform, window,
    detail), row two is the **amplitude axis and the channels** (scale policy,
    gain, artifact rejection, channel selection). Groups within a row are
    separated by a hairline rule.

    ``enabled`` / ``scope`` are the resolved channel selection; pass them to get
    the channel bar inline in row two, omit them and the row ends after the
    sliders (the caller then draws the bar itself).
    """
    fs = stream.info.fs if stream.info else 0.0
    max_window = stream._buffer_seconds if hasattr(stream, "_buffer_seconds") else 60.0

    # --- Row 1: the signal, and how much of it in time ---------------------
    if imgui.begin_table(f"{stream_name}_row_signal", 3, _ROW_FLAGS):
        imgui.table_setup_column("group", imgui.TableColumnFlags_.width_fixed)
        imgui.table_setup_column("window", imgui.TableColumnFlags_.width_stretch)
        imgui.table_setup_column("detail", imgui.TableColumnFlags_.width_stretch)
        imgui.table_next_row()

        imgui.table_next_column()
        _render_transport(ctx, stream_name, active_stream, stream, v, selectable)
        _group_rule()
        _render_signal_group(stream_name, v, fs)

        imgui.table_next_column()
        _group_rule()
        _slider_label("Window")
        changed_w, new_w = imgui.slider_float(
            f"##{stream_name}_win", v.window, 0.1, max_window, "%.1f s"
        )
        if changed_w:
            v.window = new_w
        if imgui.is_item_hovered():
            imgui.set_tooltip("How much history the scope shows, in seconds.")

        imgui.table_next_column()
        _slider_label("Detail")
        # `_slider_label` stretches the next item to the column edge (`-1`). Claim the
        # toggle's width back first, or `same_line` puts it past that edge and off the
        # panel — the slider is not "as wide as fits", it is "all of it".
        style = imgui.get_style()
        toggle_w = imgui.calc_text_size("1:1").x + style.frame_padding.x * 2.0
        imgui.set_next_item_width(-(toggle_w + style.item_spacing.x))
        # `detail_factor` is points-per-pixel internally; shown as a percentage of
        # full detail (100% = the crispest _DETAIL_FULL density).
        pct = v.detail_factor / _DETAIL_FULL * 100.0
        changed_r, new_pct = imgui.slider_float(
            f"##{stream_name}_detail", pct, _DETAIL_MIN / _DETAIL_FULL * 100.0, 100.0, "%.0f%%"
        )
        if changed_r:
            v.detail_factor = new_pct / 100.0 * _DETAIL_FULL
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Display density only — recording and analysis are unchanged.\n"
                "100% draws a few points per pixel (crispest); drag left for a\n"
                "coarser, cheaper trace when many channels tax the frame rate.\n"
                "MinMax keeps peak height, but fine shape and timing coarsen."
            )
        imgui.same_line()
        _render_one_to_one(stream_name, v, fs, enabled, stream)
        imgui.end_table()

    # --- Row 2: the amplitude axis, and which channels ---------------------
    show_bar = enabled is not None and bool(scope)
    n_cols = 4 if show_bar else 3
    if imgui.begin_table(f"{stream_name}_row_scale", n_cols, _ROW_FLAGS):
        imgui.table_setup_column("group", imgui.TableColumnFlags_.width_fixed)
        imgui.table_setup_column("gain", imgui.TableColumnFlags_.width_stretch)
        imgui.table_setup_column("artifact", imgui.TableColumnFlags_.width_stretch)
        if show_bar:
            imgui.table_setup_column("channels", imgui.TableColumnFlags_.width_fixed)
        imgui.table_next_row()

        imgui.table_next_column()
        _render_scale_group(stream_name, v)

        imgui.table_next_column()
        _group_rule()
        _slider_label("Gain")
        # Gain is inert in per-channel AUTO (normalization cancels it); in per-channel
        # MANUAL it magnifies each trace against its frozen range, so it stays live.
        gain_inert = v.per_channel_scale and v.scale_mode == "auto"
        if gain_inert:
            imgui.begin_disabled()
        changed_g, new_g = imgui.slider_float(
            f"##{stream_name}_gain",
            v.gain,
            0.01,
            100.0,
            "%.2fx",
            flags=imgui.SliderFlags_.logarithmic,
        )
        if changed_g:
            v.gain = new_g
        if gain_inert:
            imgui.end_disabled()

        imgui.table_next_column()
        _slider_label("Artifact")
        changed_t, new_t = imgui.slider_float(
            f"##{stream_name}_transient", v.transient_ms, 0.0, 40.0, "< %.0f ms"
        )
        if changed_t:
            v.transient_ms = new_t
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Ignore transients shorter than this when fitting the y-scale, so a brief "
                "movement\nartifact doesn't blow up the range. 0 = plain min/max. Keep it "
                "below your shortest\nreal contraction."
            )

        if show_bar:
            imgui.table_next_column()
            _group_rule()
            imgui.align_text_to_frame_padding()
            ui = _grid_ui.setdefault(stream_name, _GridUIState())
            render_channel_bar(stream_name, ui, enabled, scope)  # type: ignore
        imgui.end_table()

    # Full-width, below both rows: the scan list is a block, not a control.
    if v.show_retarget:
        _scan_panel(active_stream, stream)



#: Points per frame that "1:1" is allowed to ask for, summed over drawn channels.
#: Detail's ceiling exists so a wide rig cannot stall the frame rate, and turning
#: decimation off removes that ceiling — so the budget replaces it. Sized to permit
#: the case the toggle is for (a handful of channels over a few seconds) and to refuse
#: the one it would ruin: 64 channels of 2 kHz over a 10 s window is 1.3M points, every
#: frame, for a trace no display can resolve.
_ONE_TO_ONE_MAX_POINTS = 250_000


def _render_one_to_one(
    stream_name: str,
    v: ViewerState,
    fs: float,
    enabled: set[int] | None,
    stream: Stream,
) -> None:
    """The "1:1" toggle beside Detail: draw every sample, or MinMax as usual.

    Its own control rather than the top of the Detail slider, because it is a different
    kind of decision. Detail trades crispness against cost along a continuum a user can
    feel; this either reads the raw waveform or does not, and its cost is set by the
    window and the channel count rather than by where the handle sits.

    Refused — and dropped, if it is already on — once the window would exceed
    `_ONE_TO_ONE_MAX_POINTS`. Dropped rather than merely greyed out because the window
    slider can grow past the budget while this is on, and a toggle that says it is
    showing every sample while quietly not doing so is worse than one that turns itself
    off in front of you.
    """
    n_channels = len(enabled) if enabled is not None else (stream.info.n_channels if stream.info else 0)
    points = int(v.window * fs * max(n_channels, 1))
    over = points > _ONE_TO_ONE_MAX_POINTS
    if over:
        v.one_to_one = False

    if over:
        imgui.begin_disabled()
    # Read once, before the button: clicking flips `v.one_to_one`, so a `pop` guarded on
    # it directly disagrees with the `push` on the very frame it is clicked — popping a
    # colour that was never pushed when turning on, and leaking three when turning off.
    # A push/pop pair must be guarded on the value as it was at push time.
    selected = v.one_to_one
    if selected:
        push_selected()
    if imgui.small_button(f"1:1##{stream_name}_one_to_one"):
        v.one_to_one = not v.one_to_one
    if selected:
        pop_selected()
    if over:
        imgui.end_disabled()

    if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
        if over:
            imgui.set_tooltip(
                f"{points:,} points per frame across {n_channels} channels — too many.\n"
                f"Shorten the window (or draw fewer channels) to under "
                f"{_ONE_TO_ONE_MAX_POINTS:,}."
            )
        else:
            imgui.set_tooltip(
                "Draw every sample, with no MinMax reduction.\n"
                f"About {points:,} points per frame at this window and channel count.\n"
                "For reading waveform shape shorter than one decimation bucket —\n"
                "Detail alone cannot get there, it tops out a few points per pixel."
            )


def _render_transport(
    ctx: Context,
    stream_name: str,
    active_stream: str,
    stream: Stream,
    v: ViewerState,
    selectable: bool,
) -> None:
    """Stream picker (optional), freeze toggle, and the retarget toggle."""
    if selectable and ctx.streams:
        names = list(ctx.streams.keys())
        cur = names.index(active_stream) if active_stream in names else 0
        imgui.push_item_width(120)
        changed, idx = imgui.combo(f"stream##{stream_name}_sel", cur, names)
        imgui.pop_item_width()
        if changed:
            select_stream(v, names[idx])
        imgui.same_line()

    pause_label = f"{fa.ICON_FA_PLAY}  Resume" if v.paused else f"{fa.ICON_FA_PAUSE}  Pause"
    if imgui.button(f"{pause_label}##{stream_name}_pause"):
        v.paused = not v.paused
        if not v.paused:
            v.frozen_ts = None
            v.frozen_data = None
    if imgui.is_item_hovered():
        imgui.set_tooltip("Freeze the display (acquisition continues).")

    discover_fn = getattr(stream._source, "discover", None)
    if discover_fn is not None:
        imgui.same_line()
        if imgui.button(f"{fa.ICON_FA_ARROWS_ROTATE}##{stream_name}_retarget"):
            v.show_retarget = not v.show_retarget
        if imgui.is_item_hovered():
            imgui.set_tooltip("Change source: scan + reconnect to a different LSL stream.")


def _render_rms_sliders(stream_name: str, v: ViewerState, fs: float) -> None:
    """The RMS-envelope window + hop sliders, shown only for the rms_env mode.

    Hop is capped at ``min(100 ms, window)`` so windows overlap or abut rather
    than leave gaps; the cap is re-applied every frame in case the window
    slider was dragged below the current hop.
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


def _render_signal_group(stream_name: str, v: ViewerState, fs: float) -> None:
    """Mains notch and the visual-only display transform."""
    notch_vals = [0, 50, 60]
    n_idx = notch_vals.index(v.mains_notch) if v.mains_notch in notch_vals else 0
    imgui.align_text_to_frame_padding()
    imgui.text("Notch")
    imgui.same_line()
    imgui.push_item_width(84)
    n_changed, n_new = imgui.combo(f"##{stream_name}_notch", n_idx, ["Off", "50 Hz", "60 Hz"])
    imgui.pop_item_width()
    if n_changed:
        v.mains_notch = notch_vals[n_new]
    if imgui.is_item_hovered():
        imgui.set_tooltip(
            "Remove mains-line hum (50 / 60 Hz + harmonics) from the display —\n"
            "visual only, applied before the View transform. Recording is untouched."
        )
    imgui.same_line()

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

    if v.display_filter == "rms_env":
        imgui.same_line()
        _render_rms_sliders(stream_name, v, fs)


def _render_scale_group(stream_name: str, v: ViewerState) -> None:
    """Y-scaling policy: Auto/Manual + Rescale + Per channel, and the manual range.

    `Per channel` is the scaling BASIS (shared axis vs one lane per channel);
    `Auto`/`Manual` is the adaptation policy and applies to either basis. Only
    the shared numeric min/max fields are context-specific.
    """
    per_ch = v.per_channel_scale
    if v.scale_mode not in ("auto", "manual"):
        v.scale_mode = "auto"

    scale_i = segmented(
        f"{stream_name}_scale", ["Auto", "Manual"], 1 if v.scale_mode == "manual" else 0
    )
    v.scale_mode = "manual" if scale_i == 1 else "auto"
    if imgui.is_item_hovered():
        imgui.set_tooltip(
            "Y-axis scale — Auto: eases to the signal range (~5 s). Manual: holds it.\n"
            "Per channel on: applied to each channel's own lane instead of one shared range."
        )

    # One-shot "Fit & lock". The basis is recorded on the click so a same-frame
    # Per channel toggle can't misapply it.
    imgui.same_line()
    if imgui.button(f"Rescale##{stream_name}_rescale"):
        v.rescale_pending = "per_channel" if per_ch else "shared"
    if imgui.is_item_hovered():
        imgui.set_tooltip(
            ("Fit each channel to its own visible range" if per_ch else "Fit one shared range")
            + " and lock to Manual.\nClick again any time the trace goes off-scale."
        )

    imgui.same_line()
    ch_pc, pc = imgui.checkbox(f"Per channel##{stream_name}_perch", v.per_channel_scale)
    if ch_pc:
        v.per_channel_scale = pc
    if imgui.is_item_hovered():
        imgui.set_tooltip(
            "Normalize each enabled channel into its own lane.\n"
            "Trace heights are then NOT comparable between channels."
        )

    if per_ch:
        if v.scale_mode == "manual":  # no 16-field editor — just a small locked-count status
            imgui.same_line()
            imgui.text_disabled(f"{len(v.pc_ranges)} locked")
        return
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

    Transient widget state that must survive across frames but doesn't belong
    on the shared `ViewerState`; same per-stream-name dict pattern as
    `_scan.py`'s `_ScanState`.
    """

    drag: _DragSession = field(default_factory=_DragSession)
    last_clicked: int = -1
    # `v.active_channels_key` as of the last frame this grid was rendered.
    # `render_channel_controls` compares it to drop the shift-click anchor on a
    # stream/channel-count change, so a range can't resolve against the new
    # stream's out-of-range channel indices.
    last_key: tuple[str, int] | None = None
    # Whether the floating channel-grid window is open. Driven by the compact
    # bar's `[Edit…]` button and by the window's own title-bar close button.
    show_grid: bool = False


_grid_ui: dict[str, _GridUIState] = {}


def render_channel_controls(
    stream_name: str,
    stream: Stream,
    v: ViewerState,
    n_channels: int,
    scope: list[int] | None = None,
) -> tuple[set[int], list[str] | None, int]:
    """Render the compact channel bar, and mutate `v.channels` from user input.

    The bar is always drawn inline; the spatial toggle-grid renders only when
    `ui.show_grid` is set, in its own floating window (`render_grid_window`).
    `hovered_ch` is -1 whenever that window is closed.

    `resolve_enabled` (in `_state.py`) owns initializing `v.channels` before
    this runs each frame; this function only reads/mutates the existing
    selection, never (re)seeds it.
    """
    enabled = v.channels
    ch_names = stream.info.channel_names if stream.info else None
    channel_grids = stream.info.channel_grids if stream.info else None
    if scope is None:
        scope = list(range(n_channels))
    layout = normalize_layout(channel_grids, n_channels, scope)
    ui = _grid_ui.setdefault(stream_name, _GridUIState())
    if ui.last_key != v.active_channels_key:
        ui.last_clicked = -1
        # Disarm any in-flight drag: its snapshot and origin cell belong to the
        # previous stream/scope and would apply a stale selection to the new one.
        ui.drag = _DragSession()
        ui.last_key = v.active_channels_key

    # The bar itself is drawn by `render_controls`, inline in the scale row.
    hovered_ch = -1
    if ui.show_grid:
        hovered_ch = render_grid_window(stream_name, layout, enabled, ch_names, ui)

    # Resolve on mouse-up even if the window closed mid-drag, or `ui.drag`
    # stays armed forever.
    _finalize_drag(ui, enabled)

    return enabled, ch_names, hovered_ch


def render_channel_bar(
    stream_name: str,
    ui: _GridUIState,
    enabled: set[int],
    scope: list[int],
) -> None:
    """Render the always-inline, one-line channel bar.

    `Channels {enabled}/{total}` + the global All/None/Invert ops + `[Edit…]`,
    which toggles the floating grid window (`ui.show_grid`).

    Every op is bounded by `scope` — the columns this viewer may show — so the
    total, All and Invert describe the panel's own channels rather than the
    whole stream's. An unscoped viewer passes every channel.
    """
    imgui.text(f"Channels {len(enabled)}/{len(scope)}")
    imgui.same_line()
    if imgui.small_button(f"All##{stream_name}_bar_all"):
        enabled.clear()
        enabled.update(scope)
    imgui.same_line()
    if imgui.small_button(f"None##{stream_name}_bar_none"):
        enabled.clear()
    imgui.same_line()
    if imgui.small_button(f"Invert##{stream_name}_bar_invert"):
        # Complement *within the scope*, not `reduce_selection`'s XOR: XOR keeps
        # out-of-scope members of `enabled`, smuggling a foreign channel back in.
        new_enabled = set(scope) - enabled
        enabled.clear()
        enabled.update(new_enabled)
    imgui.same_line()

    # Highlight the toggle while the grid window is open.
    was_open = ui.show_grid
    if was_open:
        push_selected()
    # small_button, not button, so it lines up with the All/None/Invert pills.
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

    A real `imgui.begin`/`imgui.end` window, closable via the title-bar `[x]`
    (which clears `ui.show_grid`) — not a `begin_popup`, which auto-closes on
    any click outside its bounds and would abort a rectangle drag the instant
    it strays past the edge.
    """
    # With multi-viewport on (desktop default), open the grid as its own native
    # OS window: a NoAutoMerge window class keeps it separate even when dragged
    # back over the app, positioned just inside the main window so it opens
    # on-screen. With viewports off it stays a normal in-app floating window.
    if imgui.get_io().config_flags & imgui.ConfigFlags_.viewports_enable.value:
        wc = imgui.WindowClass()
        wc.viewport_flags_override_set = imgui.ViewportFlags_.no_auto_merge
        imgui.set_next_window_class(wc)
        mv = imgui.get_main_viewport()
        imgui.set_next_window_pos(
            imgui.ImVec2(mv.pos.x + 100.0, mv.pos.y + 100.0), imgui.Cond_.first_use_ever
        )
    cell = _grid_cell_size()
    n_cols = grid_arrangement(len(layout))
    imgui.set_next_window_size(
        _grid_window_size(layout, cell, n_cols), imgui.Cond_.first_use_ever
    )
    visible, still_open = imgui.begin(
        f"Channel selection — {stream_name}##{stream_name}_grid_window", True
    )
    hovered_ch = -1
    # `normalize_layout` already scope-restricted the layout, so its columns are
    # exactly the bound a shift-click range must respect.
    allowed = {c for g in layout for c in g.columns}
    try:
        if visible:
            # Tile the grids near-square, n_cols per row: each grid is a
            # `begin_group`ed block so `same_line` places the next to its right.
            # `render_grid` reads its own absolute cursor origin, so drag
            # hit-testing works wherever the block lands.
            for grid_idx, grid in enumerate(layout):
                if grid_idx % n_cols != 0:
                    imgui.same_line(0.0, cell)  # one-cell gap between grid columns
                imgui.begin_group()
                hovered_ch = render_grid(
                    stream_name, grid_idx, grid, enabled, ch_names, ui, cell, hovered_ch, allowed
                )
                imgui.end_group()
    finally:
        imgui.end()

    if not still_open:
        ui.show_grid = False
    return hovered_ch


def _grid_cell_size() -> float:
    """Cell edge length for the floating grid window.

    Large enough that a 3-digit channel index (``"255"``) fits centered
    without overflow.
    """
    return imgui.get_frame_height() * 1.6


def _grid_window_size(layout: list[ChannelGrid], cell: float, n_cols: int) -> imgui.ImVec2:
    """First-open size for the grid window, fit to the tiled grid blocks.

    Sized so an ``n_cols``-wide tiling opens fully visible, capped to a
    reasonable on-screen size; the window stays resizable afterwards.
    """
    n = len(layout)
    if n == 0:
        return imgui.ImVec2(520.0, 420.0)
    n_rows = ceil(n / n_cols)
    style = imgui.get_style()
    step_x = cell + style.item_spacing.x
    step_y = cell + style.item_spacing.y
    header = imgui.get_frame_height() * 1.4  # per-grid label + All/None row
    w_cells = max((len(g.cells[0]) for g in layout if g.cells and g.cells[0]), default=1)
    h_cells = max((len(g.cells) for g in layout if g.cells), default=1)
    grid_w = w_cells * step_x
    grid_h = h_cells * step_y + header
    win_w = n_cols * grid_w + (n_cols - 1) * cell + style.window_padding.x * 2 + 20.0
    win_h = n_rows * grid_h + (n_rows - 1) * step_y + style.window_padding.y * 2 + 20.0
    return imgui.ImVec2(min(win_w, 1500.0), min(win_h, 950.0))


def render_grid(
    stream_name: str,
    grid_idx: int,
    grid: ChannelGrid,
    enabled: set[int],
    ch_names: list[str] | None,
    ui: _GridUIState,
    cell: float,
    hovered_ch: int,
    allowed: set[int] | None = None,
) -> int:
    """Render one grid's header + cells; returns the updated `hovered_ch`.

    `allowed` is forwarded to `render_cell` so a shift-click range cannot
    escape this viewer's scope (``None`` = unrestricted).
    """
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
                allowed,
            )

    # Live rectangle update: recompute from the mouse-down snapshot each frame,
    # hit-testing the cursor against this frame's grid geometry. Item hover is
    # unusable here — ImGui suppresses it while the origin cell is active.
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

    Purely geometric, so it does not rely on per-item hover (which ImGui
    suppresses for non-active items during a drag). Out-of-range results are
    safe: `rect_to_channels` clamps them to the grid bounds.

    Column stride is `cell + spacing_x`, row stride `cell + spacing_y`. The two
    axes use ImGui's independent `item_spacing.x`/`.y` and must not be
    conflated: a single shared `spacing` drifts the vertical hit-test whenever
    `x != y`, as it does with this app's theme.
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

    Uses the theme's plain text color, not the per-channel accent, so the number
    stays legible over both the enabled cell's tinted fill and the disabled
    cell's hollow background. The reduced font size (`push_font(None, ...)`, the
    imgui-bundle idiom for a one-off size) keeps a 3-digit index from crowding
    the cell.
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
    allowed: set[int] | None = None,
) -> int:
    """Render one channel cell; returns the updated `hovered_ch`.

    `allowed` bounds a shift-click range selection to the columns this viewer
    may show (``None`` = unrestricted).
    """
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
        # Hollow border: an on/off cue beyond color alone (filled dot vs. none).
        border = imgui.color_convert_float4_to_u32(hairline(0.6))
        dl.add_rect(p_min, p_max, border, rounding=rounding)

    _draw_cell_label(dl, p_min, p_max, ch)

    if imgui.is_item_hovered():
        hovered_ch = ch
        name = ch_names[ch] if ch_names and ch < len(ch_names) else f"ch{ch}"
        imgui.set_tooltip(f"{grid_label} · col {ch} · {name}")
        # Hover outline from the text slot, not literal white — white on white is
        # invisible on the light theme.
        hi = primary()
        highlight = imgui.color_convert_float4_to_u32(imgui.ImVec4(hi.x, hi.y, hi.z, 0.8))
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
            # The span is numeric, but the selection must not be: a sparse scope
            # (or a grid with holes) would otherwise pick up channels between the
            # endpoints that this viewer may not show at all.
            span = range(lo, hi + 1) if allowed is None else [c for c in range(lo, hi + 1) if c in allowed]
            new_enabled = reduce_selection(enabled, "add", span)
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
