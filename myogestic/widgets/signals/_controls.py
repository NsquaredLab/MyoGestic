from __future__ import annotations

from typing import TYPE_CHECKING

from imgui_bundle import imgui

from myogestic.widgets.common import PALETTE
from myogestic.widgets.signals._scan import _scan_panel

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import Stream
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
            v.channels_initialized = False
            v.specs = []
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


def render_channel_controls(
    stream_name: str,
    stream: Stream,
    v: ViewerState,
    n_channels: int,
) -> tuple[set[int], list[str] | None, int]:
    if not v.channels_initialized or max(v.channels, default=-1) >= n_channels:
        v.channels = set(range(n_channels))
        v.specs = []
        v.channels_initialized = True
    enabled = v.channels
    ch_names = stream.info.channel_names if stream.info else None

    render_channel_presets(stream_name, enabled, n_channels)

    hovered_ch = -1
    for ch in range(n_channels):
        if ch > 0:
            imgui.same_line()
            if imgui.get_content_region_avail().x < 80:
                imgui.new_line()
        hovered_ch = render_channel_toggle(stream_name, enabled, ch_names, hovered_ch, ch)

    return enabled, ch_names, hovered_ch


def render_channel_presets(
    stream_name: str,
    enabled: set[int],
    n_channels: int,
) -> None:
    if n_channels <= 4:
        return
    if imgui.small_button(f"All##{stream_name}_all"):
        enabled.clear()
        enabled.update(range(n_channels))
    imgui.same_line()
    if imgui.small_button(f"None##{stream_name}_none"):
        enabled.clear()
    imgui.same_line()
    if imgui.small_button(f"Even##{stream_name}_even"):
        enabled.clear()
        enabled.update(range(0, n_channels, 2))
    imgui.same_line()
    if imgui.small_button(f"Odd##{stream_name}_odd"):
        enabled.clear()
        enabled.update(range(1, n_channels, 2))
    if n_channels >= 8:
        imgui.same_line()
        if imgui.small_button(f"First 8##{stream_name}_f8"):
            enabled.clear()
            enabled.update(range(8))


def render_channel_toggle(
    stream_name: str,
    enabled: set[int],
    ch_names: list[str] | None,
    hovered_ch: int,
    ch: int,
) -> int:
    is_on = ch in enabled
    color = PALETTE[ch % len(PALETTE)]
    if is_on:
        imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(color[0], color[1], color[2], 0.7))
    else:
        imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.3, 0.3, 0.3, 0.5))
    label = ch_names[ch] if ch_names and ch < len(ch_names) else f"ch{ch}"
    if imgui.button(f"{label}##{stream_name}_tog{ch}"):
        if is_on:
            enabled.discard(ch)
        else:
            enabled.add(ch)
    if imgui.is_item_hovered():
        hovered_ch = ch
    imgui.pop_style_color()
    return hovered_ch
