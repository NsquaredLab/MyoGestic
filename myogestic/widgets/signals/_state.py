from __future__ import annotations

import time as _time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from myogestic.widgets.signals._channel_grid import resolve_initial
from myogestic.widgets.signals.transforms import (
    NotchFilter,
    apply_display_filter,
    compute_rms_trace,
)

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import Stream


#: Causal-notch settle time to warm the filter up before the shown region.
_NOTCH_WARMUP_S = 0.5


def _cols(a: np.ndarray, channel_map: list[int] | None) -> np.ndarray:
    """Select the drawn columns.

    Callers MUST row-slice ``a`` to the region they need first — ``data_raw[:, channel_map]``
    over a full 60 s buffer fancy-copies tens of MB per frame.
    """
    return a if channel_map is None else a[:, channel_map]


class NotchCache:
    """Incremental causal mains-notch — the stateful counterpart of ``apply_mains_notch``.

    Holds a `NotchFilter` and the filtered tail it has produced so far, keyed by the
    stream / epoch / rate / freq / drawn-channels it was built for. Each frame it filters only
    the newly-arrived samples (identified by absolute sample *sequence*) and reuses the
    already-filtered values for the rest of the visible window, so the output equals
    re-notching the whole window every frame at a fraction of the cost. Already-drawn
    samples are never revised as the window scrolls. A key change, a coverage gap (the
    warm-up now reaches back before the cached tail), a sequence discontinuity, or a
    reconnect (new `epoch`) triggers a cold rebuild.

    ponytail: the tail is re-`concatenate`d each frame — a bounded ~window-sized copy; a
    preallocated ring would drop it if this ever profiles hot.
    """

    def __init__(self) -> None:
        self._key: tuple | None = None
        self._filter: NotchFilter | None = None
        self._filtered: np.ndarray | None = None  # filtered tail spanning [_start_seq, _next_seq)
        self._start_seq = 0
        self._next_seq = 0
        self._last_end_t: float | None = None  # newest timestamp last seen (detects clock resets)

    def release(self) -> None:
        """Drop the cached filter and tail (notch turned off, or stream abandoned)."""
        self.__init__()

    def notched(
        self,
        stream_id: int,
        epoch: int,
        end_seq: int,
        data_raw: np.ndarray,
        ts_raw: np.ndarray,
        region_start_idx: int,
        region_start_t: float,
        fs: float,
        freq: int,
        channel_map: list[int] | None,
    ) -> np.ndarray:
        """``data_raw[region_start_idx:]`` (columns ``channel_map``) with the notch applied.

        Same result as [`apply_mains_notch`][myogestic.widgets.signals.transforms.apply_mains_notch]
        over a warm-up-extended slice, but filtering only samples newer than the last call.
        ``end_seq`` is the sequence just past ``data_raw``'s newest row (from
        [`Stream.get_raw_snapshot_stable`][]): ``data_raw[i]`` has sequence
        ``end_seq - len(data_raw) + i``.
        """
        n = len(data_raw)
        oldest_seq = end_seq - n
        warm_idx = int(np.searchsorted(ts_raw, region_start_t - _NOTCH_WARMUP_S, side="left"))
        warm_seq = oldest_seq + warm_idx
        key = (stream_id, epoch, fs, freq, tuple(channel_map) if channel_map is not None else None)
        end_t = float(ts_raw[-1])

        cold = (
            self._key != key
            or self._filter is None
            or self._filtered is None
            or self._next_seq > end_seq  # sequence regressed (shouldn't happen within an epoch)
            or self._next_seq < oldest_seq  # cache fell behind the ring (render stalled)
            or self._start_seq > warm_seq  # cached tail no longer reaches the warm-up start
            # Newest timestamp went backwards: an upstream clock reset (e.g. ReplaySource
            # looping to t=0) that does NOT bump the epoch. Don't carry IIR state across it.
            or (self._last_end_t is not None and end_t < self._last_end_t)
        )
        if cold:
            self._key = key
            self._filter = NotchFilter(fs, freq)
            # Column-select ONLY the warm-up+region rows, never the whole buffer (see `_cols`).
            self._filtered = self._filter.step(_cols(data_raw[warm_idx:], channel_map))
            self._start_seq = warm_seq
            self._next_seq = end_seq
        else:
            new_count = end_seq - self._next_seq
            if new_count > 0:  # filter ONLY the newly-arrived samples (column-select just those rows)
                fresh = self._filter.step(_cols(data_raw[n - new_count :], channel_map))
                self._filtered = np.concatenate([self._filtered, fresh])
                self._next_seq = end_seq
            drop = warm_seq - self._start_seq  # >= 0 unless it was cold
            if drop:
                self._filtered = self._filtered[drop:]
                self._start_seq = warm_seq
        self._last_end_t = end_t
        # _filtered now spans [warm_seq, end_seq); return from the region start.
        return self._filtered[region_start_idx - warm_idx :]


@dataclass
class ViewerState:
    """Per-widget-id viewer state."""

    n_pixels: int | None = None  # optional hard cap on drawn points; None/0 = no cap
    detail_factor: float = 3.0  # draw density (points per plot pixel); the "Detail" slider drives it
    one_to_one: bool = False  # draw every sample, no MinMax; the "1:1" toggle drives it
    window: float = 1.0
    gain: float = 1.0
    channels: set[int] = field(default_factory=set)
    specs: list = field(default_factory=list)
    fps: list[float] = field(default_factory=list)
    channels_initialized: bool = False
    # `(stream_key, n_channels)` that `channels` currently reflects — set by
    # `resolve_enabled`, `None` until the first resolve. Also read by `_controls.py`
    # to reset the toggle-grid's shift-click anchor on a stream/channel-count change.
    active_channels_key: tuple[str, int, tuple[int, ...] | None] | None = None
    # Per-`(stream_key, n_channels)` selection cache so a `selectable` viewer that
    # flips between streams restores each stream's own selection. Populated by
    # `resolve_enabled` whenever it moves `channels` to a new key.
    _channels_by_key: dict[tuple[str, int], set[int]] = field(default_factory=dict, repr=False)
    selected_stream: str | None = None
    scale_mode: str = "auto"
    y_min: float = -1.0
    y_max: float = 1.0
    per_channel_scale: bool = False
    # Pending "Rescale/Fit & lock" click, remembering which BASIS it applies to ("shared"
    # fits the one shared y-range; "per_channel" fits each channel's lane) so a same-frame
    # Per channel toggle can't misapply it. `None` = no request. Consumed once in `viewer.py`.
    rescale_pending: str | None = None
    # Auto-scale easing state (see `_plot.update_auto_scale`). `scale_ease_t` is the last
    # frame's `perf_counter` (dt source); `scale_ease_key` is the (stream, channels,
    # display_filter) context — a change snaps rather than eases across an unrelated scale.
    scale_ease_key: tuple | None = None
    scale_ease_t: float = 0.0
    # Per-channel-mode easing (see `_plot.update_per_channel_ranges`): the same ease over
    # each channel's normalisation `(min, max)`. `pc_ranges` is keyed by real channel index.
    pc_ranges: dict[int, tuple[float, float]] = field(default_factory=dict, repr=False)
    pc_ease_key: tuple | None = None
    pc_ease_t: float = 0.0
    # Ignore transients shorter than this (ms) when fitting the y-range, so a brief
    # movement artifact doesn't define the scale. 0 = plain min/max. See
    # `_plot.robust_channel_ranges`.
    transient_ms: float = 20.0
    paused: bool = False
    frozen_ts: np.ndarray | None = None
    frozen_data: np.ndarray | None = None
    show_diagnostics: bool | None = None
    display_filter: str = "none"
    # Optional mains-hum notch (0 = off, else 50 or 60 Hz) applied to the
    # visible window *before* `display_filter`. Visual-only — recording and
    # model input are untouched. See `transforms.apply_mains_notch`.
    mains_notch: int = 0
    # RMS-envelope controls (only used when `display_filter == "rms_env"`):
    # the averaging window and the hop between envelope points, both in ms.
    # See `transforms.compute_rms_trace`.
    rms_window_ms: float = 100.0
    rms_hop_ms: float = 20.0
    show_markers: bool = True
    show_retarget: bool = False
    show_controls: bool = True  # top control menu; toggled from the panel header for plot/grid room
    # Decimation output-size target used by the *last* `render_plot` call (see
    # `resolve_decimation_target`). `render_footer` reads it back to report decimation
    # stats without a live ImPlot context of its own (it renders after `end_plot()`).
    last_decim_n_out: int = 0
    # Cached per-channel diagnostics `(channels, rms, pp, mean)` and the perf_counter
    # time they were computed. `render_footer` computes these over the *raw*
    # (undecimated) window — O(window_samples * n_enabled), tens of ms at a high rate /
    # wide window / many channels — so it throttles the recompute to ~10 Hz (and on an
    # enabled-set change) and renders the cached values in between.
    stats_cache: tuple[list[int], np.ndarray, np.ndarray, np.ndarray] | None = field(
        default=None, repr=False
    )
    stats_last_t: float = 0.0
    # Incremental causal-notch state (see `NotchCache`).
    notch_cache: NotchCache = field(default_factory=NotchCache, repr=False)
    # Buffer identity captured when paused, so the notch cache treats the frozen window
    # as one unchanging snapshot. `frozen_fs` is captured with the samples so a
    # reconnect at a new rate can't be applied to the frozen old-rate data.
    frozen_epoch: int = 0
    frozen_seq: int = 0
    frozen_fs: float = 0.0


def select_stream(v: ViewerState, name: str) -> None:
    """Point a `selectable` viewer at ``name``, dropping any frozen window.

    The one place a stream switch happens, because the freeze is what makes two
    routes diverge: a paused viewer that changes stream keeps showing the *old*
    stream's frozen samples under the new stream's title until someone presses
    Resume. Both the transport dropdown and the header's prev/next arrows go
    through here.

    Channel selection is deliberately *not* reset: `resolve_enabled` keys it by
    ``(stream, n_channels)`` and restores each stream's own set.

    Parameters
    ----------
    v
        The viewer's state.
    name
        Stream to show.
    """
    v.selected_stream = name
    v.paused = False
    v.frozen_ts = None
    v.frozen_data = None


@dataclass
class SignalFrame:
    # The enabled-subset trace to plot. Normally the raw (display-filtered)
    # visible window; in `rms_env` mode the *sparse* RMS envelope. Its rows
    # pair with `trace_ts`, not `ts_win`.
    data: np.ndarray
    # Visible-window timestamps (raw samples). Drives the label markers.
    ts_win: np.ndarray
    # Full-width visible window used by the footer diagnostics (kept RAW in
    # `rms_env` mode so the numeric readout still describes the real signal).
    data_win: np.ndarray
    # Timestamps paired with `data` for plotting. Equals `ts_win` normally; the
    # hop-endpoint times of the RMS envelope in `rms_env` mode.
    trace_ts: np.ndarray
    # Time that maps to plot-x 0 — the visible window's left edge. Passed to the
    # decimator so a sparse trace starting after the edge is not shifted left.
    x_origin: float
    n_channels: int
    n_points: int
    frame_start: float
    # Real channel index for each column of `data`, ascending: `data[:, i]` is
    # channel `channel_map[i]`. `data` only spans the enabled subset, so callers
    # MUST go through this map rather than index `data` by real channel index
    # (`data_win` stays full-width and can be indexed directly).
    channel_map: list[int]


_viewers: dict[str, ViewerState] = {}


def normalize_scale_mode(scale_mode: str) -> str:
    return "manual" if scale_mode == "manual" else "auto"


def minmax_grid_all_shared_x(
    t: np.ndarray,
    data: np.ndarray,
    n_out: int,
    window_s: float,
    x_origin: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """MinMax-decimate every enabled channel at once, to ~`n_out` points each.

    Returns `(xs, ys)`: `xs` has shape `(2*n_buckets+2,)`, shared across every
    channel; `ys` has shape `(n_channels, 2*n_buckets+2)`. Each channel keeps
    its own min/max envelope — no cross-channel index union, whose reduction
    vanishes at high channel counts (64 channels over a 5 s / 2048 Hz window
    union to the *entire* window). The two points per bucket sit at the
    bucket's CENTER time (the shared `xs`), sub-pixel-accurate once
    `n_out ~= 3 * plot_width`.

    Buckets are anchored to an *absolute*-time grid (`bucket_dt = window_s /
    n_buckets`), not to this window's own start. `t` is the absolute sample
    timestamp and the visible window slides every frame, so window-relative
    boundaries would move frame to frame over unchanged samples and flicker
    the left edge. On the absolute grid a sample always lands in the same
    bucket, so the drawn envelope is stable as the window scrolls.

    Pure NumPy, all channels processed together (no per-channel Python
    loop): ~0.9 ms for 64 channels / 5 s / 2048 Hz.
    """
    data = np.ascontiguousarray(data)
    n, n_channels = data.shape
    if n == 0:
        return np.empty(0, dtype=np.float64), np.empty((n_channels, 0), dtype=np.float64)
    # `x_origin` is the time that maps to plot-x 0 (the visible window's left edge).
    # It defaults to the first sample's own timestamp, but a *sparse* trace (e.g. the
    # RMS envelope) can start after the left edge, and subtracting its own `t[0]`
    # would slide it against the raw x-axis and misalign the label markers.
    if x_origin is None:
        x_origin = float(t[0])
    if n <= n_out:
        xs = np.ascontiguousarray(t - x_origin, dtype=np.float64)
        return xs, np.ascontiguousarray(data.T, dtype=np.float64)

    n_buckets = max(1, n_out // 2)
    bucket_dt = window_s / n_buckets if window_s > 0 else 0.0
    if not np.isfinite(bucket_dt) or bucket_dt <= 0:
        # Degenerate window (<=0, or too small for a usable grid): fall back to
        # n_buckets equal-count groups so we still reduce the point count. Not
        # scroll-stable, but the window slider is floored at 0.1 s (_controls.py).
        bucket_id = (np.arange(n, dtype=np.int64) * n_buckets) // n
    else:
        bucket_id = np.floor(t / bucket_dt).astype(np.int64)

    # Each distinct bucket occupies one contiguous run of `bucket_id` (it's
    # non-decreasing: `t` is a monotonic window slice and `floor` preserves
    # order). `starts` locates each run's first offset; `lengths` its size.
    starts = np.flatnonzero(np.r_[True, bucket_id[1:] != bucket_id[:-1]])
    lengths = np.diff(starts, append=n)
    # Cap the padded run width. `blocks` below is `(n_buckets, width, n_channels)`;
    # with `width = lengths.max()` one pathological run — a device clock stall drops
    # many samples onto a single timestamp, so onto one bucket — would force *every*
    # bucket to that width and blow the allocation up to gigabytes. The few runs over
    # the cap get an exact reduction below, so nothing is silently dropped.
    uniform = -(-n // len(starts))  # ceil(n / n_buckets)
    width = min(int(lengths.max()), max(4 * uniform, 64))
    # Gather every run into one (buckets, width, channels) block, padding short runs
    # by repeating their last sample (`np.minimum(..., lengths - 1)` clamps the
    # take-index so it never reads past a run's own end): one vectorized reduction
    # instead of a per-bucket Python loop.
    take = starts[:, None] + np.minimum(np.arange(width, dtype=np.intp), lengths[:, None] - 1)
    blocks = data[take]  # (buckets, width, channels); tail padded by repeat
    lows = np.fmin.reduce(blocks, axis=1)  # (buckets, channels), NaN-robust
    highs = np.fmax.reduce(blocks, axis=1)
    # Runs longer than the cap had their tail ignored by the take-clamp
    # above; recompute those (few) buckets exactly over their full run so a
    # degenerate flat-timestamp block keeps its true min/max envelope.
    for i in np.flatnonzero(lengths > width):
        seg = data[starts[i] : starts[i] + lengths[i]]
        lows[i] = np.fmin.reduce(seg, axis=0)
        highs[i] = np.fmax.reduce(seg, axis=0)

    nb = len(starts)
    ys = np.empty((n_channels, 2 * nb + 2), dtype=np.float64)
    ys[:, 0] = data[0]
    ys[:, 1:-1:2] = lows.T
    ys[:, 2:-1:2] = highs.T
    ys[:, -1] = data[-1]

    centers = (bucket_id[starts].astype(np.float64) + 0.5) * bucket_dt
    centers = np.clip(centers, t[0], t[-1])
    xs = np.empty(2 * nb + 2, dtype=np.float64)
    xs[0] = t[0]
    xs[1:-1:2] = centers
    xs[2:-1:2] = centers
    xs[-1] = t[-1]
    xs -= x_origin
    return xs, ys


#: Draw-density bounds for the "Detail" control, in points per plot pixel.
#: `_DETAIL_FULL` keeps sharp features / MinMax peaks crisp; `_DETAIL_MIN`
#: is the coarsest, cheapest trace.
_DETAIL_MIN = 0.5
_DETAIL_FULL = 3.0
#: Floor on the width-derived target so a very narrow (or not-yet-laid-out)
#: plot never collapses decimation down to near nothing.
_DECIMATE_MIN_POINTS = 64
#: Target used only on the first frame, before the plot has a real pixel
#: width and no explicit `n_pixels` cap is set. Self-corrects next frame.
_DECIMATE_FALLBACK_POINTS = 2000

#: Asked for by the "1:1" toggle: larger than any window a ring buffer can hold, so
#: `minmax_grid_all_shared_x` takes its ``n <= n_out`` pass-through and returns the
#: samples untouched. Deliberately not a real point count — what keeps 1:1 affordable
#: is the budget the toggle itself enforces (`_controls._ONE_TO_ONE_MAX_POINTS`), which
#: can see the channel count and the window; this function sees neither.
_ONE_TO_ONE_TARGET = 1 << 24


def resolve_decimation_target(plot_width_px: float, v: ViewerState) -> int:
    """MinMax decimation output size, sized to the plot's own pixel width.

    `plot_width_px` should come from the live plot (e.g.
    ``implot.get_plot_size().x``, only valid between `begin_plot` /
    `end_plot`). The drawn point count per channel is
    ``plot_width_px * v.detail_factor``. `v.n_pixels` is an *optional* hard
    cap (`None`/`0` = no cap) and the fallback when `plot_width_px` isn't
    available yet (the very first frame, reported as `<= 0`).

    ``v.one_to_one`` overrides all of it and asks for every sample. Detail tops out at
    a few points per pixel — more than a display can resolve, but not the raw signal —
    so reading a waveform shorter than a bucket needs decimation off rather than turned
    up.
    """
    if v.one_to_one:
        return _ONE_TO_ONE_TARGET
    if plot_width_px <= 0:
        target = v.n_pixels or _DECIMATE_FALLBACK_POINTS
    else:
        target = max(_DECIMATE_MIN_POINTS, int(plot_width_px * v.detail_factor))
        if v.n_pixels:
            target = min(target, v.n_pixels)
    return max(4, (target // 4) * 4)


def get_viewer_state(
    ctx: Context,
    widget_id: str,
    n_pixels: int | None,
    scale_mode: str,
    y_range: tuple[float, float],
    show_markers: bool,
    window_s: float | None = None,
    stream_name: str | None = None,
    show_controls: bool = True,
) -> ViewerState:
    """Per-widget viewer state, created on first use.

    Keyed by ``widget_id`` — NOT by the stream — so several viewers can show
    the same stream (e.g. one panel per electrode grid) without sharing one
    another's channels, scale, pause or filter. ``stream_name`` defaults to
    ``widget_id`` and is only used to pick the initial window from the stream.
    """
    v = _viewers.get(widget_id)
    if v is None:
        s0 = ctx.streams.get(stream_name or widget_id)
        # Caller override wins; fall back to the stream's processing window
        # (typically tiny — 0.2 s for classification — and unreadable on screen).
        if window_s is not None:
            win0 = window_s
        else:
            win0 = s0._window if s0 is not None else 1.0
        v = ViewerState(
            n_pixels=n_pixels,
            window=win0,
            gain=1.0,
            scale_mode=normalize_scale_mode(scale_mode),
            y_min=y_range[0],
            y_max=y_range[1],
            show_markers=show_markers,
            show_controls=show_controls,
        )
        _viewers[widget_id] = v
    return v


def resolve_enabled(
    v: ViewerState,
    stream_key: str,
    n_channels: int,
    initial_channels: Iterable[int] | None = None,
    scope: list[int] | None = None,
) -> set[int]:
    """Resolve the enabled channel set from persistent viewer state.

    Must run before [`build_signal_frame`][] so the frame can decimate
    only the enabled columns.

    The selection is cached on `v` keyed by `(stream_key, n_channels)`, so a
    `selectable` viewer that flips between streams restores each stream's own
    selection, and a channel-count change (e.g. a reconnect at a different
    count) is a fresh key rather than a clobber.

    `initial_channels` seeds `resolve_initial` only the very first time this
    `ViewerState` ever creates a selection — once, for whichever
    `(stream_key, n_channels)` is active on that call — so the caller's
    one-shot hint can never overwrite a user's own edits. Every later
    first-sight of a *different* key falls back to `resolve_initial`'s `None`
    policy: every channel for `n_channels <= 32`, otherwise the first 16.
    Returns the live `v.channels` set; nothing reads it again until the *next*
    frame, after which only `render_channel_controls` mutates it.

    `scope` (from `resolve_scope`) is the hard restriction — the columns this
    viewer may *ever* show. It bounds the seed, any restored selection, and the
    live set on **every** path, and it forms part of the cache key so a
    differently-scoped viewer sharing a ``widget_id`` never inherits another's
    selection. ``None`` is unrestricted.
    """
    # The scope fingerprint is part of the identity: state is keyed by `widget_id`,
    # not by Python instance, so a same-id differently-scoped viewer must not
    # inherit a selection resolved under another scope.
    key = (stream_key, n_channels, None if scope is None else tuple(scope))
    scope_set = None if scope is None else set(scope)
    if v.channels_initialized and v.active_channels_key == key:
        if scope_set is not None:
            # Enforce on the fast path too: it returns before the seeding below, so
            # intersecting only on restore would let anything that mutated
            # `v.channels` in between escape the scope.
            v.channels.intersection_update(scope_set)
        return v.channels

    first_ever = not v.channels_initialized
    if v.channels_initialized and v.active_channels_key is not None:
        v._channels_by_key[v.active_channels_key] = v.channels

    cached = v._channels_by_key.get(key)
    if cached is not None:
        v.channels = set(cached) if scope_set is None else set(cached) & scope_set
    else:
        v.channels = resolve_initial(
            initial_channels if first_ever else None, n_channels, [], scope=scope
        )

    v.specs = []
    v.channels_initialized = True
    v.active_channels_key = key
    return v.channels


def _notch_from(
    v: ViewerState,
    stream_id: int,
    epoch: int,
    end_seq: int,
    data_raw: np.ndarray,
    ts_raw: np.ndarray,
    region_start_idx: int,
    region_start_t: float,
    fs: float,
    freq: int,
    channel_map: list[int] | None = None,
) -> np.ndarray:
    """``data_raw[region_start_idx:]`` (columns ``channel_map``) with a notch.

    Delegates to ``v.notch_cache`` (see `NotchCache`), which warms the causal notch up over
    ``_NOTCH_WARMUP_S`` of samples before ``region_start_t`` and then drops that warm-up.
    ``freq == 0`` is a no-op and releases the cache, so no tail/IIR state is retained while
    the notch is off. ``(epoch, end_seq)`` come from
    [`Stream.get_raw_snapshot_stable`][] and identify the snapshot for the cache.

    ``channel_map`` restricts the notch (and the returned columns) to the channels actually
    drawn — per-frame IIR cost scales with that count, not the full array width. Column
    selection commutes with every per-sample display filter, so slicing here matches slicing
    after.
    """
    if not freq:
        v.notch_cache.release()
        return _cols(data_raw[region_start_idx:], channel_map)  # row-slice FIRST, then columns
    return v.notch_cache.notched(
        stream_id, epoch, end_seq, data_raw, ts_raw, region_start_idx, region_start_t, fs, freq, channel_map
    )


def build_signal_frame(
    stream: Stream,
    v: ViewerState,
    enabled: set[int],
) -> SignalFrame | None:
    """Read one live/frozen snapshot, slice the visible window, and filter.

    `data` is the enabled-only trace the plot draws (compacted to
    `channel_map`); `data_win` stays the full-width visible window for the
    footer diagnostics, which index it by real channel. In every mode except
    `rms_env`, `data` is the display-filtered visible window and `trace_ts`
    equals `ts_win`. In `rms_env` mode `data` is instead the *sparse* RMS
    envelope from `compute_rms_trace` (over a pre-roll-extended, enabled-only
    slice), `trace_ts` is its hop-endpoint time base, and `data_win` is kept
    RAW so the footer's rms/pp/mean still describe the real signal.

    Does *not* MinMax-decimate: that runs in `render_plot` (`_plot.py`) via
    `minmax_grid_all_shared_x`.
    """
    frame_start = _time.perf_counter()
    if v.paused and v.frozen_data is not None and v.frozen_ts is not None:
        ts_raw = v.frozen_ts
        data_raw = v.frozen_data
        epoch, end_seq, fs = v.frozen_epoch, v.frozen_seq, v.frozen_fs
    else:
        # Stable (locked-copy) snapshot: the notch cache carries IIR state across
        # frames, so it needs samples the acquire thread can't overwrite mid-filter,
        # plus (epoch, end_seq) to tell new samples from already-filtered ones and `fs`
        # captured atomically with the data (a separate stream.info.fs read can race a
        # reconnect). Copy only the visible window + notch warm-up (+ rms pre-roll); at
        # 10 kHz copying the whole 60 s buffer dominates the frame.
        # Exception: when *entering* pause, take the FULL buffer — the window / rms
        # sliders stay live while paused and a trimmed freeze can't satisfy a widening.
        margin_s = v.window + _NOTCH_WARMUP_S + 0.25
        if v.display_filter == "rms_env":
            margin_s += max(v.rms_window_ms, 0.0) / 1000.0
        raw = stream.get_raw_snapshot_stable(None if v.paused else margin_s)
        if raw is None:
            return None
        epoch, end_seq, fs, ts_raw, data_raw = raw
        if v.paused:
            # Freeze the samples AND their identity (incl. fs), so the notch cache sees one
            # unchanging snapshot while paused and resumes cleanly on play.
            v.frozen_ts = ts_raw
            v.frozen_data = data_raw
            v.frozen_epoch = epoch
            v.frozen_seq = end_seq
            v.frozen_fs = fs

    n_raw = len(data_raw)
    n_channels = data_raw.shape[1]
    # Slice the visible window by *timestamp*, not by sample count: sources that
    # stamp at host arrival time (e.g. BLE under radio jitter) have non-uniform
    # timestamps, so a fixed-count slice can span more than v.window seconds and
    # draw past the right edge of the plot's hard `[0, v.window]` x-axis. Time-based
    # slicing makes the rendered span always `min(v.window, data_age)`.
    if n_raw > 0:
        last_ts = float(ts_raw[-1])
        vis_start_t = last_ts - v.window
        start_idx = int(np.searchsorted(ts_raw, vis_start_t, side="left"))
    else:
        vis_start_t = 0.0
        start_idx = 0
    ts_win = ts_raw[start_idx:]
    data_win_raw = data_raw[start_idx:]  # full-width RAW visible window
    x_origin = float(ts_win[0]) if len(ts_win) else 0.0

    # `channel_map` — the enabled real-channel indices, ascending. Everything
    # the plot draws is compacted to this subset.
    channel_map = sorted(c for c in enabled if 0 <= c < n_channels)

    if v.display_filter == "rms_env":
        # Sparse RMS envelope. Read one RMS window of PRE-ROLL before the visible
        # edge so the leftmost envelope points have a full window of history
        # (otherwise they are a scroll-dependent partial transient), and slice to
        # the enabled columns *before* the O(window·ch) RMS work.
        window_s = max(v.rms_window_ms, 0.0) / 1000.0
        pre_idx = (
            int(np.searchsorted(ts_raw, vis_start_t - window_s, side="left")) if n_raw > 0 else 0
        )
        ts_pre = ts_raw[pre_idx:]
        data_pre = _notch_from(
            v, id(stream), epoch, end_seq, data_raw, ts_raw, pre_idx,
            vis_start_t - window_s, fs, v.mains_notch, channel_map,
        )
        rms_ts, rms_data = compute_rms_trace(ts_pre, data_pre, fs, v.rms_window_ms, v.rms_hop_ms)
        # Keep only endpoints inside the visible window (pre-roll was history).
        keep = rms_ts >= vis_start_t
        trace_ts = rms_ts[keep]
        data_sel = rms_data[keep]
        # Footer diagnostics read `data_win`; keep it RAW so the numeric
        # rms/pp/mean describe the real signal, not the envelope.
        data_win = data_win_raw
    else:
        # Only the *drawn* trace gets the notch, and only on the channels actually
        # plotted (`channel_map`); `data_win` stays un-notched for the footer.
        data_win = apply_display_filter(data_win_raw, v.display_filter, fs)
        notched = _notch_from(
            v, id(stream), epoch, end_seq, data_raw, ts_raw, start_idx,
            vis_start_t, fs, v.mains_notch, channel_map,
        )
        data_sel = apply_display_filter(notched, v.display_filter, fs)
        trace_ts = ts_win

    return SignalFrame(
        data=data_sel,
        ts_win=ts_win,
        data_win=data_win,
        trace_ts=trace_ts,
        x_origin=x_origin,
        n_channels=n_channels,
        n_points=len(data_sel),
        frame_start=frame_start,
        channel_map=channel_map,
    )
