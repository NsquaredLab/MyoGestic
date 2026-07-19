from __future__ import annotations

import time as _time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from myogestic.widgets.signals._channel_grid import resolve_initial
from myogestic.widgets.signals.transforms import apply_display_filter

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import Stream


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
    show_markers: bool = True
    show_retarget: bool = False
    _m4_downsampler: object | None = field(default=None, repr=False)
    _m4_numpy_fallback: bool = field(default=False, repr=False)
    # Per-channel M4 output-size target used by the *last* `render_plot`
    # call (sized to the live plot's pixel width there — see
    # `resolve_decimation_target`). `render_footer` reads it back to report
    # accurate decimation stats without needing a live ImPlot context of
    # its own (it renders after `end_plot()`).
    last_decim_n_out: int = 0


@dataclass
class SignalFrame:
    data: np.ndarray
    data_full: np.ndarray
    ts_win: np.ndarray
    data_win: np.ndarray
    n_channels: int
    n_points: int
    frame_start: float
    # Real channel index for each column of `data`, ascending: `data[:, i]`
    # is channel `channel_map[i]`. `data` only spans the enabled subset, so
    # callers must go through this map instead of indexing `data` by real
    # channel index (`data_full` / `data_win` stay full-width and can still
    # be indexed by real channel index directly). `data`'s rows pair with
    # `ts_win` (same window, same row count) — there is no separate
    # decimated `ts` field: decimation is now per-channel, sized to the
    # plot's pixel width and done in the plot loop
    # (`_plot.plot_channel` / `m4_decimate_channel`), not here.
    channel_map: list[int]


_viewers: dict[str, ViewerState] = {}


def normalize_scale_mode(scale_mode: str) -> str:
    return "manual" if scale_mode == "manual" else "auto"


def _ensure_m4_downsampler(v: ViewerState) -> None:
    if v._m4_downsampler is None and not v._m4_numpy_fallback:
        try:
            from tsdownsample import M4Downsampler
        except ModuleNotFoundError:
            v._m4_numpy_fallback = True
        else:
            v._m4_downsampler = M4Downsampler()


def m4_decimate_channel(
    t: np.ndarray,
    col: np.ndarray,
    n_out: int,
    v: ViewerState,
) -> tuple[np.ndarray, np.ndarray]:
    """M4-decimate one channel's raw column independently, to ~`n_out` points.

    Each enabled channel calls this on its own — its own M4 index set, its
    own output x array — instead of the old approach of M4-decimating every
    enabled channel and then *unioning* all their index sets onto one
    shared x-axis. That union made the reduction vanish at high channel
    counts (the union of many channels' distinct M4 picks approaches the
    full window — e.g. 64 channels over a 5 s / 2048 Hz window unioned to
    the *entire* window, zero point reduction). Decimating per channel
    instead bounds total draw points at `n_channels * n_out`, independent
    of window length or sample rate.
    """
    n = len(col)
    if n <= n_out:
        return t, col
    _ensure_m4_downsampler(v)
    col = np.ascontiguousarray(col)
    if v._m4_downsampler is None:
        idx = _m4_indices_numpy(col, n_out)
    else:
        # tsdownsample's M4Downsampler requires n_out to be a multiple of 4;
        # round defensively here regardless of what the caller passed in.
        n_out_m4 = max(4, (n_out // 4) * 4)
        idx = v._m4_downsampler.downsample(  # type: ignore
            col, n_out=n_out_m4
        )
    idx = np.asarray(idx, dtype=np.intp)
    return t[idx], col[idx]


#: Oversampling factor applied to the plot's pixel width when sizing each
#: channel's M4 target — a few points per pixel keeps sharp features
#: visible without materially increasing draw cost.
_DECIMATE_PIXEL_FACTOR = 3.0
#: Floor on the width-derived target so a very narrow (or not-yet-laid-out)
#: plot never collapses decimation down to near nothing.
_DECIMATE_MIN_POINTS = 64


def resolve_decimation_target(plot_width_px: float, v: ViewerState) -> int:
    """Per-channel M4 output size, sized to the plot's own pixel width.

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


def _m4_indices_numpy(y: np.ndarray, n_out: int) -> np.ndarray:
    n = len(y)
    if n <= n_out:
        return np.arange(n, dtype=np.intp)

    n_bins = max(1, n_out // 4)
    edges = np.linspace(0, n, n_bins + 1, dtype=np.intp)
    idx = np.empty(n_bins * 4, dtype=np.intp)
    pos = 0
    for start, end in zip(edges[:-1], edges[1:], strict=True):
        if end <= start:
            continue
        segment = y[start:end]
        idx[pos] = start
        idx[pos + 1] = start + int(np.argmin(segment))
        idx[pos + 2] = start + int(np.argmax(segment))
        idx[pos + 3] = end - 1
        pos += 4
    return np.unique(idx[:pos])


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

    Must run before :func:`build_signal_frame` so the frame can decimate
    only the enabled columns.

    The selection is cached on `v` keyed by `(stream_key, n_channels)`, so
    a `selectable` viewer that flips between streams restores each
    stream's own selection instead of resetting a single shared one — and
    a channel-count change on the active stream (e.g. a reconnect at a
    different channel count) is treated as a fresh key rather than
    clobbering that stream's other-size selection.

    `initial_channels` seeds
    :func:`~myogestic.widgets.signals._channel_grid.resolve_initial` only
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


def build_signal_frame(
    stream: Stream,
    v: ViewerState,
    enabled: set[int],
) -> SignalFrame | None:
    """Read one live/frozen snapshot, slice the visible window, and filter.

    Slices to `enabled` columns only — `data` is compacted to that subset,
    see `SignalFrame.channel_map` for how to translate a column of `data`
    back to its real channel index. `data_full` / `data_win` stay
    full-width for consumers that still need every channel (e.g.
    per-channel-scale ranges, diagnostics, and the per-channel plot loop
    itself, all keyed by real channel index).

    Does *not* decimate: the old shared-union M4 decimation used to run
    here, over all enabled columns at once, before this function returned.
    That union made the reduction vanish at high channel counts (see
    `m4_decimate_channel`'s docstring). Decimation now happens per channel,
    sized to the plot's own pixel width, inside the plot loop
    (`_plot.plot_channel`) — so this function only ever needs to hand it
    the raw (filtered, windowed, enabled-column-sliced) samples.
    """
    frame_start = _time.perf_counter()
    if v.paused and v.frozen_data is not None and v.frozen_ts is not None:
        ts_raw = v.frozen_ts
        data_raw = v.frozen_data
    else:
        raw = stream.get_raw_snapshot()
        if raw is None:
            return None
        ts_raw, data_raw = raw
        if v.paused:
            v.frozen_ts = ts_raw.copy()
            v.frozen_data = data_raw.copy()

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
        start_idx = int(np.searchsorted(ts_raw, last_ts - v.window, side="left"))
    else:
        start_idx = 0
    data_win = data_raw[start_idx:]
    ts_win = ts_raw[start_idx:]
    # Caller (viewer.py) guards `stream.info is None` before building a frame.
    assert stream.info is not None
    data_win = apply_display_filter(data_win, v.display_filter, stream.info.fs)

    # Slice to only the enabled columns — `data_win` stays full-width (it's
    # stored on the frame for consumers that index it by real channel), but
    # `data` only ever exposes the enabled subset.
    channel_map = sorted(c for c in enabled if 0 <= c < n_channels)
    data_sel = data_win[:, channel_map]

    return SignalFrame(
        data=data_sel,
        data_full=data_raw,
        ts_win=ts_win,
        data_win=data_win,
        n_channels=n_channels,
        n_points=len(data_sel),
        frame_start=frame_start,
        channel_map=channel_map,
    )
