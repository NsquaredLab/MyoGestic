"""Raw signal viewer — every visible sample, no decimation, bounded-copy render.

For when you need to see every sample exactly (debugging glitches,
validating timestamps, sanity-checking acquisition). For higher-channel
counts and longer windows, use [`SignalViewer`][] instead.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui, implot

from myogestic._theme import mono_font
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    PALETTE,
    SUCCESS,
    WARNING,
    ensure_implot_style,
    fit_text,
    mono_text,
    muted,
    panel_header,
    plot_empty,
    plot_legend,
    plot_size,
    segmented,
    ui_px,
)
from myogestic.widgets.signals._scan import _disconnected_ui

if TYPE_CHECKING:
    from myogestic.core import Context


@dataclass
class _RawViewerState:
    """Per-widget raw-viewer buffers, channel selection, window and FPS history."""

    window: float = 1.0
    channels: set[int] = field(default_factory=set)
    bufs: dict = field(default_factory=dict)
    specs: list = field(default_factory=list)
    fps: list[float] = field(default_factory=list)
    n_channels: int = -1


_raw_viewers: dict[str, _RawViewerState] = {}


class RawSignalViewer:
    """Every visible sample, with a Window selector and a Channels chip popup.

    Construct once and call [`ui`][] each frame. The header names the stream;
    the mono footer reports sample rate, selected channels, raw points and FPS.
    Disconnected and empty states explain the next step in the plot's space.

    Parameters
    ----------
    stream_name : str
        Stream to draw, as registered with ``app.streams``.
    size : tuple[float, float], optional
        Plot size in UI-scaled pixels, by default ``(-1, 300)``. Nonpositive
        dimensions fill the available space, reserving the footer.
    show_connect : bool, optional
        Offer a Connect button while detached. Turn it off when a StreamPanel
        or DevicePicker owns connecting, to avoid duplicate Connect controls.
    channel_height : float, optional
        Trace spacing in signal units. ``0`` derives spacing from the visible
        data. Set a common value when comparing several viewers.
    widget_id : str | None, optional
        State and ImGui identity, defaulting to ``stream_name``. Supply distinct
        ids for independent views of the same stream.
    show_title : bool, optional
        Show the panel title, by default ``True``. Window and Channels remain
        available when the title is hidden.

    Examples
    --------
    >>> from myogestic.widgets import RawSignalViewer
    >>> viewer = RawSignalViewer("emg", widget_id="raw:left")
    >>> viewer.ui(ctx)
    """

    def __init__(
        self,
        stream_name: str,
        *,
        size: tuple[float, float] = (-1, 300),
        channel_height: float = 0.0,
        show_connect: bool = True,
        widget_id: str | None = None,
        show_title: bool = True,
    ) -> None:
        self._stream_name = stream_name
        self._size = size
        self._channel_height = channel_height
        self._show_connect = show_connect
        self._widget_id = stream_name if widget_id is None else widget_id
        self._show_title = show_title

    def ui(self, ctx: Context) -> None:
        """Render the raw viewer. Call once per frame inside ``@app.ui``."""
        imgui.push_id(self._widget_id)
        try:
            self._draw(ctx)
        finally:
            imgui.pop_id()

    def _draw(self, ctx: Context) -> None:
        """Render one scoped viewer, requesting only its visible raw tail."""
        stream = ctx.streams.get(self._stream_name)
        if stream is None:
            self._header(None, IDLE)
            plot_empty("Stream not found", "Add this stream to the app.", self._size)
            return
        if stream.status != "connected" or stream.info is None:
            tone = DANGER if stream.last_error else WARNING if stream.info is not None else IDLE
            self._header(None, tone)
            imgui.begin_child("disconnected", plot_size(self._size))
            try:
                _disconnected_ui(self._stream_name, stream, show_connect=self._show_connect)
            finally:
                imgui.end_child()
            return

        r = _raw_viewers.setdefault(self._widget_id, _RawViewerState(window=stream._window))
        t_start = _time.perf_counter()
        self._header(r, SUCCESS)
        snapshot = stream.get_raw_snapshot_stable(r.window)
        if snapshot is None:
            plot_empty("No samples yet", "Start the source to display raw signals.", self._size)
            return
        _, _, _, all_ts, all_data = snapshot
        n_win = max(1, int(r.window * stream.info.fs))
        data, ts = all_data[-n_win:], all_ts[-n_win:]
        n_samples, n_channels = data.shape
        if r.n_channels != n_channels:
            r.channels = set(range(n_channels))
            r.specs, r.bufs = [], {}
            r.n_channels = n_channels
        ch_names = stream.info.channel_names
        series = [
            (ch, ch_names[ch] if ch_names and ch < len(ch_names) else f"ch{ch}")
            for ch in range(n_channels)
        ]
        popup_width = min(ui_px(320), imgui.get_content_region_avail().x)
        imgui.set_next_window_size_constraints(
            imgui.ImVec2(popup_width, 0), imgui.ImVec2(popup_width, ui_px(320))
        )
        if imgui.begin_popup("channels"):
            plot_legend(series, selected=r.channels)
            imgui.end_popup()
        if n_samples == 0:
            plot_empty("No samples yet", "Start the source to display raw signals.", self._size)
            return
        if not r.channels:
            hint = (
                "Open Channels and enable a channel."
                if n_channels
                else "Connect a source with signal channels."
            )
            plot_empty("No channels enabled", hint, self._size)
            return

        bufs = r.bufs
        if not bufs or bufs.get("cap", 0) < n_samples:
            cap = n_samples + 1024
            bufs = {"cap": cap, "xs": np.empty(cap, dtype=np.float64), "ys": {}}
            r.bufs = bufs
        xs = cast("np.ndarray", bufs["xs"])
        np.subtract(ts, ts[0], out=xs[:n_samples])
        channel_height = self._channel_height
        if channel_height <= 0:
            lo = min(float(np.min(data[:, ch])) for ch in r.channels)
            hi = max(float(np.max(data[:, ch])) for ch in r.channels)
            channel_height = (hi - lo) * 1.2 if hi > lo else 1.0

        ensure_implot_style()
        if not r.specs:
            for ch in range(n_channels):
                color = PALETTE[ch % len(PALETTE)]
                spec = implot.Spec()
                spec.line_color = imgui.ImVec4(*map(float, color), 0.9)
                r.specs.append(spec)
        flags = int(implot.Flags_.no_title | implot.Flags_.no_legend)
        footer = imgui.get_text_line_height_with_spacing()
        if implot.begin_plot("##raw", plot_size(self._size, footer=footer), flags):
            ys_bufs = cast("dict[int, np.ndarray]", bufs["ys"])
            for plot_idx, ch in enumerate(sorted(r.channels)):
                if ch not in ys_bufs:
                    ys_bufs[ch] = np.empty(bufs["cap"], dtype=np.float64)
                ys = ys_bufs[ch]
                np.add(data[:, ch], -plot_idx * channel_height, out=ys[:n_samples])
                r.specs[ch].line_weight = ui_px(1)
                implot.plot_line(f"##channel{ch}", xs[:n_samples], ys[:n_samples], r.specs[ch])
            implot.end_plot()
        r.fps.append(_time.perf_counter() - t_start)
        del r.fps[:-60]
        dt = float(np.mean(r.fps))
        fps = 1.0 / dt if dt > 0 else 0.0
        detail = f"{stream.info.fs:g} Hz · {len(r.channels)}/{n_channels} ch · {n_samples} pts/ch raw · {fps:.0f} fps"
        font = mono_font()
        if font is not None:
            imgui.push_font(font, imgui.get_style().font_size_base)
        clipped = fit_text(detail, imgui.get_content_region_avail().x)
        if font is not None:
            imgui.pop_font()
        mono_text(clipped, muted())
        imgui.set_item_tooltip(detail)

    def _header(self, state: _RawViewerState | None, tone: imgui.ImVec4) -> None:
        """Wrap the Window selector below the header in a narrow cell."""
        style = imgui.get_style()
        if state is None:
            if self._show_title:
                panel_header(f"Raw · {self._stream_name}", status=tone)
            return
        windows = [0.1, 1.0, 5.0]
        if state.window not in windows:
            windows[1] = state.window
            windows.sort()
        labels = [f"{win:g} s" for win in windows]
        controls = sum(
            imgui.calc_text_size(s).x + 2 * style.frame_padding.x for s in labels
        ) + ui_px(4)
        caption = imgui.calc_text_size("Window").x + style.item_spacing.x
        icon = fa.ICON_FA_LAYER_GROUP
        button_w = imgui.calc_text_size(icon).x + 2 * style.frame_padding.x
        width = imgui.get_content_region_avail().x
        inline = width >= controls + caption + button_w + ui_px(100)
        reserve = (
            button_w
            + style.item_spacing.x
            + (controls + caption + style.item_spacing.x if inline else 0)
        )
        if self._show_title:
            panel_header(f"Raw · {self._stream_name}", reserve=reserve, status=tone)
            imgui.set_item_tooltip("Connected")
            imgui.same_line()
        if not inline:
            imgui.set_cursor_pos_x(
                imgui.get_cursor_pos_x() + max(0.0, imgui.get_content_region_avail().x - button_w)
            )
        if imgui.button(f"{icon}##channels_button"):
            imgui.open_popup("channels")
        imgui.set_item_tooltip("Channels")
        if inline:
            imgui.same_line()
        if width < controls + caption:
            imgui.text_colored(muted(), "Window")
        else:
            imgui.align_text_to_frame_padding()
            imgui.text_colored(muted(), "Window")
            imgui.same_line()
        state.window = windows[segmented("window", labels, windows.index(state.window))]


__all__ = ["RawSignalViewer"]
