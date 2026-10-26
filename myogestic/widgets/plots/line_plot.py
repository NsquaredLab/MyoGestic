"""Multi-channel line plot for @app.ui.

from myogestic.widgets.plots.line_plot import LinePlot
"""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui, implot

from myogestic.widgets.common import (
    PALETTE,
    ensure_implot_style,
    panel_header,
    plot_empty,
    plot_legend,
    plot_size,
    segmented,
    ui_px,
)

__all__ = ["LinePlot"]


class LinePlot:
    """Multi-channel line plot with a panel header and PALETTE-dot legend chips.

    Parameters
    ----------
    label : str
        Plot label shown above the lines.
    size : tuple[float, float], optional
        Plot size in UI-scaled pixels, by default ``(-1, 200)``.
        Nonpositive dimensions fill the available space, reserving the legend.
    widget_id : str | None, optional
        Explicit ImGui id scope, defaulting to ``label``. Supply distinct ids
        for instances with the same visible label.
    show_title : bool, optional
        Show the panel header, by default ``True``. The plot itself has no title.
    y_range : tuple[float, float] | None, optional
        Shared amplitude limits for comparisons. When supplied, start in Shared
        mode and offer an Auto / Shared control beside the header. ``None``
        keeps automatic scaling. Limits must be finite and increasing.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.widgets import LinePlot
    >>> plot = LinePlot("Channels")
    >>> plot.ui(np.array([[0.0, 1.0], [1.0, 0.0]]))
    """

    def __init__(
        self,
        label: str,
        *,
        size: tuple[float, float] = (-1, 200),
        widget_id: str | None = None,
        show_title: bool = True,
        y_range: tuple[float, float] | None = None,
    ) -> None:
        if y_range is not None and (not np.isfinite(y_range).all() or y_range[0] >= y_range[1]):
            raise ValueError("Pass y_range=(low, high) with finite low < high.")
        self._label = label
        self._size = size
        self._widget_id = widget_id
        self._show_title = show_title
        self._y_range = y_range
        self._shared_range = True

    def ui(self, data: np.ndarray, channel_names: list[str] | None = None) -> None:
        """Render the line plot for the given frame.

        Parameters
        ----------
        data : np.ndarray
            Samples of shape ``(n_samples,)`` or ``(n_samples, n_channels)``.
        channel_names : list[str] | None, optional
            Per-channel legend names. Falls back to ``ch{i}`` when omitted.
        """
        imgui.push_id(self._widget_id or self._label)
        try:
            self._header()
            if data.size == 0:
                plot_empty("No samples", "Provide samples to display the traces.", self._size)
                return

            if data.ndim == 1:
                data = data[:, np.newaxis]

            ensure_implot_style()
            series = [
                (ch, channel_names[ch] if channel_names and ch < len(channel_names) else f"ch{ch}")
                for ch in range(data.shape[1])
            ]
            footer = plot_legend(series, measure_only=True)
            flags = int(implot.Flags_.no_title | implot.Flags_.no_legend)
            if implot.begin_plot("##lines", plot_size(self._size, footer=footer), flags):
                shared = self._y_range is not None and self._shared_range
                implot.setup_axis(implot.ImAxis_.x1)
                implot.setup_axis(
                    implot.ImAxis_.y1,
                    None,
                    int(implot.AxisFlags_.lock if shared else implot.AxisFlags_.auto_fit),
                )
                if shared:
                    implot.setup_axis_limits(implot.ImAxis_.y1, *self._y_range, imgui.Cond_.always)
                for ch, name in series:
                    # The shared PALETTE, not ImPlot's separate default cycle, so
                    # channel N is the same colour across the app.
                    c = PALETTE[ch % len(PALETTE)]
                    spec = implot.Spec()
                    spec.line_color = imgui.ImVec4(float(c[0]), float(c[1]), float(c[2]), 1.0)
                    spec.line_weight = ui_px(1)
                    implot.plot_line(
                        f"{name}##channel{ch}", np.ascontiguousarray(data[:, ch]), spec=spec
                    )
                implot.end_plot()
            plot_legend(series)
        finally:
            imgui.pop_id()

    def _header(self) -> None:
        """Keep the scale switch beside the title when the cell has enough room."""
        options = ["Auto", "Shared"]
        style = imgui.get_style()
        controls = sum(
            imgui.calc_text_size(s).x + 2 * style.frame_padding.x for s in options
        ) + ui_px(2)
        inline = imgui.get_content_region_avail().x >= controls + ui_px(70)
        if self._show_title:
            panel_header(
                self._label,
                reserve=controls + style.item_spacing.x
                if inline and self._y_range is not None
                else 0.0,
            )
        if self._y_range is not None:
            if self._show_title and inline:
                imgui.same_line()
                imgui.set_cursor_pos_x(
                    imgui.get_cursor_pos_x()
                    + max(0.0, imgui.get_content_region_avail().x - controls)
                )
            self._shared_range = bool(segmented("scale", options, int(self._shared_range)))
