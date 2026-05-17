from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

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
    selected_stream: str | None = None
    scale_mode: str = "auto"
    y_min: float = -1.0
    y_max: float = 1.0
    per_channel_scale: bool = False
    rescale_pending: bool = False
    paused: bool = False
    frozen_ts: object | None = None
    frozen_data: object | None = None
    show_diagnostics: bool | None = None
    display_filter: str = "none"
    show_markers: bool = True
    show_retarget: bool = False
    _m4_downsampler: object | None = field(default=None, repr=False)
    _m4_numpy_fallback: bool = field(default=False, repr=False)


@dataclass
class SignalFrame:
    ts: np.ndarray
    data: np.ndarray
    data_full: np.ndarray
    ts_win: np.ndarray
    data_win: np.ndarray
    n_channels: int
    n_points: int
    n_total: int
    is_decimated: bool
    frame_start: float


_viewers: dict[str, ViewerState] = {}


def normalize_scale_mode(scale_mode: str) -> str:
    return "manual" if scale_mode == "manual" else "auto"


def apply_display_filter(data: np.ndarray, mode: str, fs: float) -> np.ndarray:
    """Apply visual-only transforms. Recording/model input is unaffected."""
    if mode == "rectify":
        return np.abs(data)
    if mode == "dc_removal":
        return data - data.mean(axis=0, keepdims=True)
    if mode != "rms_env" or len(data) < 4:
        return data

    k = max(4, int(0.01 * fs))
    if k >= len(data):
        return data
    sq = (data.astype(np.float32)) ** 2
    csum = np.cumsum(sq, axis=0)
    denom = np.arange(1, k + 1, dtype=np.float32)[:, None]
    rms_warm = np.sqrt(np.maximum(csum[:k] / denom, 0.0))
    rms_tail = np.sqrt(np.maximum((csum[k:] - csum[:-k]) / k, 0.0))
    return np.concatenate([rms_warm, rms_tail])


def _m4_decimate_visible_window(
    t: np.ndarray,
    d: np.ndarray,
    n_out: int,
    v: ViewerState,
) -> tuple[np.ndarray, np.ndarray]:
    if v._m4_downsampler is None and not v._m4_numpy_fallback:
        try:
            from tsdownsample import M4Downsampler
        except ModuleNotFoundError:
            v._m4_numpy_fallback = True
        else:
            v._m4_downsampler = M4Downsampler()

    idx_parts = []
    for ch in range(d.shape[1]):
        col = np.ascontiguousarray(d[:, ch])
        if v._m4_downsampler is None:
            idx = _m4_indices_numpy(col, n_out)
        else:
            idx = v._m4_downsampler.downsample(  # type: ignore[attr-defined]
                col, n_out=n_out
            )
        idx_parts.append(np.asarray(idx, dtype=np.intp))

    if not idx_parts:
        return t[:0], d[:0]

    all_idx = np.unique(np.concatenate(idx_parts))
    return t[all_idx], d[all_idx]


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
    window_seconds: float | None = None,
) -> ViewerState:
    v = _viewers.get(stream_name)
    if v is None:
        s0 = ctx.streams.get(stream_name)
        # Caller override wins; fall back to the stream's processing window
        # (typically tiny — 0.2 s for classification — which is fine for the
        # model but unreadable on screen).
        if window_seconds is not None:
            win0 = window_seconds
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


def build_signal_frame(stream: Stream, v: ViewerState) -> SignalFrame | None:
    """Read one live/frozen snapshot and return the visible window."""
    frame_start = _time.perf_counter()
    if v.paused and v.frozen_data is not None:
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
    data_win = apply_display_filter(data_win, v.display_filter, stream.info.fs)

    n_out = max(1, int(v.n_pixels)) * 4
    if len(data_win) > n_out:
        ts, data = _m4_decimate_visible_window(ts_win, data_win, n_out, v)
        is_decimated = True
    else:
        ts = ts_win
        data = data_win
        is_decimated = False

    n_total = len(data)

    return SignalFrame(
        ts=ts,
        data=data,
        data_full=data_raw,
        ts_win=ts_win,
        data_win=data_win,
        n_channels=n_channels,
        n_points=len(data),
        n_total=n_total,
        is_decimated=is_decimated,
        frame_start=frame_start,
    )
