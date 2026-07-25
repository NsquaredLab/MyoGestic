from __future__ import annotations

import math
import time as _time
from typing import TYPE_CHECKING

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui, implot

from myogestic.widgets.common import PALETTE, ensure_implot_style, muted
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
    # Ease the auto y-range toward the data BEFORE deriving the lane height / axis limits from it
    # (no-op unless auto mode is active). `frame.frame_start` is this frame's perf_counter.
    update_auto_scale(v, frame.data, frame.channel_map, stream_name, frame.frame_start)
    channel_height = resolve_channel_height(frame.data, channel_height, v)
    if v.per_channel_scale:
        # Ease each lane's normalisation range (grow-fast/shrink-slow) so amplitudes don't breathe.
        channel_ranges = update_per_channel_ranges(
            v, frame.data, frame.channel_map, stream_name, frame.frame_start
        )
    else:
        v.pc_ease_t = 0.0  # snap per-channel ranges when it's next re-enabled
    ensure_specs(v, frame.n_channels)

    plot_w, plot_h = size
    if plot_h <= 0:
        plot_h = max(imgui.get_content_region_avail().y - 25, 50)

    ensure_implot_style()
    if implot.begin_plot(
        f"{stream_name}##{stream_name}_viewer",
        imgui.ImVec2(plot_w, plot_h),
        # no_mouse_text: the default readout's y is a lane-offset + gain (or
        # per-channel-normalized) number, not physical amplitude — misleading,
        # so suppress it until there's a real per-lane hover readout.
        flags=implot.Flags_.no_legend | implot.Flags_.no_title | implot.Flags_.no_mouse_text,
    ):
        setup_axes(v, enabled, channel_height, frame.channel_map, ch_names)
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
    if v is not None:
        # Manual AND (eased) auto both pin the lane height to `y_min/y_max` so the
        # spacing is perfectly stable, instead of recomputing it from the visible
        # data each frame (which wobbled the channels vertically). In auto,
        # `update_auto_scale` has already eased `y_min/y_max` toward the data range.
        span = float(v.y_max - v.y_min)
        return span if span > 0 else 1.0
    # No ViewerState (bare preview): derive from the visible trace.
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
    used everywhere the plot draws); non-finite values are dropped, and an all-non-finite
    column is omitted.

    Vectorized (axis-0 reductions, not a Python per-column loop) — this runs every frame in
    per-channel mode, where the loop cost dominated the frame at high channel counts.
    """
    ranges: dict[int, tuple[float, float]] = {}
    if plotted.size == 0:
        return ranges
    finite = np.isfinite(plotted)
    if finite.all():  # common live case: no copy, plain axis-0 min/max
        lo = plotted.min(axis=0)
        hi = plotted.max(axis=0)
    else:  # drop non-finite per element, then nan-aware reduce (all-nan column ⇒ nan ⇒ skipped)
        masked = np.where(finite, plotted, np.nan)
        with np.errstate(invalid="ignore"):
            lo = np.nanmin(masked, axis=0)
            hi = np.nanmax(masked, axis=0)
    ok = np.isfinite(lo)
    for col, ch in enumerate(channel_map):
        if ok[col]:
            ranges[ch] = (float(lo[col]), float(hi[col]))
    return ranges


#: Time-bin width (ms) for the duration-based robust range. Each bin contributes one min and one
#: max; a transient that fills fewer than the "ignore transients shorter than" budget of these bins
#: is dropped as an artifact.
_ROBUST_BIN_MS = 5.0


def robust_channel_ranges(
    data: np.ndarray,
    channel_map: list[int],
    transient_ms: float,
    window_s: float,
    display_filter: str,
    rms_window_ms: float,
    rms_hop_ms: float,
) -> dict[int, tuple[float, float]]:
    """Per-channel range that ignores transients shorter than ``transient_ms`` (movement artifacts).

    *Duration*, not amplitude, separates an artifact (a brief spike) from a contraction (a sustained
    burst) — they look alike by amplitude. The visible window is split into equal-time bins; each
    bin contributes one min and one max; the ``k`` most extreme bin maxima/minima (``k`` covering
    the transient budget) are dropped and the next extrema are the robust range. A 10 ms artifact
    fills ~2 bins (dropped); a 50 ms contraction fills ~11 (kept). Mode-aware: ``rectify`` /
    ``rms_env`` are one-sided (lower bound pinned to 0, only the top trimmed), and ``rms_env``'s
    envelope is already time-binned, so its own points are the bins with the RMS smear folded into
    ``k``. ``transient_ms == 0`` degrades to plain per-channel min/max.

    Cheap enough for the per-frame path: reshape + axis-1 min/max + one axis-0 partition (no
    full-window percentile). Falls back gracefully to min/max when there are too few bins.
    """
    n = len(data)
    if n == 0 or not channel_map:
        return {}
    one_sided = display_filter in ("rectify", "rms_env")
    if display_filter == "rms_env":
        highs = np.asarray(data)  # each envelope point ≈ one time bin (keep native dtype)
        lows = highs
        k = int(np.ceil((transient_ms + rms_window_ms) / max(rms_hop_ms, 1e-6)))
    else:
        bin_n = max(1, round(n * _ROBUST_BIN_MS / (window_s * 1000.0))) if window_s > 0 else 1
        n_bins = max(1, n // bin_n)
        head = np.asarray(data[: n_bins * bin_n]).reshape(n_bins, bin_n, -1)  # view, no copy/cast
        if np.isfinite(head).all():  # common live case: plain (fast) min/max, no nan bookkeeping
            highs = head.max(axis=1)  # (n_bins, n_ch)
            lows = head.min(axis=1)
        else:
            with np.errstate(invalid="ignore"):
                highs = np.nanmax(head, axis=1)
                lows = np.nanmin(head, axis=1)
        bin_ms = window_s * 1000.0 / n_bins if window_s > 0 else _ROBUST_BIN_MS
        k = int(np.ceil(transient_ms / max(bin_ms, 1e-6))) + (1 if transient_ms > 0 else 0)
    # A NaN bin must not corrupt the order statistic: park it at the non-selected end.
    highs = np.where(np.isfinite(highs), highs, -np.inf)
    lows = np.where(np.isfinite(lows), lows, np.inf)
    n_bins = highs.shape[0]
    k = max(0, min(k, (n_bins - 1) // 2))  # always keep ≥1 bin per side (→ min/max when few bins)
    hi_idx, lo_idx = n_bins - 1 - k, k
    hi = np.partition(highs, hi_idx, axis=0)[hi_idx]  # (k+1)-th largest bin-max per channel
    lo = np.zeros_like(hi) if one_sided else np.partition(lows, lo_idx, axis=0)[lo_idx]
    ranges: dict[int, tuple[float, float]] = {}
    for col, ch in enumerate(channel_map):
        if np.isfinite(hi[col]) and np.isfinite(lo[col]):
            ranges[ch] = (float(lo[col]), float(hi[col]))
    return ranges


#: Auto-scale CONTRACTION settle time (s) — how long to shrink the range when the signal
#: quietens (~95% at 3·tau). Slow, so the range never jitters downward. Expansion is INSTANT
#: (the bound snaps out to contain a new peak), so nothing is ever clipped while it catches up.
_SCALE_EASE_S = 5.0


def update_auto_scale(
    v: ViewerState,
    data: np.ndarray,
    channel_map: list[int],
    stream_name: str,
    now: float,
) -> None:
    """Ease `v.y_min`/`v.y_max` toward the drawn data's padded range (auto mode only).

    Replaces ImPlot's per-frame `auto_fit` refit — which makes a variable signal zoom in/out
    constantly — with a **grow-fast / shrink-slow** ease toward the drawn window's gain-scaled
    global min/max: the range EXPANDS quickly (``_SCALE_EXPAND_S``) so a new peak/contraction is
    never clipped, and CONTRACTS slowly (``_SCALE_EASE_S``) so it never jitters downward.
    **Snaps** instead of easing on the first frame
    and whenever the context ``(active stream, channels, display filter, notch, gain)`` changes,
    so it never eases across an unrelated scale; a huge ``dt`` (e.g. after a pause) also snaps.
    No-op unless auto mode is active and per-channel scaling is off.
    """
    if v.scale_mode != "auto" or v.per_channel_scale:
        # Force a snap when auto resumes, so re-entering auto doesn't ease from stale/manual bounds.
        v.scale_ease_t = 0.0
        return
    # Artifact-robust range per channel, then take the UNION for the shared axis — never a global
    # scan (a contraction on one of many channels would be statistically drowned out). Gain-correct
    # (`plot_channel` draws `data * v.gain`).
    g = v.gain
    robust = robust_channel_ranges(
        data, channel_map, v.transient_ms, v.window, v.display_filter, v.rms_window_ms, v.rms_hop_ms
    )
    if not robust:
        return  # empty / all-NaN window: hold the current range
    lo = min(r[0] for r in robust.values()) * g
    hi = max(r[1] for r in robust.values()) * g
    if lo > hi:
        lo, hi = hi, lo
    span = hi - lo
    pad = span * 0.1 if span > 0 else 1.0
    target_lo, target_hi = lo - pad, hi + pad

    # Snap (don't ease) on the first frame or any change that alters the scale: which stream a
    # selectable viewer shows (`selected_stream`, not the stable widget id), the channel set, the
    # display filter, the mains notch, or the gain.
    key = (
        v.selected_stream or stream_name,
        tuple(channel_map),
        v.display_filter,
        v.mains_notch,
        g,
        v.rms_window_ms,
        v.rms_hop_ms,
        v.transient_ms,
    )
    if key != v.scale_ease_key or v.scale_ease_t <= 0.0:
        v.y_min, v.y_max = target_lo, target_hi  # snap: first frame / context change
    else:
        dt = max(0.0, now - v.scale_ease_t)  # backward clock ⇒ dt 0 ⇒ no move
        a = 1.0 - math.exp(-dt / (_SCALE_EASE_S / 3.0))  # contraction ease
        # Grow INSTANTLY (snap the bound out so a new peak never clips), shrink slowly (no jitter).
        v.y_max = target_hi if target_hi > v.y_max else v.y_max + a * (target_hi - v.y_max)
        v.y_min = target_lo if target_lo < v.y_min else v.y_min + a * (target_lo - v.y_min)
    v.scale_ease_key = key
    v.scale_ease_t = now


def update_per_channel_ranges(
    v: ViewerState,
    data: np.ndarray,
    channel_map: list[int],
    stream_name: str,
    now: float,
) -> dict[int, tuple[float, float]]:
    """Per-channel normalisation ranges (GAINED) for per-channel mode, keyed by real channel.

    `per_channel_scale` is the *basis*; `scale_mode` decides whether it adapts:

    - **Auto**: ease each channel's range grow-fast (snap out so a louder channel never overflows
      its lane) / shrink-slow (no per-frame breathing), snapping on the first frame / a
      newly-enabled channel / a context change (stream / channels / filter / notch / gain / rms).
    - **Manual**: hold the frozen ranges untouched — so a channel weakening, strengthening, or
      drifting stays visible against its captured reference. Only a *newly-enabled* channel (with
      no saved range) is initialised from its current data; existing ones never move.

    Ranges are stored **gained** (× `v.gain`): in Auto gain is inert (it cancels in `plot_channel`),
    but in Manual, changing gain magnifies the trace against the frozen reference. Returns the dict
    and stores it on `v.pc_ranges` (channels no longer drawn drop out).
    """
    g = v.gain
    args = (v.transient_ms, v.window, v.display_filter, v.rms_window_ms, v.rms_hop_ms)
    if v.scale_mode != "auto":  # MANUAL: hold frozen ranges; init only a newly-enabled channel
        need_init = any(ch not in v.pc_ranges for ch in channel_map)
        raw = robust_channel_ranges(data, channel_map, *args) if need_init else {}
        held: dict[int, tuple[float, float]] = {}
        for ch in channel_map:
            if ch in v.pc_ranges:
                held[ch] = v.pc_ranges[ch]
            elif ch in raw:
                lo, hi = raw[ch]
                held[ch] = (lo * g, hi * g)
        v.pc_ranges = held
        v.pc_ease_t = 0.0  # snap once when Auto resumes
        return held

    targets = robust_channel_ranges(data, channel_map, *args)
    key = (
        v.selected_stream or stream_name,
        tuple(channel_map),
        v.display_filter,
        v.mains_notch,
        g,
        v.rms_window_ms,
        v.rms_hop_ms,
        v.transient_ms,
    )
    snap = key != v.pc_ease_key or v.pc_ease_t <= 0.0
    dt = max(0.0, now - v.pc_ease_t)
    a = 1.0 - math.exp(-dt / (_SCALE_EASE_S / 3.0))  # contraction ease; expansion snaps instantly
    eased: dict[int, tuple[float, float]] = {}
    for ch, (r_lo, r_hi) in targets.items():
        t_lo, t_hi = r_lo * g, r_hi * g  # gained target
        prev = v.pc_ranges.get(ch)
        if snap or prev is None:  # first frame / context change / newly-enabled channel
            eased[ch] = (t_lo, t_hi)
        else:
            lo, hi = prev
            hi = t_hi if t_hi > hi else hi + a * (t_hi - hi)  # grow instantly, shrink slow
            lo = t_lo if t_lo < lo else lo + a * (t_lo - lo)
            eased[ch] = (lo, hi)
    v.pc_ranges = eased
    v.pc_ease_key = key
    v.pc_ease_t = now
    return eased


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
    channel_map: list[int],
    ch_names: list[str] | None,
) -> None:
    implot.setup_axis(implot.ImAxis_.x1, "Time (s)")
    implot.setup_axis_limits(
        implot.ImAxis_.x1,
        0,
        v.window,
        implot.Cond_.always,  # type: ignore[attr-defined]
    )

    if v.per_channel_scale:
        # Pin to the fixed unit-lane geometry (each lane fills ±0.4 around baselines stacked by
        # `channel_height` == 1.0). NOT `auto_fit`: while a channel's eased range contracts its
        # trace occupies less than its lane, and auto_fit would zoom to that and cancel the ease.
        implot.setup_axis(implot.ImAxis_.y1)
        n_enabled = max(1, len(enabled))
        implot.setup_axis_limits(
            implot.ImAxis_.y1,
            -0.5 - (n_enabled - 1) * channel_height,
            0.5,
            implot.Cond_.always,  # type: ignore[attr-defined]
        )
    else:
        # Auto AND manual apply the same fixed limits every frame; only the values differ —
        # auto's `y_min/y_max` are eased toward the data by `update_auto_scale`, manual's are held.
        # Pinning them each frame (instead of `auto_fit`) is what stops the per-frame zoom jitter.
        implot.setup_axis(implot.ImAxis_.y1)
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

    # Channel-identity gutter: one y-tick per lane at its baseline (the same
    # `-col_idx * channel_height` offset plot_channel draws at), labelled with
    # the channel name — replaces the old `no_tick_labels` suppression so a
    # channel can be identified past the ~10 distinguishable trace colours.
    # ponytail: at very high enabled counts the labels crowd; that's the job of
    # the future full-array raster overview, not this per-trace view.
    if channel_map:
        positions = [-col_idx * channel_height for col_idx in range(len(channel_map))]
        labels = [
            ch_names[ch] if ch_names and 0 <= ch < len(ch_names) else f"ch{ch}"
            for ch in channel_map
        ]
        implot.setup_axis_ticks(implot.ImAxis_.y1, positions, labels)


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
        # `ch_data` and the ranges are both GAINED. In Auto gain cancels here (range is eased in the
        # same gained units); in Manual the range is frozen, so gain magnifies against it.
        ch_data = np.asarray(col_ch, dtype=np.float64) * v.gain
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
            m = muted()  # unlabeled markers ride the theme's secondary tone
            color = imgui.ImVec4(m.x, m.y, m.z, 0.6)
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
    # Real loop rate from ImGui (smoothed). The old `1000/avg_ms` divided by
    # per-frame *viewer work*, not the inter-frame interval, so it read absurdly
    # high (~800); keep that work time as an explicit render-cost readout.
    ui_fps = imgui.get_io().framerate

    n_buf = stream._data.shape[0] if stream._data is not None else 0
    capacity = stream._data.maxlen if stream._data is not None else 0
    fill_pct = 100.0 * n_buf / capacity if capacity > 0 else 0.0
    paused_tag = f"  {fa.ICON_FA_PAUSE} PAUSED" if v.paused else ""

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
        pts_str = f"{len(frame.trace_ts):,} pts/ch (RMS env)"
    else:
        raw_len = len(frame.data_win)
        n_out = v.last_decim_n_out or raw_len
        if raw_len > n_out:  # one expression instead of printing the target twice
            pts_str = f"MinMax {raw_len:,}→{n_out:,} pts/ch"
        else:
            pts_str = f"{raw_len:,} pts/ch (raw)"

    imgui.text_colored(
        muted(),
        f"{ui_fps:.0f} fps ({avg_ms:.1f} ms viewer) | "
        f"fs={stream.info.fs:.0f} Hz | "
        f"{frame.n_channels} ch | "
        f"buf {fill_pct:.0f}% | "
        f"{pts_str}" + paused_tag,
    )

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
            muted(),
            f"  {name}: rms {rms_all[i]:.3f}  pp {pp_all[i]:.3f}  mean {mean_all[i]:+.3f}",
        )
