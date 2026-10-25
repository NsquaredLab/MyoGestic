from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import (
    PALETTE,
    hairline,
    mono_font,
    muted,
    panel_header,
    pop_selected,
    primary,
    push_selected,
    segmented,
    ui_px,
)
from myogestic.widgets.signals._channel_grid import (
    grid_arrangement,
    normalize_layout,
    rect_to_channels,
    reduce_selection,
)
from myogestic.widgets.signals._plot import render_footer
from myogestic.widgets.signals._scan import _scan_panel
from myogestic.widgets.signals._state import _DETAIL_FULL, _DETAIL_MIN, select_stream

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import ChannelGrid, Stream
    from myogestic.widgets.signals._state import SignalFrame, ViewerState


def _slider_label(text: str) -> None:
    """Put a muted label in the Display popup's shared control column."""
    left = imgui.get_cursor_pos_x()
    imgui.align_text_to_frame_padding()
    imgui.text_colored(muted(), text)
    imgui.same_line()
    imgui.set_cursor_pos_x(left + ui_px(80))
    imgui.set_next_item_width(-1)


def _button_width(label: str) -> float:
    """Measure a button using the current font and frame padding."""
    return imgui.calc_text_size(label).x + imgui.get_style().frame_padding.x * 2


def _toolbar_next(width: float) -> None:
    """Keep the next control beside this one only when the whole control fits."""
    imgui.same_line()
    if imgui.get_content_region_avail().x < width:
        imgui.new_line()


def _popup_button(label: str, widget_id: str, popup_id: str) -> None:
    """Open a popup, retaining the selected cue while it is open."""
    selected = imgui.is_popup_open(popup_id)
    if selected:
        push_selected()
    if imgui.button(f"{label}##{widget_id}"):
        imgui.open_popup(popup_id)
    if selected:
        pop_selected()


def render_controls(
    ctx: Context,
    stream_name: str,
    active_stream: str,
    stream: Stream | None,
    v: ViewerState,
    selectable: bool,
    enabled: set[int] | None = None,
    scope: list[int] | None = None,
    *,
    title: str | None = None,
    show_title: bool = True,
) -> None:
    """Render the title and right-aligned toolbar, wrapping only when necessary.

    Popup ids and every control use ``stream_name``, the viewer's widget id,
    rather than the stream it currently happens to display. Channel operations
    run before the plot so the frame contains exactly the selected columns.
    """
    connected = stream is not None and stream.status == "connected" and stream.info is not None
    enabled = v.channels if enabled is None else enabled
    scope = list(range(stream.info.n_channels)) if scope is None and connected else (scope or [])
    picker = selectable and len(ctx.streams) > 1
    retarget = picker and stream is not None and getattr(stream._source, "discover", None) is not None
    pause = f"{fa.ICON_FA_PLAY}  Resume" if v.paused else f"{fa.ICON_FA_PAUSE}  Pause"
    channels = f"{len(enabled)}/{len(scope)} ch {fa.ICON_FA_CHEVRON_DOWN}"
    display = f"{fa.ICON_FA_SLIDERS}  Display"
    chrome = fa.ICON_FA_ANGLES_UP if v.show_controls else fa.ICON_FA_ANGLES_DOWN
    sp = imgui.get_style().item_spacing.x
    view_width = ui_px(130)
    widths = []
    if v.show_controls:
        if picker:
            widths.append(ui_px(120))
        if retarget:
            widths.append(_button_width(fa.ICON_FA_ARROWS_ROTATE))
        if connected:
            widths.extend([
                _button_width(pause), view_width,
                _button_width("Auto") + _button_width("Manual") + ui_px(2),
                _button_width(channels), _button_width(display),
            ])
    if show_title:
        widths.append(_button_width(chrome))
    width = sum(widths) + sp * max(0, len(widths) - 1)
    avail = imgui.get_content_region_avail().x
    inline = avail >= width + imgui.calc_text_size(fa.ICON_FA_CHART_LINE).x + sp * 3
    source_in_title = show_title and v.show_controls and connected and picker and not inline
    source_width = ui_px(120) + (_button_width(fa.ICON_FA_ARROWS_ROTATE) + sp if retarget else 0)
    if source_in_title:
        # Source selection names the title; it can stay beside it when the
        # remaining controls need the second row.
        width -= source_width + sp
    if connected and v.show_controls and width > avail:
        # The fallback row must still fit: the transport glyph already names its
        # action, and the view combo can give some of its preview width back.
        icon = fa.ICON_FA_PLAY if v.paused else fa.ICON_FA_PAUSE
        width -= _button_width(pause) - _button_width(icon) + view_width - ui_px(90)
        pause, view_width = icon, ui_px(90)
    if show_title:
        reserve = source_width + sp if source_in_title else (width + sp if inline else 0.0)
        if inline or source_in_title:
            imgui.align_text_to_frame_padding()
        panel_header(title or f"SIGNAL · {active_stream}", fa.ICON_FA_CHART_LINE, reserve=reserve)
        if inline or source_in_title:
            imgui.same_line()
    if widths:
        # Measure after same_line: before it, avail describes the next whole row.
        avail = imgui.get_content_region_avail().x
        row_width = source_width if source_in_title else width
        if avail > row_width:
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + avail - row_width)

    if v.show_controls:
        if picker:
            names = list(ctx.streams)
            cur = names.index(active_stream) if active_stream in names else 0
            imgui.set_next_item_width(ui_px(120))
            changed, idx = imgui.combo(f"##{stream_name}_sel", cur, names)
            if changed:
                select_stream(v, names[idx])
            if retarget or (not source_in_title and (connected or show_title)):
                imgui.same_line()
        if retarget:
            selected = v.show_retarget
            if selected:
                push_selected()
            if imgui.button(f"{fa.ICON_FA_ARROWS_ROTATE}##{stream_name}_retarget"):
                v.show_retarget = not v.show_retarget
            if selected:
                pop_selected()
            imgui.set_item_tooltip("Change source: scan + reconnect to a different LSL stream.")
            if not source_in_title and (connected or show_title):
                imgui.same_line()
        if connected:
            if source_in_title:
                avail = imgui.get_content_region_avail().x
                if avail > width:
                    imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + avail - width)
            _render_transport(stream_name, v, pause)
            _toolbar_next(view_width)
            _render_signal_group(stream_name, v, view_width)
            _toolbar_next(_button_width("Auto") + _button_width("Manual") + ui_px(2))
            _render_scale_group(stream_name, v)
            _toolbar_next(_button_width(channels))
            _popup_button(channels, f"{stream_name}_channels", f"{stream_name}_channels_popup")
            _toolbar_next(_button_width(display))
            _popup_button(display, f"{stream_name}_display", f"{stream_name}_display_popup")
            if show_title:
                _toolbar_next(_button_width(chrome))
    if show_title:
        selected = not v.show_controls
        if selected:
            push_selected()
        if imgui.small_button(f"{chrome}##{stream_name}_chrome"):
            v.show_controls = not v.show_controls
        if selected:
            pop_selected()
        imgui.set_item_tooltip("Show controls and footer" if selected else "Hide controls and footer")

    if v.show_controls and connected:
        if imgui.begin_popup(f"{stream_name}_channels_popup"):
            ui = _grid_ui.setdefault(stream_name, _GridUIState())
            render_channel_bar(stream_name, ui, enabled, scope)
            imgui.end_popup()
        if v.show_retarget and picker:
            _scan_panel(active_stream, stream)
    # Keep the cost guard alive even while Display is closed or chrome is folded.
    if connected and v.window * stream.info.fs * max(len(enabled), 1) > _ONE_TO_ONE_MAX_POINTS:
        v.one_to_one = False


def render_display_popup(
    stream_name: str,
    stream: Stream,
    v: ViewerState,
    frame: SignalFrame | None,
    enabled: set[int],
    show_diagnostics: bool,
) -> None:
    """Draw display settings and detailed statistics outside the plot's layout.

    Called after plotting so the footer describes the samples actually drawn.
    Display edits take effect on the next frame, like plot navigation itself.
    """
    imgui.set_next_window_size(imgui.ImVec2(ui_px(560), 0), imgui.Cond_.appearing)
    if not imgui.begin_popup(f"{stream_name}_display_popup"):
        return
    fs = stream.info.fs if stream.info else 0.0
    panel_header("Time")
    _slider_label("Window")
    changed, value = imgui.slider_float(
        f"##{stream_name}_win", v.window, 0.1, getattr(stream, "_buffer_seconds", 60.0), "%.1f s"
    )
    if changed:
        v.window = value
    imgui.set_item_tooltip("How much history the scope shows, in seconds.")
    _slider_label("Detail")
    imgui.set_next_item_width(-(_button_width("1:1") + imgui.get_style().item_spacing.x))
    changed, value = imgui.slider_float(
        f"##{stream_name}_detail", v.detail_factor / _DETAIL_FULL * 100,
        _DETAIL_MIN / _DETAIL_FULL * 100, 100.0, "%.0f%%"
    )
    if changed:
        v.detail_factor = value / 100 * _DETAIL_FULL
    imgui.set_item_tooltip(
        "Display density only — recording and analysis are unchanged.\n"
        "100% draws a few points per pixel; lower detail coarsens shape and timing."
    )
    imgui.same_line()
    _render_one_to_one(stream_name, v, fs, enabled, stream)

    panel_header("Amplitude")
    _slider_label("Gain")
    imgui.begin_disabled(v.per_channel_scale and v.scale_mode == "auto")
    changed, value = imgui.slider_float(
        f"##{stream_name}_gain", v.gain, 0.01, 100.0, "%.2fx", flags=imgui.SliderFlags_.logarithmic
    )
    if changed:
        v.gain = value
    imgui.end_disabled()
    _slider_label("Artifact")
    changed, value = imgui.slider_float(f"##{stream_name}_transient", v.transient_ms, 0, 40, "< %.0f ms")
    if changed:
        v.transient_ms = value
    imgui.set_item_tooltip(
        "Ignore shorter transients when fitting the y-scale.\n"
        "0 = plain min/max; keep this below your shortest real contraction."
    )
    _slider_label("Lanes")
    v.per_channel_scale = bool(segmented(
        f"{stream_name}_lanes", ["Shared", "Per channel"], int(v.per_channel_scale)
    ))
    imgui.set_item_tooltip("Per channel normalizes each lane; trace heights are then not comparable.")
    imgui.same_line()
    if imgui.button(f"Rescale now##{stream_name}_rescale"):
        v.rescale_pending = "per_channel" if v.per_channel_scale else "shared"
    imgui.set_item_tooltip("Fit the visible range and lock to Manual.")
    if v.scale_mode == "manual":
        if v.per_channel_scale:
            imgui.text_disabled(f"{len(v.pc_ranges)} locked")
        else:
            imgui.set_next_item_width(ui_px(100))
            _, v.y_min = imgui.input_float(f"min##{stream_name}_ymin", v.y_min, 0, 0, "%.2f")
            imgui.same_line()
            imgui.set_next_item_width(ui_px(100))
            _, v.y_max = imgui.input_float(f"max##{stream_name}_ymax", v.y_max, 0, 0, "%.2f")

    panel_header("Display filter")
    _slider_label("Notch")
    notch = [0, 50, 60]
    idx = notch.index(v.mains_notch) if v.mains_notch in notch else 0
    v.mains_notch = notch[segmented(f"{stream_name}_notch", ["Off", "50 Hz", "60 Hz"], idx)]
    imgui.push_style_color(imgui.Col_.text, muted())
    imgui.text_wrapped(
        "Changes the plot only. The recorded signal's notch is set where the device is connected."
    )
    imgui.pop_style_color()
    if v.display_filter == "rms_env":
        _render_rms_sliders(stream_name, v, fs)

    panel_header("Diagnostics")
    if frame is not None:
        font = mono_font()
        if font is not None:
            imgui.push_font(font, imgui.get_style().font_size_base)
        render_footer(stream_name, stream, v, frame, enabled,
                      stream.info.channel_names if stream.info else None, show_diagnostics)
        if font is not None:
            imgui.pop_font()
    else:
        imgui.text_disabled("Waiting for samples")
    imgui.end_popup()


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


def _render_transport(stream_name: str, v: ViewerState, label: str) -> None:
    """Freeze the display while acquisition continues."""
    selected = v.paused
    if selected:
        push_selected()
    if imgui.button(f"{label}##{stream_name}_pause"):
        v.paused = not v.paused
        if not v.paused:
            v.frozen_ts = None
            v.frozen_data = None
    if selected:
        pop_selected()
    imgui.set_item_tooltip("Freeze the display (acquisition continues).")


def _render_rms_sliders(stream_name: str, v: ViewerState, fs: float) -> None:
    """The RMS-envelope window + hop sliders, shown only for the rms_env mode.

    Hop is capped at ``min(100 ms, window)`` so windows overlap or abut rather
    than leave gaps; the cap is re-applied every frame in case the window
    slider was dragged below the current hop.
    """
    imgui.push_item_width(ui_px(104))
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


def _render_signal_group(stream_name: str, v: ViewerState, width: float) -> None:
    """Choose the visual transform in a combo labelled by its current view."""
    modes = ["none", "rectify", "dc_removal", "rms_env"]
    labels = ["Raw", "Rectified", "DC removed", "RMS envelope"]
    idx = modes.index(v.display_filter) if v.display_filter in modes else 0
    imgui.set_next_item_width(width)
    changed, idx = imgui.combo(f"##{stream_name}_df", idx, labels)
    if changed:
        v.display_filter = modes[idx]
    imgui.set_item_tooltip("View: visual-only transform — never affects recording or model input.")


def _render_scale_group(stream_name: str, v: ViewerState) -> None:
    """Choose the scale adaptation policy for shared or per-channel lanes."""
    idx = segmented(f"{stream_name}_scale", ["Auto", "Manual"], int(v.scale_mode == "manual"))
    v.scale_mode = "manual" if idx else "auto"
    imgui.set_item_tooltip(
        "Y-axis scale — Auto eases to the signal range; Manual holds it.\n"
        "Range and lane settings are in Display."
    )


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
    """Render the spatial channel window and mutate the existing selection.

    The bar lives in the Channels popup; the spatial toggle-grid renders only when
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

    # The bar itself is drawn by `render_controls`, in the Channels popup.
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
    """Render the channel action chips inside the Channels popup.

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
