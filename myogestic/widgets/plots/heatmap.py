"""Heatmap widget for @app.ui (confusion matrix, correlation matrix, etc.).

from myogestic.widgets.plots.heatmap import Heatmap
"""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui, implot

from myogestic.widgets.common import ensure_implot_style

__all__ = ["Heatmap"]


class Heatmap:
    """2D heatmap widget.

    Parameters
    ----------
    label : str
        Plot label shown above the heatmap.
    size : tuple[float, float], optional
        Plot size in pixels, by default ``(-1, 300)``.
    label_fmt : str, optional
        Printf-style format for the per-cell value labels, by default ``"%.1f"``.
    colormap : int | None, optional
        An ``implot.Colormap_`` value. ``None`` (default) uses ``viridis`` — a
        perceptually-uniform map suited to continuous values (ImPlot's own
        default, "Deep", is categorical and misleads on a heatmap). Pass e.g.
        ``implot.Colormap_.rd_bu`` for signed / diverging data.
    widget_id : str | None, optional
        Explicit ImGui id scope. Defaults to ``label`` when omitted, so two
        instances with the same plot label don't collide on ImGui ids.
    """

    def __init__(
        self,
        label: str,
        *,
        size: tuple[float, float] = (-1, 300),
        label_fmt: str = "%.1f",
        colormap: int | None = None,
        widget_id: str | None = None,
    ) -> None:
        self._label = label
        self._size = size
        self._label_fmt = label_fmt
        # Perceptually-uniform default (``implot.Colormap_.viridis``). ImPlot's
        # own default is "Deep" — a *categorical* palette that maps continuous
        # values to non-monotonic colours, which is wrong for a heatmap. Pass a
        # diverging map (e.g. ``implot.Colormap_.rd_bu``) for signed data.
        self._colormap = colormap
        self._widget_id = widget_id

    def ui(
        self,
        data: np.ndarray,
        x_tick_labels: list[str] | None = None,
        y_tick_labels: list[str] | None = None,
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
        """
        imgui.push_id(self._widget_id or self._label)
        try:
            values = np.ascontiguousarray(data, dtype=np.float64)
            if values.size == 0 or values.ndim != 2:
                imgui.text_disabled(f"{self._label}: no data")
                return
            rows, cols = values.shape

            ensure_implot_style()
            cmap = implot.Colormap_.viridis if self._colormap is None else self._colormap
            implot.push_colormap(cmap)
            try:
                if implot.begin_plot(self._label, imgui.ImVec2(*self._size)):
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
                        scale_min=float(values.min()),
                        scale_max=float(values.max()),
                        label_fmt=self._label_fmt,
                        bounds_min=implot.Point(0.0, 0.0),
                        bounds_max=implot.Point(float(cols), float(rows)),
                    )
                    implot.end_plot()
            finally:
                implot.pop_colormap()
        finally:
            imgui.pop_id()
