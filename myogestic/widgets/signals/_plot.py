from __future__ import annotations

import time as _time
from typing import TYPE_CHECKING

import numpy as np
from imgui_bundle import imgui, implot

from myogestic.widgets.common import PALETTE

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import Stream
    from myogestic.widgets.signals._state import SignalFrame, ViewerState


def apply_display_filter(data: np.ndarray, mode: str, fs: float) -> np.ndarray:
    # Display filters are applied to the raw visible window in
    # build_signal_frame before M4 decimation. This shim keeps the existing
    # signal.py call sites from filtering the decimated envelope a second time.
    return data


def render_plot(
    ctx: Context,
    stream_name: str,
    stream: Stream,
    v: ViewerState,
    frame: SignalFrame,
    data: np.ndarray,
    channel_ranges: dict[int, tuple[float, float]] | None,
    enabled: set[int],
    ch_names: list[str] | None,
    hovered_ch: int,
    size: tuple[float, float],
    channel_height: float,
) -> None:
    xs = build_x_axis(frame.ts)
    channel_height = resolve_channel_height(frame.data_win, enabled, channel_height, v)
    if v.per_channel_scale:
        channel_ranges = resolve_channel_ranges(frame.data_win, enabled)
    ensure_specs(v, frame.n_channels)

    plot_w, plot_h = size
    if plot_h <= 0:
        plot_h = max(imgui.get_content_region_avail().y - 25, 50)

    if implot.begin_plot(
        f"{stream_name}##{stream_name}_viewer",
        imgui.ImVec2(plot_w, plot_h),
        flags=implot.Flags_.no_legend | implot.Flags_.no_title,
    ):
        setup_axes(v, enabled, channel_height)
        # Iterate `frame.channel_map` (not `sorted(enabled)`) — it's the
        # authoritative record of which real channel landed in which column
        # of the (enabled-only, decimated) `data` array.
        for col_idx, ch in enumerate(frame.channel_map):
            plot_channel(
                stream_name,
                v,
                data,
                channel_ranges,
                xs,
                ch_names,
                hovered_ch,
                channel_height,
                col_idx,
                ch,
            )
        render_markers(ctx, stream_name, v, frame.ts)
        implot.end_plot()


def build_x_axis(ts: np.ndarray) -> np.ndarray:
    if len(ts) > 1:
        return np.ascontiguousarray(ts - ts[0], dtype=np.float64)
    return np.array([0.0], dtype=np.float64)


def resolve_channel_height(
    data: np.ndarray,
    enabled: set[int],
    channel_height: float,
    v: ViewerState | None = None,
) -> float:
    if channel_height > 0:
        return channel_height
    if v is not None and v.per_channel_scale:
        # In per-channel mode every channel renormalises into a unit-height
        # lane, so the absolute amplitude no longer drives the layout.
        return 1.0
    if v is not None and v.scale_mode == "manual":
        # Manual mode: pin channel height to the user's range so the
        # lane spacing is perfectly stable, instead of recomputing it
        # from the visible data each frame (which causes per-frame
        # min/max ticks to wobble the channels vertically inside the
        # fixed axis).
        span = float(v.y_max - v.y_min)
        return span if span > 0 else 1.0
    # Auto mode: derive from the visible window so stale spikes in the raw
    # ring cannot flatten the live trace.
    d_min, d_max = np.inf, -np.inf
    for ch in enabled:
        if ch >= data.shape[1]:
            continue
        col = data[:, ch]
        if col.size == 0:
            continue
        d_min = min(d_min, float(np.min(col)))
        d_max = max(d_max, float(np.max(col)))
    data_range = d_max - d_min
    return data_range * 1.2 if data_range > 0 else 1.0


def resolve_channel_ranges(
    data: np.ndarray,
    enabled: set[int],
) -> dict[int, tuple[float, float]]:
    ranges: dict[int, tuple[float, float]] = {}
    if data.size == 0:
        return ranges
    for ch in sorted(enabled):
        if ch >= data.shape[1]:
            continue
        col = data[:, ch]
        finite = col[np.isfinite(col)]
        if finite.size == 0:
            continue
        ranges[ch] = (float(finite.min()), float(finite.max()))
    return ranges


def ensure_specs(v: ViewerState, n_channels: int) -> None:
    if len(v.specs) >= n_channels:
        return
    v.specs = []
    for ch in range(n_channels):
        c = PALETTE[ch % len(PALETTE)]
        s = implot.Spec()
        s.line_color = imgui.ImVec4(c[0], c[1], c[2], 0.9)
        s.line_weight = 1.0
        v.specs.append(s)


def setup_axes(
    v: ViewerState,
    enabled: set[int],
    channel_height: float,
) -> None:
    implot.setup_axis(implot.ImAxis_.x1)
    implot.setup_axis_limits(
        implot.ImAxis_.x1,
        0,
        v.window,
        implot.Cond_.always,  # type: ignore[attr-defined]
    )
    if v.scale_mode == "auto":
        implot.setup_axis(
            implot.ImAxis_.y1,
            flags=implot.AxisFlags_.auto_fit | implot.AxisFlags_.no_tick_labels,
        )
        return

    implot.setup_axis(implot.ImAxis_.y1, flags=implot.AxisFlags_.no_tick_labels)
    y_min, y_max = v.y_min, v.y_max
    n_enabled = max(1, len(enabled))
    axis_min = y_min - (n_enabled - 1) * channel_height
    axis_max = y_max
    if axis_min >= axis_max:
        axis_max = axis_min + 1e-6
    implot.setup_axis_limits(
        implot.ImAxis_.y1,
        axis_min,
        axis_max,
        implot.Cond_.always,  # type: ignore[attr-defined]
    )


def plot_channel(
    stream_name: str,
    v: ViewerState,
    data: np.ndarray,
    channel_ranges: dict[int, tuple[float, float]] | None,
    xs: np.ndarray,
    ch_names: list[str] | None,
    hovered_ch: int,
    channel_height: float,
    col_idx: int,
    ch: int,
) -> None:
    """Plot one trace.

    `data` is column-compacted to the enabled subset, so it must be indexed
    by `col_idx` (`data`'s own column position) — `ch` (the real channel
    index) is only for color/label/spec lookups against full-width tables
    (`ch_names`, `v.specs`, `PALETTE`, `channel_ranges`).
    """
    offset = -col_idx * channel_height
    if v.per_channel_scale:
        ch_data = np.asarray(data[:, col_idx], dtype=np.float64)
        if channel_ranges is not None and ch in channel_ranges:
            ch_min, ch_max = channel_ranges[ch]
        else:
            ch_min = float(ch_data.min())
            ch_max = float(ch_data.max())
        ch_range = ch_max - ch_min
        if ch_range > 1e-12:
            ys = (ch_data - 0.5 * (ch_min + ch_max)) / ch_range * (channel_height * 0.8) + offset
        else:
            ys = np.full_like(ch_data, offset)
        ys = np.ascontiguousarray(ys, dtype=np.float64)
    else:
        ys = np.ascontiguousarray(data[:, col_idx] * v.gain + offset, dtype=np.float64)
    label = ch_names[ch] if ch_names and ch < len(ch_names) else f"ch{ch}"
    spec = v.specs[ch]
    if hovered_ch >= 0:
        c = PALETTE[ch % len(PALETTE)]
        spec = implot.Spec()
        if ch == hovered_ch:
            spec.line_color = imgui.ImVec4(c[0], c[1], c[2], 1.0)
            spec.line_weight = 2.5
        else:
            spec.line_color = imgui.ImVec4(c[0], c[1], c[2], 0.15)
            spec.line_weight = 1.0
    implot.plot_line(f"{label}##{stream_name}", xs, ys, spec)


def render_markers(
    ctx: Context,
    stream_name: str,
    v: ViewerState,
    ts: np.ndarray,
) -> None:
    if not v.show_markers or ctx.session is None or len(ts) == 0:
        return

    t0 = float(ts[0])
    t_last = float(ts[-1])
    by_class: dict[int, list[float]] = {}
    for ev in ctx.session.label_track:
        if t0 <= ev.timestamp <= t_last:
            by_class.setdefault(ev.class_index, []).append(float(ev.timestamp - t0))
    for ci, xs_list in by_class.items():
        if ci < 0:
            color = imgui.ImVec4(0.7, 0.7, 0.7, 0.6)
        else:
            c = PALETTE[ci % len(PALETTE)]
            color = imgui.ImVec4(c[0], c[1], c[2], 0.7)
        spec = implot.Spec()
        spec.line_color = color
        spec.line_weight = 1.5
        implot.plot_inf_lines(
            f"label_{ci}##{stream_name}_mark",
            np.array(xs_list, dtype=np.float64),
            spec,
        )


def render_footer(
    stream_name: str,
    stream: Stream,
    v: ViewerState,
    frame: SignalFrame,
    enabled: set[int],
    ch_names: list[str] | None,
    show_diagnostics: bool,
) -> None:
    # Caller only renders the footer for a connected stream (viewer.py guards
    # `stream.info is None` and returns early), so info is non-None here.
    assert stream.info is not None
    frame_dt = _time.perf_counter() - frame.frame_start
    v.fps.append(frame_dt)
    if len(v.fps) > 60:
        v.fps.pop(0)
    avg_ms = np.mean(v.fps) * 1000
    fps = 1000.0 / avg_ms if avg_ms > 0 else 0

    n_buf = stream._data.shape[0] if stream._data is not None else 0
    capacity = stream._data.maxlen if stream._data is not None else 0
    fill_pct = 100.0 * n_buf / capacity if capacity > 0 else 0.0
    paused_tag = "  ⏸ PAUSED" if v.paused else ""
    display_tag = "raw" if not frame.is_decimated else f"M4 {len(frame.data_win)}->{frame.n_points}"

    imgui.text_colored(
        imgui.ImVec4(0.5, 0.5, 0.5, 1.0),
        f"{fps:.0f} fps ({avg_ms:.1f} ms) | "
        f"fs={stream.info.fs:.0f} Hz | "
        f"{frame.n_channels} ch | "
        f"buf {fill_pct:.0f}% | "
        f"{frame.n_points} pts/ch" + f" ({display_tag})" + paused_tag,
    )

    imgui.same_line()
    changed, per_channel = imgui.checkbox(f"Per-Ch##{stream_name}_per_channel", v.per_channel_scale)
    if changed:
        v.per_channel_scale = per_channel
    if imgui.is_item_hovered():
        imgui.set_tooltip("Normalize each enabled channel into its own lane.")

    diag_on = v.show_diagnostics if v.show_diagnostics is not None else show_diagnostics
    imgui.same_line()
    if imgui.small_button(f"{'Hide' if diag_on else 'Show'} stats##{stream_name}_diag"):
        v.show_diagnostics = not diag_on
        diag_on = v.show_diagnostics
    if not diag_on or len(enabled) == 0:
        return

    for ch in sorted(enabled):
        if ch >= frame.data_win.shape[1]:
            continue
        col = frame.data_win[:, ch]
        rms = float(np.sqrt(np.mean(col * col))) if col.size else 0.0
        pp = float(col.max() - col.min()) if col.size else 0.0
        mean = float(col.mean()) if col.size else 0.0
        name = ch_names[ch] if ch_names and ch < len(ch_names) else f"ch{ch}"
        imgui.text_colored(
            imgui.ImVec4(0.55, 0.58, 0.62, 1.0),
            f"  {name}: rms {rms:.3f}  pp {pp:.3f}  mean {mean:+.3f}",
        )
