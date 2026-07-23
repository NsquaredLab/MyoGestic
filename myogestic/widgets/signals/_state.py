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
    re-notching the whole window every frame (``apply_mains_notch``) at a fraction of the
    cost. A key change, a coverage gap (the warm-up now reaches back before the cached tail),
    a sequence discontinuity, or a reconnect (new `epoch`) triggers a cold rebuild.

    Persistent state means already-drawn samples are never revised as the window scrolls —
    strictly better than re-seeding a fresh warm-up each frame, which the old per-frame notch
    did (their settled outputs agree to well within the trace's line width).

    ponytail: the tail is re-`concatenate`d each frame — a bounded ~window-sized copy, far
    cheaper than the O(window) IIR it replaces; a preallocated ring would drop even that copy
    if it ever profiles hot.
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
            # Column-select ONLY the warm-up+region rows, never the whole buffer:
            # `data_raw[:, channel_map]` over a 60 s buffer fancy-copies ~40 MB/frame.
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

    n_pixels: int = 2000
    window: float = 1.0
    gain: float = 1.0
    channels: set[int] = field(default_factory=set)
    specs: list = field(default_factory=list)
    fps: list[float] = field(default_factory=list)
    channels_initialized: bool = False
    # `(stream_key, n_channels)` that `channels` currently reflects — set by
    # `resolve_enabled`. `None` until the first resolve. Also read by
    # `_controls.py` to reset the toggle-grid's shift-click anchor on a
    # stream/channel-count change.
    active_channels_key: tuple[str, int] | None = None
    # Per-`(stream_key, n_channels)` selection cache so a `selectable`
    # viewer that flips between streams restores each stream's own
    # selection instead of sharing/resetting a single one. Populated by
    # `resolve_enabled` whenever it moves `channels` to a new key.
    _channels_by_key: dict[tuple[str, int], set[int]] = field(default_factory=dict, repr=False)
    last_hovered: int = -1
    selected_stream: str | None = None
    scale_mode: str = "auto"
    y_min: float = -1.0
    y_max: float = 1.0
    per_channel_scale: bool = False
    rescale_pending: bool = False
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
    # Decimation output-size target used by the *last* `render_plot` call
    # (sized to the live plot's pixel width there — see
    # `resolve_decimation_target`). `render_footer` reads it back to report
    # accurate decimation stats without needing a live ImPlot context of
    # its own (it renders after `end_plot()`).
    last_decim_n_out: int = 0
    # Cached per-channel diagnostics `(channels, rms, pp, mean)` and the
    # perf_counter time they were computed. `render_footer` computes these
    # over the *raw* (undecimated) window — O(window_samples * n_enabled),
    # which is tens of ms at a high sample rate / wide window / many channels
    # — so it throttles the recompute to ~10 Hz (and on an enabled-set
    # change) and renders the cached values in between, rather than paying it
    # every frame for a readout that changes slowly.
    stats_cache: tuple[list[int], np.ndarray, np.ndarray, np.ndarray] | None = field(
        default=None, repr=False
    )
    stats_last_t: float = 0.0
    # Incremental causal-notch state (see `NotchCache`): persists the filtered
    # tail + per-biquad IIR state so the notch filters only the newly-arrived
    # samples each frame instead of re-notching the whole visible window.
    notch_cache: NotchCache = field(default_factory=NotchCache, repr=False)
    # Buffer identity captured when paused, so the notch cache treats the frozen
    # window as one unchanging snapshot (no re-filtering while paused). `frozen_fs`
    # is captured with the samples so a reconnect at a new rate can't be applied to
    # the frozen old-rate data.
    frozen_epoch: int = 0
    frozen_seq: int = 0
    frozen_fs: float = 0.0


@dataclass
class SignalFrame:
    # The enabled-subset trace to plot. Normally the raw (display-filtered)
    # visible window; in `rms_env` mode the *sparse* RMS envelope. Its rows
    # pair with `trace_ts` (not `ts_win`).
    data: np.ndarray
    # Visible-window timestamps (raw samples). Drives the label markers and is
    # `trace_ts` in every non-`rms_env` mode. Kept distinct from `trace_ts`
    # because the RMS envelope has its own, sparser time base.
    ts_win: np.ndarray
    # Full-width visible window used by the footer diagnostics (kept RAW in
    # `rms_env` mode so the numeric readout still describes the real signal).
    data_win: np.ndarray
    # Timestamps paired with `data` for plotting. Equals `ts_win` normally; the
    # hop-endpoint times of the RMS envelope in `rms_env` mode.
    trace_ts: np.ndarray
    # Time that maps to plot-x 0 — the visible window's left edge. Passed to
    # the decimator so a sparse trace starting after the edge is not shifted
    # left and the markers stay aligned.
    x_origin: float
    n_channels: int
    n_points: int
    frame_start: float
    # Real channel index for each column of `data`, ascending: `data[:, i]`
    # is channel `channel_map[i]`. `data` only spans the enabled subset, so
    # callers must go through this map instead of indexing `data` by real
    # channel index (`data_win` stays full-width and can still be indexed by
    # real channel index directly).
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
    its own min/max envelope — there is no cross-channel index union (that
    union is what made the old shared decimator's reduction vanish at high
    channel counts: the union of many channels' distinct picks approaches
    the full window, e.g. 64 channels over a 5 s / 2048 Hz window unioning to
    the *entire* window). The two points per bucket sit at the bucket's
    CENTER time (the shared `xs`), which is sub-pixel-accurate once
    `n_out ~= 3 * plot_width`, rather than at either member sample's own
    timestamp.

    Buckets are anchored to an *absolute*-time grid (`bucket_dt = window_s /
    n_buckets`), not to this window's own start. `t` is the absolute
    (continuous) sample timestamp, and the visible window slides every frame
    as new samples arrive — bucketing relative to the window's own first
    timestamp would recompute different bucket boundaries every frame even
    though the underlying samples are unchanged, which is what caused the
    left-edge scrolling flicker (most visible in the partial leftmost
    bucket, since its boundary shifts the most between frames). Flooring the
    *absolute* timestamp onto a grid whose width is fixed frame-to-frame
    instead maps a given sample to the same bucket regardless of where the
    window currently starts, so the per-bucket min/max — and therefore the
    drawn envelope — is stable as the window scrolls.

    Pure NumPy, all channels processed together (no per-channel Python
    loop): ~0.9 ms for 64 channels / 5 s / 2048 Hz, versus ~15.7 ms for the
    old per-channel loop over `m4_decimate_channel`.
    """
    data = np.ascontiguousarray(data)
    n, n_channels = data.shape
    if n == 0:
        return np.empty(0, dtype=np.float64), np.empty((n_channels, 0), dtype=np.float64)
    # `x_origin` is the time that maps to plot-x 0 (the visible window's left
    # edge). It defaults to the first sample's own timestamp — correct for a
    # dense window that fills the view — but a *sparse* trace (e.g. the RMS
    # envelope) can start after the left edge, and subtracting its own `t[0]`
    # would slide it against the raw x-axis and misalign the label markers.
    if x_origin is None:
        x_origin = float(t[0])
    if n <= n_out:
        xs = np.ascontiguousarray(t - x_origin, dtype=np.float64)
        return xs, np.ascontiguousarray(data.T, dtype=np.float64)

    n_buckets = max(1, n_out // 2)
    bucket_dt = window_s / n_buckets if window_s > 0 else 0.0
    if not np.isfinite(bucket_dt) or bucket_dt <= 0:
        # Degenerate window (<=0, or too small relative to n_buckets to
        # produce a usable grid) -- fall back to splitting the samples into
        # n_buckets equal-count groups so we still reduce the point count.
        # Not scroll-stable, but window_s <= 0 is not a state the viewer
        # should ever reach in practice (the window slider is floored at
        # 0.1 s; see _controls.py).
        bucket_id = (np.arange(n, dtype=np.int64) * n_buckets) // n
    else:
        bucket_id = np.floor(t / bucket_dt).astype(np.int64)

    # Each distinct bucket occupies one contiguous run of `bucket_id` (it's
    # non-decreasing: `t` is a monotonic window slice and `floor` preserves
    # order). `starts` locates each run's first offset; `lengths` its size.
    starts = np.flatnonzero(np.r_[True, bucket_id[1:] != bucket_id[:-1]])
    lengths = np.diff(starts, append=n)
    # Cap the padded run width. `blocks` below is `(n_buckets, width,
    # n_channels)`; with `width = lengths.max()` a *single* pathological run
    # would force *every* bucket to that width and blow the allocation up to
    # gigabytes. Such a run is realistic: a device clock stall or a
    # monotonic-clamped session drops many samples onto one timestamp, so
    # they all land in one bucket. Cap width at a generous multiple of the
    # uniform run length; the few runs that exceed the cap get an exact
    # reduction below, so nothing is silently dropped.
    uniform = -(-n // len(starts))  # ceil(n / n_buckets)
    width = min(int(lengths.max()), max(4 * uniform, 64))
    # Gather every run into one (buckets, width, channels) block, padding
    # short runs by repeating their last sample (`np.minimum(..., lengths -
    # 1)` clamps the take-index so it never reads past a run's own end) —
    # trades a little extra memory for a single vectorized reduction instead
    # of a per-bucket Python loop.
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


#: Oversampling factor applied to the plot's pixel width when sizing the
#: MinMax decimation target — a few points per pixel keeps sharp features
#: visible without materially increasing draw cost.
_DECIMATE_PIXEL_FACTOR = 3.0
#: Floor on the width-derived target so a very narrow (or not-yet-laid-out)
#: plot never collapses decimation down to near nothing.
_DECIMATE_MIN_POINTS = 64


def resolve_decimation_target(plot_width_px: float, v: ViewerState) -> int:
    """MinMax decimation output size, sized to the plot's own pixel width.

    `plot_width_px` should come from the live plot (e.g.
    ``implot.get_plot_size().x``, only valid between `begin_plot` /
    `end_plot`). `v.n_pixels` (the "Resolution" control) is the ceiling on
    the result — it also doubles as the fallback when `plot_width_px` isn't
    available yet (e.g. the very first frame, reported as `<= 0`) — so the
    control still has an effect once the plot has a real size, instead of
    being the primary driver the way the old fixed `n_pixels * 4` budget
    was.
    """
    cap = max(4, int(v.n_pixels))
    if plot_width_px <= 0:
        target = cap
    else:
        width_target = max(_DECIMATE_MIN_POINTS, int(plot_width_px * _DECIMATE_PIXEL_FACTOR))
        target = min(cap, width_target)
    return max(4, (target // 4) * 4)


def get_viewer_state(
    ctx: Context,
    stream_name: str,
    n_pixels: int,
    scale_mode: str,
    y_range: tuple[float, float],
    show_markers: bool,
    window_s: float | None = None,
) -> ViewerState:
    v = _viewers.get(stream_name)
    if v is None:
        s0 = ctx.streams.get(stream_name)
        # Caller override wins; fall back to the stream's processing window
        # (typically tiny — 0.2 s for classification — which is fine for the
        # model but unreadable on screen).
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
        )
        _viewers[stream_name] = v
    return v


def resolve_enabled(
    v: ViewerState,
    stream_key: str,
    n_channels: int,
    initial_channels: Iterable[int] | None = None,
) -> set[int]:
    """Resolve the enabled channel set from persistent viewer state.

    Must run before [`build_signal_frame`][] so the frame can decimate
    only the enabled columns.

    The selection is cached on `v` keyed by `(stream_key, n_channels)`, so
    a `selectable` viewer that flips between streams restores each
    stream's own selection instead of resetting a single shared one — and
    a channel-count change on the active stream (e.g. a reconnect at a
    different channel count) is treated as a fresh key rather than
    clobbering that stream's other-size selection.

    `initial_channels` seeds
    `resolve_initial` only
    the very first time this `ViewerState` ever creates a selection —
    i.e. once, for whichever `(stream_key, n_channels)` is active on that
    first call. Every later first-sight of a *different* key (a stream
    switch, or a channel-count change) falls back to `resolve_initial`'s
    `None` policy instead: every channel for streams with
    `n_channels <= 32`, otherwise just the first 16. This keeps a user's
    own edits from ever being silently overwritten by the caller's
    one-shot hint. Returns the live `v.channels` set; safe because
    nothing reads it again until the *next* frame, after which only
    `render_channel_controls` mutates it.
    """
    key = (stream_key, n_channels)
    if v.channels_initialized and v.active_channels_key == key:
        return v.channels

    first_ever = not v.channels_initialized
    if v.channels_initialized and v.active_channels_key is not None:
        v._channels_by_key[v.active_channels_key] = v.channels

    cached = v._channels_by_key.get(key)
    if cached is not None:
        v.channels = set(cached)
    else:
        v.channels = resolve_initial(initial_channels if first_ever else None, n_channels, [])

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
    ``_NOTCH_WARMUP_S`` of samples before ``region_start_t``, drops that warm-up, and — the
    whole point of the cache — filters only the samples newer than the previous frame while
    reusing the already-filtered tail. ``freq == 0`` is a no-op (and releases the cache so its
    tail/IIR state is not retained while the notch is off). ``(epoch, end_seq)`` come from
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
    envelope from `compute_rms_trace` (computed over a pre-roll-extended,
    enabled-only slice), `trace_ts` is its hop-endpoint time base, and
    `data_win` is kept RAW so the footer's rms/pp/mean still describe the real
    signal.

    Does *not* MinMax-decimate: that runs once per frame over every enabled
    column at once (`minmax_grid_all_shared_x`) inside `render_plot`
    (`_plot.py`) — this function only hands it the trace to draw.
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
        # reconnect). Copy only the visible window + notch warm-up (+ rms pre-roll), not
        # the whole 60 s buffer — that copy alone was the dominant per-frame cost at 10 kHz.
        # Exception: when *entering* pause, take the FULL buffer, because the window / rms
        # sliders stay live while paused and a trimmed freeze couldn't satisfy a widening.
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
    # Slice the visible window by *timestamp*, not by sample count.
    # Sample-count slicing only matches v.window seconds when timestamps
    # are perfectly uniform. Sources that stamp at host arrival time
    # (e.g. BLE) produce non-uniform per-sample timestamps under radio
    # jitter — a fixed-count slice can then span more than v.window
    # seconds and the trace draws past the right edge of the plot's
    # hard `[0, v.window]` x-axis. Time-based slicing makes the rendered
    # span always equal `min(v.window, data_age)`.
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
        # Sparse RMS envelope. Read one RMS window of PRE-ROLL before the
        # visible edge so the leftmost envelope points have a full window of
        # history (otherwise they are a scroll-dependent partial transient),
        # and slice to the enabled columns *before* the O(window·ch) RMS work.
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
        # Footer diagnostics read `data_win`; keep it the RAW visible window so
        # the numeric rms/pp/mean still describe the real signal, not the
        # envelope.
        data_win = data_win_raw
    else:
        # Footer stats read `data_win` (full width); keep it the RAW visible
        # window (display-filtered), like the rms_env branch, so the numbers
        # describe the real signal. Only the *drawn* trace gets the notch, and
        # only on the channels actually plotted (`channel_map`).
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
