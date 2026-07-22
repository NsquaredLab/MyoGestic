"""Real-time signal viewer.

The public widget is intentionally short; plotting/control internals live in
`myogestic.widgets.signals` helper modules so opening this file gives the reader
the widget flow first.

    from myogestic.widgets import SignalViewer

    viewer = SignalViewer("emg")          # construct once

    @app.ui
    def my_ui(ctx):
        viewer.ui(ctx)                     # render each frame
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import panel_header
from myogestic.widgets.signals._controls import (
    render_channel_controls,
    render_controls,
)
from myogestic.widgets.signals._plot import (
    render_footer,
    render_plot,
    resolve_channel_ranges,
)
from myogestic.widgets.signals._scan import _disconnected_ui
from myogestic.widgets.signals._state import (
    build_signal_frame,
    get_viewer_state,
    resolve_enabled,
)

if TYPE_CHECKING:
    from myogestic.core import Context


class SignalViewer:
    """Real-time multi-channel signal viewer.

    Construct once with the stable config, then call :meth:`ui` with the
    live ``ctx`` each frame. Includes decimation, pause, auto/manual Y
    scale, visual-only display filters, channel toggles, stats, stream
    retargeting, and label markers.

    Parameters
    ----------
    stream_name
        The stable widget ID / stream to view. When ``selectable=True``,
        the user may switch the active stream from the UI — each stream's
        channel selection is tracked separately and restored when the user
        switches back.
    scale_mode
        ``"auto"`` for ImPlot fitting, ``"manual"`` for the user-set
        ``y_range``.
    window_s
        The *initial* display window in seconds — the user can still drag
        the slider afterwards. Defaults to 5 s. The stream's ``buffer_ms``
        must be at least this large.
    initial_channels
        Which channels open enabled, e.g. ``range(16)`` for "the first
        16" — do not pass a bare ``int`` (ambiguous with a single channel
        index). It seeds only the very first selection this viewer resolves;
        a different stream later shown through a ``selectable`` viewer falls
        back to the ``None`` policy. Once a selection exists (here or
        restored from a prior visit), the user's own toggle edits are never
        overwritten. ``None`` (default) falls back to
        :func:`~myogestic.widgets.signals._channel_grid.resolve_initial`'s
        policy: every channel when ``n_channels <= 32``, else the first 16.
    """

    def __init__(
        self,
        stream_name: str,
        *,
        size: tuple[float, float] = (-1, -1),
        n_pixels: int = 2000,
        channel_height: float = 0.0,
        show_diagnostics: bool = False,
        selectable: bool = False,
        scale_mode: str = "auto",
        y_range: tuple[float, float] = (-1.0, 1.0),
        show_markers: bool = False,
        window_s: float = 5.0,
        initial_channels: Iterable[int] | None = None,
    ) -> None:
        self._stream_name = stream_name
        self._size = size
        self._n_pixels = n_pixels
        self._channel_height = channel_height
        self._show_diagnostics = show_diagnostics
        self._selectable = selectable
        self._scale_mode = scale_mode
        self._y_range = y_range
        self._show_markers = show_markers
        self._window_s = window_s
        self._initial_channels = initial_channels

    def ui(self, ctx: Context) -> None:
        """Render the viewer. Call once per frame inside ``@app.ui``."""
        stream_name = self._stream_name
        v = get_viewer_state(
            ctx,
            stream_name,
            n_pixels=self._n_pixels,
            scale_mode=self._scale_mode,
            y_range=self._y_range,
            show_markers=self._show_markers,
            window_s=self._window_s,
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

        render_controls(ctx, stream_name, active_stream, stream, v, self._selectable)

        # Resolve which channels are enabled from persistent state *before*
        # building the frame, so the frame's column slice and the plot loop's
        # per-channel decimation only ever touch those columns.
        n_channels = stream.info.n_channels
        enabled = resolve_enabled(v, active_stream, n_channels, self._initial_channels)

        # Channel bar at the top, above the plot. It reads/mutates `v.channels`
        # (the same set `enabled` points at) and reports grid-hover — all
        # applied this frame, so channel toggles and the hover highlight take
        # effect immediately instead of a frame late.
        _, _, hovered_ch = render_channel_controls(stream_name, stream, v, n_channels)
        v.last_hovered = hovered_ch

        frame = build_signal_frame(stream, v, enabled)
        if frame is None:
            imgui.text_disabled(f"{active_stream}: no data")
            return

        ch_names = stream.info.channel_names

        # `render_plot` derives per-channel ranges from the drawn trace itself
        # (`resolve_channel_ranges`), so none need to be precomputed here.
        channel_ranges = None

        # Honour a "Rescale" button click from the controls bar: snap y_min /
        # y_max to the range of what is actually drawn (the raw window, or the
        # RMS envelope in rms_env mode), then switch to Manual so it stays put.
        if v.rescale_pending:
            v.rescale_pending = False
            ranges = resolve_channel_ranges(frame.data, frame.channel_map)
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
                channel_ranges=channel_ranges,
                enabled=enabled,
                ch_names=ch_names,
                hovered_ch=hovered_ch,
                size=self._size,
                channel_height=self._channel_height,
            )
        else:
            imgui.text("No channels enabled")

        render_footer(
            stream_name=stream_name,
            stream=stream,
            v=v,
            frame=frame,
            enabled=enabled,
            ch_names=ch_names,
            show_diagnostics=self._show_diagnostics,
        )


__all__ = ["SignalViewer"]
