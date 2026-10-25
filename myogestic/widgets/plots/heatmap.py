"""Heatmap widget for @app.ui (confusion matrix, correlation matrix, etc.).

from myogestic.widgets.plots.heatmap import Heatmap
"""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui, implot

from myogestic.widgets.common import (
    ensure_implot_style,
    fit_text,
    mono_text,
    muted,
    panel_header,
    plot_empty,
    plot_size,
    ui_px,
)

__all__ = ["Heatmap"]


class Heatmap:
    """2D heatmap with a panel header, mono range and continuous colour strip.

    Parameters
    ----------
    label : str
        Plot label shown above the heatmap.
    size : tuple[float, float], optional
        Plot size in UI-scaled pixels, by default ``(-1, 300)``.
        Nonpositive dimensions fill the available space.
    label_fmt : str, optional
        Printf-style format for the per-cell value labels, by default ``"%.1f"``.
    colormap : int | None, optional
        An ``implot.Colormap_`` value. ``None`` (default) uses ``viridis`` — a
        perceptually-uniform map suited to continuous values (ImPlot's own
        default, "Deep", is categorical and misleads on a heatmap). Pass e.g.
        ``implot.Colormap_.rd_bu`` for signed / diverging data.
    widget_id : str | None, optional
        Explicit ImGui id scope, defaulting to ``label``. Supply distinct ids
        for instances with the same visible label.
    show_title : bool, optional
        Show the panel header, by default ``True``. The plot itself has no title.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.widgets import Heatmap
    >>> heatmap = Heatmap("Confusion", label_fmt="%.2f")
    >>> heatmap.ui(np.array([[0.9, 0.1], [0.2, 0.8]]))
    """

    def __init__(
        self,
        label: str,
        *,
        size: tuple[float, float] = (-1, 300),
        label_fmt: str = "%.1f",
        colormap: int | None = None,
        widget_id: str | None = None,
        show_title: bool = True,
    ) -> None:
        self._label = label
        self._size = size
        self._label_fmt = label_fmt
        # ``None`` resolves to viridis at draw time; see the class docstring.
        self._colormap = colormap
        self._widget_id = widget_id
        self._show_title = show_title

    def ui(
        self,
        data: np.ndarray,
        x_tick_labels: list[str] | None = None,
        y_tick_labels: list[str] | None = None,
        vrange: tuple[float, float] | None = None,
    ) -> None:
        """Render the heatmap for the given frame.

        Parameters
        ----------
        data : np.ndarray
            2D array of values to render, row-major (row 0 is drawn at the top).
        x_tick_labels, y_tick_labels : list[str], optional
            Per-column / per-row axis labels (e.g. class names for a confusion
            matrix). When omitted, columns/rows are labelled by index. Extra
            labels beyond the grid size are ignored.
        vrange : tuple[float, float], optional
            Explicit ``(min, max)`` for the colour mapping. ``None`` (default)
            maps this frame's own ``data.min()``/``.max()``. Pass a **shared**
            range whenever several heatmaps are meant to be compared — with
            per-instance autoscaling a quiet grid and a loud one render
            identically — or a fixed one to stop colours drifting frame to frame.
        """
        imgui.push_id(self._widget_id or self._label)
        try:
            if self._show_title:
                panel_header(self._label)
            values = np.ascontiguousarray(data, dtype=np.float64)
            if values.size == 0 or values.ndim != 2:
                plot_empty("No grid data", "Provide a 2D array to display the heatmap.", self._size)
                return
            rows, cols = values.shape

            ensure_implot_style()
            cmap = implot.Colormap_.viridis if self._colormap is None else self._colormap
            implot.push_colormap(cmap)
            try:
                lo, hi = (
                    (float(values.min()), float(values.max()))
                    if vrange is None
                    else (float(vrange[0]), float(vrange[1]))
                )
                if not hi > lo:
                    hi = lo + 1e-12
                footer = (
                    imgui.get_text_line_height_with_spacing()
                    + ui_px(8)
                    + imgui.get_style().item_spacing.y
                )
                flags = int(implot.Flags_.no_title | implot.Flags_.no_legend)
                if implot.begin_plot("##heatmap_plot", plot_size(self._size, footer=footer), flags):
                    # One tick per cell, at its centre, so the axes read as the
                    # matrix's rows/columns (or the given labels) instead of a
                    # continuous 0-1 scale. Grid lines off + locked to the cells.
                    flags = int(implot.AxisFlags_.no_grid_lines | implot.AxisFlags_.lock)
                    implot.setup_axis(implot.ImAxis_.x1, None, flags)
                    implot.setup_axis(implot.ImAxis_.y1, None, flags)
                    implot.setup_axis_limits(implot.ImAxis_.x1, 0.0, float(cols))
                    implot.setup_axis_limits(implot.ImAxis_.y1, 0.0, float(rows))
                    x_labels = (
                        list(x_tick_labels)
                        if x_tick_labels is not None
                        else [str(j) for j in range(cols)]
                    )
                    y_labels = (
                        list(y_tick_labels)
                        if y_tick_labels is not None
                        else [str(i) for i in range(rows)]
                    )
                    implot.setup_axis_ticks(
                        implot.ImAxis_.x1, [j + 0.5 for j in range(cols)], x_labels[:cols]
                    )
                    # Row 0 draws at the top, so its tick sits at the top of the axis.
                    implot.setup_axis_ticks(
                        implot.ImAxis_.y1, [rows - i - 0.5 for i in range(rows)], y_labels[:rows]
                    )
                    implot.plot_heatmap(
                        "##heatmap",
                        values,
                        scale_min=lo,
                        scale_max=hi,
                        label_fmt=self._label_fmt,
                        bounds_min=implot.Point(0.0, 0.0),
                        bounds_max=implot.Point(float(cols), float(rows)),
                    )
                    implot.end_plot()
                _scale_strip(cmap)
                readout = f"{lo:g} — {hi:g}"
                mono_text(fit_text(readout, imgui.get_content_region_avail().x), muted())
                imgui.set_item_tooltip(readout)
            finally:
                implot.pop_colormap()
        finally:
            imgui.pop_id()


def _scale_strip(colormap: int) -> None:
    """Draw the grid's continuous colormap as a horizontal strip."""
    width = imgui.get_content_region_avail().x
    height = ui_px(8)
    pos = imgui.get_cursor_screen_pos()
    draw = imgui.get_window_draw_list()
    for i in range(32):
        left = imgui.get_color_u32(implot.sample_colormap(i / 32, colormap))
        right = imgui.get_color_u32(implot.sample_colormap((i + 1) / 32, colormap))
        draw.add_rect_filled_multi_color(
            imgui.ImVec2(pos.x + width * i / 32, pos.y),
            imgui.ImVec2(pos.x + width * (i + 1) / 32, pos.y + height),
            left,
            right,
            right,
            left,
        )
    imgui.dummy(imgui.ImVec2(width, height))
