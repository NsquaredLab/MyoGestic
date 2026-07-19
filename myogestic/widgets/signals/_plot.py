from __future__ import annotations

import time as _time
from typing import TYPE_CHECKING

import numpy as np
from imgui_bundle import imgui, implot

from myogestic.widgets.common import PALETTE
from myogestic.widgets.signals._state import minmax_grid_all_shared_x, resolve_decimation_target

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import Stream
    from myogestic.widgets.signals._state import SignalFrame, ViewerState


def render_plot(
    ctx: Context,
    stream_name: str,
    stream: Stream,
    v: ViewerState,
    frame: SignalFrame,
    channel_ranges: dict[int, tuple[float, float]] | None,
    enabled: set[int],
    ch_names: list[str] | None,
    hovered_ch: int,
    size: tuple[float, float],
    channel_height: float,
) -> None:
    # Scale off the trace that is actually drawn (`frame.data`), not the raw
    # window — so an RMS envelope fills its lane instead of being dwarfed by
    # the raw amplitude, and warm-up/dropout NaNs are ignored.
    channel_height = resolve_channel_height(frame.data, channel_height, v)
    if v.per_channel_scale:
        channel_ranges = resolve_channel_ranges(frame.data, frame.channel_map)
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
        # Plot pixel width is only known once the plot is live — size the
        # decimation target off it (a few points per pixel) instead of a
        # fixed budget, so draw cost tracks what's actually on screen
        # regardless of window length / sample rate / channel count.
        n_out = resolve_decimation_target(implot.get_plot_size().x, v)
        v.last_decim_n_out = n_out
        # Decimate every enabled column at once — `xs_shared` is the shared
        # (relative-to-window-start) x-axis every channel's trace and the
        # label markers align to; `ys_all[i]` is channel `frame.channel_map[i]`'s
        # own min/max envelope over that same axis (see
        # `minmax_grid_all_shared_x`'s docstring: no cross-channel index
        # union, so per-channel draw cost stays bounded regardless of how
        # many other channels are enabled).
        xs_shared, ys_all = minmax_grid_all_shared_x(
            frame.trace_ts, frame.data, n_out, v.window, x_origin=frame.x_origin
        )
        # Iterate `frame.channel_map` (not `sorted(enabled)`) — it's the
        # authoritative record of which real channel landed in which column
        # of the enabled-only `data` array (and therefore which row of
        # `ys_all`).
        for col_idx, ch in enumerate(frame.channel_map):
            plot_channel(
                stream_name,
                v,
                channel_ranges,
                ch_names,
                hovered_ch,
                channel_height,
                xs_shared,
                ys_all,
                col_idx,
                ch,
            )
        render_markers(ctx, stream_name, v, frame.ts_win)
        implot.end_plot()


def resolve_channel_height(
    plotted: np.ndarray,
    channel_height: float,
    v: ViewerState | None = None,
) -> float:
    """Lane height for the shared-axis layout, derived from the drawn trace.

    `plotted` is the enabled-only trace (`frame.data`) — raw visible window in
    normal modes, or the RMS envelope in `rms_env` mode — so the layout tracks
    what is actually on screen. Non-finite warm-up/dropout values are ignored.
    """
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
    # Auto mode: derive from the visible trace so stale spikes in the raw
    # ring cannot flatten the live trace.
    if plotted.size == 0:
        return 1.0
    finite = plotted[np.isfinite(plotted)]
    if finite.size == 0:
        return 1.0
    data_range = float(finite.max()) - float(finite.min())
    return data_range * 1.2 if data_range > 0 else 1.0


def resolve_channel_ranges(
    plotted: np.ndarray,
    channel_map: list[int],
) -> dict[int, tuple[float, float]]:
    """Per-channel `(min, max)` of the drawn trace, keyed by real channel index.

    `plotted[:, col]` is channel `channel_map[col]` (the enabled-only compaction
    used everywhere the plot draws); non-finite values are dropped.
    """
    ranges: dict[int, tuple[float, float]] = {}
    if plotted.size == 0:
        return ranges
    for col, ch in enumerate(channel_map):
        finite = plotted[:, col][np.isfinite(plotted[:, col])]
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
    channel_ranges: dict[int, tuple[float, float]] | None,
    ch_names: list[str] | None,
    hovered_ch: int,
    channel_height: float,
    xs_shared: np.ndarray,
    ys_all: np.ndarray,
    col_idx: int,
    ch: int,
) -> None:
    """Plot one trace, reading its already-decimated row out of `ys_all`.

    `xs_shared` / `ys_all` come from one `minmax_grid_all_shared_x` call in
    `render_plot`, covering every enabled column at once — this function no
    longer decimates anything itself. `col_idx` selects both the row of
    `ys_all` (`frame.channel_map[col_idx] == ch`) and the vertical lane
    offset; color/label/spec/range lookups still key off `ch`, the real
    channel index, against full-width tables (`ch_names`, `v.specs`,
    `PALETTE`, `channel_ranges`).
    """
    col_ch = ys_all[col_idx]
    xs = xs_shared

    offset = -col_idx * channel_height
    if v.per_channel_scale:
        ch_data = np.asarray(col_ch, dtype=np.float64)
        if channel_ranges is not None and ch in channel_ranges:
            ch_min, ch_max = channel_ranges[ch]
        elif ch_data.size:
            ch_min = float(ch_data.min())
            ch_max = float(ch_data.max())
        else:
            ch_min = ch_max = 0.0
        ch_range = ch_max - ch_min
        if ch_range > 1e-12:
            ys = (ch_data - 0.5 * (ch_min + ch_max)) / ch_range * (channel_height * 0.8) + offset
        else:
            ys = np.full_like(ch_data, offset)
        ys = np.ascontiguousarray(ys, dtype=np.float64)
    else:
        ys = np.ascontiguousarray(col_ch * v.gain + offset, dtype=np.float64)
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


#: How often `render_footer` recomputes the per-channel diagnostics readout.
#: The values change slowly and are only a visual sanity check, so refreshing
#: at ~10 Hz instead of every frame keeps a wide/high-rate window from paying
#: the O(window_samples * n_channels) scan on every single frame.
_STATS_REFRESH_S = 0.1


def stats_need_recompute(
    cache: tuple[list[int], np.ndarray, np.ndarray, np.ndarray] | None,
    valid_channels: list[int],
    now: float,
    last_t: float,
) -> bool:
    """Whether the throttled footer stats must be recomputed this frame.

    Recompute when there is no cache, when the enabled-channel set changed
    (so a toggle updates immediately), or when `_STATS_REFRESH_S` has elapsed
    since the cached values were computed. Otherwise the cached values stand.
    """
    return cache is None or cache[0] != valid_channels or (now - last_t) >= _STATS_REFRESH_S


def channel_diagnostics(
    data_win: np.ndarray,
    valid_channels: list[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-channel `(rms, pp, mean)` over the raw window, one vectorized pass.

    `valid_channels` are real channel indices into `data_win`'s columns
    (ascending). The three arrays are aligned to `valid_channels` order;
    NaN-propagating, matching the old per-channel readout.

    Cost here is dominated by memory, not arithmetic: at 256 ch / 5 s /
    10 kHz a naive ``data_win[:, valid]`` fancy-index gather of every column
    is ~43 ms on its own (and ``cols * cols`` allocates a second full
    window). So skip the gather entirely when every channel is enabled, and
    fold the sum-of-squares into one ``einsum`` pass with no temporary —
    ~57 ms → ~7 ms for that worst case.
    """
    n = data_win.shape[0]
    if n == 0 or not valid_channels:
        z = np.zeros(len(valid_channels))
        return z, z, z
    # `valid_channels` is sorted, unique, and bounded by the column count, so
    # a length match means it is exactly every column — use `data_win`
    # directly and pay no gather. Only a real subset needs the copy (and then
    # it is proportionally small).
    cols = data_win if len(valid_channels) == data_win.shape[1] else data_win[:, valid_channels]
    # Sum of squares in one fused pass, accumulated in float64 — no `cols*cols`
    # temporary, and more accurate than a float32 running sum over a long window.
    ssq = np.einsum("ij,ij->j", cols, cols, dtype=np.float64)
    total = cols.sum(axis=0, dtype=np.float64)
    rms_all = np.sqrt(ssq / n)
    mean_all = total / n
    pp_all = cols.max(axis=0) - cols.min(axis=0)
    return rms_all, pp_all, mean_all


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

    # Report the points-per-channel actually drawn. In rms_env mode the trace
    # is the *sparse* RMS envelope (`frame.trace_ts`), already ~window/hop
    # points and never decimated — so describe it as such rather than as a
    # raw→MinMax reduction of the (undrawn) raw window. Otherwise: decimation
    # happened once for every enabled channel inside the plot loop that already
    # ran this frame; `v.last_decim_n_out` is that call's plot-width-derived
    # target (stashed on `v` since this runs after `end_plot()`), and every
    # channel shares the same raw window length so a single `raw_len > n_out`
    # check tells us whether it kicked in.
    if v.display_filter == "rms_env":
        pts_per_ch = len(frame.trace_ts)
        display_tag = "RMS env"
    else:
        raw_len = len(frame.data_win)
        n_out = v.last_decim_n_out or raw_len
        is_decimated = raw_len > n_out
        pts_per_ch = min(raw_len, n_out) if is_decimated else raw_len
        display_tag = "raw" if not is_decimated else f"MinMax {raw_len}->{pts_per_ch}"

    imgui.text_colored(
        imgui.ImVec4(0.5, 0.5, 0.5, 1.0),
        f"{fps:.0f} fps ({avg_ms:.1f} ms) | "
        f"fs={stream.info.fs:.0f} Hz | "
        f"{frame.n_channels} ch | "
        f"buf {fill_pct:.0f}% | "
        f"{pts_per_ch} pts/ch" + f" ({display_tag})" + paused_tag,
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

    valid_channels = [ch for ch in sorted(enabled) if ch < frame.data_win.shape[1]]
    if not valid_channels:
        return
    # The stats scan the *raw* (undecimated) window — O(window_samples *
    # n_channels), tens of ms at a high sample rate / wide window / many
    # channels. It is a slowly-changing readout, so recompute at most every
    # `_STATS_REFRESH_S` (or immediately when the enabled set changes) and
    # render the cached values on the frames in between, instead of paying
    # the full scan every frame.
    cache = v.stats_cache
    if stats_need_recompute(cache, valid_channels, frame.frame_start, v.stats_last_t):
        rms_all, pp_all, mean_all = channel_diagnostics(frame.data_win, valid_channels)
        v.stats_cache = (valid_channels, rms_all, pp_all, mean_all)
        v.stats_last_t = frame.frame_start
    else:
        _, rms_all, pp_all, mean_all = cache

    for i, ch in enumerate(valid_channels):
        name = ch_names[ch] if ch_names and ch < len(ch_names) else f"ch{ch}"
        imgui.text_colored(
            imgui.ImVec4(0.55, 0.58, 0.62, 1.0),
            f"  {name}: rms {rms_all[i]:.3f}  pp {pp_all[i]:.3f}  mean {mean_all[i]:+.3f}",
        )
