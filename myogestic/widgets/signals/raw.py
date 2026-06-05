"""Raw signal viewer — every sample, no decimation, zero-alloc render.

For when you need to see every sample exactly (debugging glitches,
validating timestamps, sanity-checking acquisition). For higher-channel
counts and longer windows, use :func:`signal_viewer` instead.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from imgui_bundle import imgui, implot

from myogestic.widgets.common import PALETTE
from myogestic.widgets.signals._scan import _disconnected_ui

if TYPE_CHECKING:
    from myogestic.core import Context


@dataclass
class _RawViewerState:
    """Per-stream raw-viewer state — buffers + channel toggles + FPS history."""

    window: float = 1.0
    channels: set[int] = field(default_factory=set)
    bufs: dict = field(default_factory=dict)
    specs: list = field(default_factory=list)
    fps: list[float] = field(default_factory=list)
    channels_initialized: bool = False


_raw_viewers: dict[str, _RawViewerState] = {}


def raw_signal_viewer(
    ctx: Context,
    stream_name: str,
    size: tuple[float, float] = (-1, 300),
    channel_height: float = 0.0,
) -> None:
    """Raw signal viewer — every sample, no decimation, zero-alloc render path."""
    stream = ctx.streams.get(stream_name)
    if stream is None:
        imgui.text(f"{stream_name}: not found")
        return
    if stream.status != "connected" or stream.info is None:
        _disconnected_ui(stream_name, stream)
        return

    r = _raw_viewers.get(stream_name)
    if r is None:
        r = _RawViewerState(window=stream._window)
        _raw_viewers[stream_name] = r

    t_start = _time.perf_counter()

    changed, new_win = imgui.slider_float(
        f"Window (s)##{stream_name}_raw_win",
        r.window,
        0.1,
        60.0,
        "%.1f s",
    )
    if changed:
        r.window = new_win

    snapshot = stream.get_raw_snapshot()
    if snapshot is None:
        imgui.text(f"{stream_name}: no data")
        return
    all_ts, all_data = snapshot
    n_win = int(r.window * stream.info.fs)
    if len(all_data) > n_win:
        data = all_data[-n_win:]
        ts = all_ts[-n_win:]
    else:
        data = all_data
        ts = all_ts

    n_samples, n_channels = data.shape

    if not r.channels_initialized or max(r.channels, default=-1) >= n_channels:
        r.channels = set(range(n_channels))
        r.specs = []
        r.bufs = {}  # invalidate per-channel ys buffers
        r.channels_initialized = True
    enabled = r.channels
    ch_names = stream.info.channel_names if stream.info else None

    for ch in range(n_channels):
        if ch > 0:
            imgui.same_line()
            if imgui.get_content_region_avail().x < 80:
                imgui.new_line()
        is_on = ch in enabled
        color = PALETTE[ch % len(PALETTE)]
        if is_on:
            imgui.push_style_color(
                imgui.Col_.button, imgui.ImVec4(color[0], color[1], color[2], 0.7)
            )
        else:
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.3, 0.3, 0.3, 0.5))
        label = ch_names[ch] if ch_names and ch < len(ch_names) else f"ch{ch}"
        if imgui.button(f"{label}##{stream_name}_rawtog{ch}"):
            if is_on:
                enabled.discard(ch)
            else:
                enabled.add(ch)
        imgui.pop_style_color()

    if not enabled:
        imgui.text("No channels enabled")
        return

    bufs = r.bufs
    if not bufs or bufs.get("cap", 0) < n_samples:
        cap = n_samples + 1024
        bufs = {
            "cap": cap,
            "xs": np.empty(cap, dtype=np.float64),
            "ys": {ch: np.empty(cap, dtype=np.float64) for ch in range(n_channels)},
        }
        r.bufs = bufs

    xs = bufs["xs"]
    np.subtract(ts, ts[0], out=xs[:n_samples])
    xs_view = xs[:n_samples]

    if channel_height <= 0:
        d_min, d_max = np.inf, -np.inf
        for ch in enabled:
            d_min = min(d_min, float(np.min(data[:, ch])))
            d_max = max(d_max, float(np.max(data[:, ch])))
        data_range = d_max - d_min
        channel_height = data_range * 1.2 if data_range > 0 else 1.0

    if len(r.specs) < n_channels:
        r.specs = []
        for ch in range(n_channels):
            c = PALETTE[ch % len(PALETTE)]
            s = implot.Spec()
            s.line_color = imgui.ImVec4(c[0], c[1], c[2], 0.9)
            s.line_weight = 1.0
            r.specs.append(s)
    specs = r.specs

    if implot.begin_plot(f"{stream_name}##{stream_name}_raw", imgui.ImVec2(size[0], size[1])):
        plot_idx = 0
        for ch in sorted(enabled):
            offset = -plot_idx * channel_height
            if ch not in bufs["ys"]:
                bufs["ys"][ch] = np.empty(bufs["cap"], dtype=np.float64)
            ys = bufs["ys"][ch]
            np.add(data[:, ch], offset, out=ys[:n_samples])
            label = ch_names[ch] if ch_names and ch < len(ch_names) else f"ch{ch}"
            implot.plot_line(f"{label}##{stream_name}_raw", xs_view, ys[:n_samples], specs[ch])
            plot_idx += 1
        implot.end_plot()

    frame_dt = _time.perf_counter() - t_start
    r.fps.append(frame_dt)
    if len(r.fps) > 60:
        r.fps.pop(0)
    avg_ms = np.mean(r.fps) * 1000
    fps = 1000.0 / avg_ms if avg_ms > 0 else 0
    imgui.text_colored(
        imgui.ImVec4(0.5, 0.5, 0.5, 1.0),
        f"{fps:.0f} fps ({avg_ms:.1f} ms) | "
        f"fs={stream.info.fs:.0f} Hz | "
        f"{len(enabled)}/{n_channels} ch | "
        f"{n_samples} pts/ch (raw)",
    )
