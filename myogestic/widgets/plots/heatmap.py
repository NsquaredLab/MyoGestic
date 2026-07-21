"""Heatmap widget for @app.ui (confusion matrix, correlation matrix, etc.).

from myogestic.widgets.plots.heatmap import Heatmap
"""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui, implot

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
        widget_id: str | None = None,
    ) -> None:
        self._label = label
        self._size = size
        self._label_fmt = label_fmt
        self._widget_id = widget_id

    def ui(self, data: np.ndarray) -> None:
        """Render the heatmap for the given frame.

        Parameters
        ----------
        data : np.ndarray
            2D array of values to render.
        """
        imgui.push_id(self._widget_id or self._label)
        try:
            if data.size == 0:
                imgui.text(f"{self._label}: no data")
                return

            values = np.ascontiguousarray(data, dtype=np.float64)

            if implot.begin_plot(self._label, imgui.ImVec2(*self._size)):
                implot.plot_heatmap(
                    "##heatmap",
                    values,
                    scale_min=float(values.min()),
                    scale_max=float(values.max()),
                    label_fmt=self._label_fmt,
                )
                implot.end_plot()
        finally:
            imgui.pop_id()
