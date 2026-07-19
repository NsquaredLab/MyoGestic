"""Real-time signal viewer.

The public widget is intentionally short; plotting/control internals live in
`myogestic.widgets.signals` helper modules so opening this file gives the reader
the widget flow first.

    from myogestic.widgets.signals.viewer import signal_viewer

    @app.ui
    def my_ui(ctx):
        signal_viewer(ctx, "emg")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import panel_header
from myogestic.widgets.signals._controls import (
    render_channel_controls,
    render_controls,
)
from myogestic.widgets.signals._plot import (
    apply_display_filter,
    render_footer,
    render_plot,
)
from myogestic.widgets.signals._scan import _disconnected_ui
from myogestic.widgets.signals._state import (
    build_signal_frame,
    get_viewer_state,
    resolve_enabled,
)

if TYPE_CHECKING:
    from myogestic.core import Context


def _channel_ranges(
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


def signal_viewer(
    ctx: Context,
    stream_name: str,
    size: tuple[float, float] = (-1, -1),
    n_pixels: int = 2000,
    channel_height: float = 0.0,
    show_diagnostics: bool = False,
    selectable: bool = False,
    scale_mode: str = "auto",
    y_range: tuple[float, float] = (-1.0, 1.0),
    show_markers: bool = False,
    window_s: float = 5.0,
) -> None:
    """Real-time multi-channel signal viewer.

    Includes decimation, pause, auto/manual Y scale, visual-only display
    filters, channel toggles, stats, stream retargeting, and label markers.
    The function argument `stream_name` is the stable widget ID; when
    `selectable=True`, the user may switch the active stream from the UI.

    `scale_mode` supports "auto" for ImPlot fitting and "manual" for the
    user-set `y_range`.

    `window_s` sets the *initial* display window in seconds — the user
    can still drag the slider afterwards. Defaults to 5 s, which is wide
    enough to scan visually across most real-time setups. Pass a smaller
    value when you want the display to mirror a short analysis window
    (classification often runs at 0.2 s, for example). The stream's
    ``buffer_ms`` must be at least this large.
    """
    v = get_viewer_state(
        ctx,
        stream_name,
        n_pixels=n_pixels,
        scale_mode=scale_mode,
        y_range=y_range,
        show_markers=show_markers,
        window_s=window_s,
    )
    active_stream = v.selected_stream or stream_name
    stream = ctx.streams.get(active_stream)

    panel_header(f"SIGNAL · {active_stream}", fa.ICON_FA_CHART_LINE)
    if stream is None:
        imgui.text(f"{active_stream}: not found")
        return
    if stream.status != "connected" or stream.info is None:
        _disconnected_ui(active_stream, stream)
        return

    render_controls(ctx, stream_name, active_stream, stream, v, selectable)

    # Resolve which channels are enabled from persistent state *before*
    # building the frame, so decimation only ever touches those columns —
    # the channel toggle buttons (rendered after the plot below) mutate
    # `v.channels` for the *next* frame, not this one.
    n_channels = stream.info.n_channels
    enabled = resolve_enabled(v, n_channels)

    frame = build_signal_frame(stream, v, enabled)
    if frame is None:
        imgui.text(f"{active_stream}: no data")
        return

    ch_names = stream.info.channel_names

    if v.display_filter == "rms_env":
        data = frame.data
    else:
        data = apply_display_filter(frame.data, v.display_filter, stream.info.fs)

    channel_ranges = None
    if v.per_channel_scale:
        full_data = apply_display_filter(frame.data_full, v.display_filter, stream.info.fs)
        channel_ranges = _channel_ranges(full_data, enabled)

    # Honour a "Rescale" button click from the controls bar: snap y_min /
    # y_max to the current visible data range across enabled channels,
    # then switch to Manual so it stays put. Uses the full-width, non-
    # decimated `frame.data_win` (real-channel-indexed) rather than `data`,
    # which is now compacted to the enabled subset.
    if v.rescale_pending:
        v.rescale_pending = False
        ranges = _channel_ranges(frame.data_win, enabled)
        if ranges:
            mins = [lo for lo, _ in ranges.values()]
            maxs = [hi for _, hi in ranges.values()]
            lo = min(mins)
            hi = max(maxs)
            span = hi - lo
            pad = span * 0.1 if span > 0 else 1.0
            v.y_min = lo - pad
            v.y_max = hi + pad
            v.scale_mode = "manual"

    if enabled:
        render_plot(
            ctx=ctx,
            stream_name=stream_name,
            stream=stream,
            v=v,
            frame=frame,
            data=data,
            channel_ranges=channel_ranges,
            enabled=enabled,
            ch_names=ch_names,
            # This frame's hover state isn't known yet — the toggle buttons
            # that report it render after the plot (below). One-frame lag
            # is imperceptible and keeps decimation from blocking on them.
            hovered_ch=v.last_hovered,
            size=size,
            channel_height=channel_height,
        )
    else:
        imgui.text("No channels enabled")

    # Draw the channel toggle buttons after the plot: this both reports
    # `hovered_ch` for next frame's render_plot call and mutates
    # `v.channels` (via the toggle buttons) for next frame's `enabled`.
    _, _, hovered_ch = render_channel_controls(stream_name, stream, v, n_channels)
    v.last_hovered = hovered_ch

    render_footer(
        stream_name=stream_name,
        stream=stream,
        v=v,
        frame=frame,
        enabled=enabled,
        ch_names=ch_names,
        show_diagnostics=show_diagnostics,
    )
