"""2D and 3D scatter plots for @app.ui (UMAP, t-SNE, PCA, etc.).

from myogestic.widgets.plots.scatter import Scatter2D, Scatter3D
"""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui, implot, implot3d

from myogestic.widgets.common import (
    PALETTE,
    ensure_implot3d_style,
    ensure_implot_style,
    panel_header,
    plot_empty,
    plot_legend,
    plot_size,
    ui_px,
)

__all__ = ["Scatter2D", "Scatter3D"]


class Scatter2D:
    """2D scatter plot with a panel header and PALETTE-dot class legend chips.

    Parameters
    ----------
    label : str
        Plot label shown above the scatter.
    size : tuple[float, float], optional
        Plot size in UI-scaled pixels, by default ``(-1, 300)``.
        Nonpositive dimensions fill the available space, reserving the legend.
    marker_size : float, optional
        Marker radius in UI-scaled pixels, by default ``3.0``.
    widget_id : str | None, optional
        Explicit ImGui id scope, defaulting to ``label``. Supply distinct ids
        for instances with the same visible label.
    show_title : bool, optional
        Show the panel header, by default ``True``. The plot itself has no title.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.widgets import Scatter2D
    >>> scatter = Scatter2D("Embedding")
    >>> scatter.ui(np.array([[0.0, 0.0], [1.0, 1.0]]))
    """

    def __init__(
        self,
        label: str,
        *,
        size: tuple[float, float] = (-1, 300),
        marker_size: float = 3.0,
        widget_id: str | None = None,
        show_title: bool = True,
    ) -> None:
        self._label = label
        self._size = size
        self._marker_size = marker_size
        self._widget_id = widget_id
        self._show_title = show_title

    def ui(
        self,
        points: np.ndarray,
        labels: np.ndarray | None = None,
        class_names: list[str] | None = None,
    ) -> None:
        """Render the 2D scatter for the given frame.

        Parameters
        ----------
        points : np.ndarray
            Point coordinates of shape ``(n_points, 2)``.
        labels : np.ndarray | None, optional
            Per-point integer class labels for coloring. If omitted, all points
            share a single series.
        class_names : list[str] | None, optional
            Legend names indexed by class label. Falls back to the label value.
        """
        imgui.push_id(self._widget_id or self._label)
        try:
            if self._show_title:
                panel_header(self._label)
            if len(points) == 0:
                plot_empty(
                    "No points", "Provide point coordinates to display the scatter.", self._size
                )
                return

            xs = np.ascontiguousarray(points[:, 0], dtype=np.float64)
            ys = np.ascontiguousarray(points[:, 1], dtype=np.float64)

            ensure_implot_style()
            series = _series(labels, class_names)
            footer = plot_legend(series, measure_only=True)
            flags = int(implot.Flags_.no_title | implot.Flags_.no_legend)
            if implot.begin_plot("##scatter", plot_size(self._size, footer=footer), flags):
                for cls, name in series:
                    mask = slice(None) if labels is None else labels == cls
                    color = PALETTE[cls % len(PALETTE)]
                    spec = implot.Spec()
                    spec.marker_size = ui_px(self._marker_size)
                    spec.marker_fill_color = imgui.ImVec4(*map(float, color), 1.0)
                    spec.marker_line_color = spec.marker_fill_color
                    implot.plot_scatter(f"{name}##class{cls}", xs[mask], ys[mask], spec)
                implot.end_plot()
            plot_legend(series)
        finally:
            imgui.pop_id()


class Scatter3D:
    """Theme-styled 3D scatter with an orbit camera and PALETTE-dot legend chips.

    Parameters
    ----------
    label : str
        Plot label shown above the scatter.
    size : tuple[float, float], optional
        Plot size in UI-scaled pixels, by default ``(-1, 400)``.
        Nonpositive dimensions fill the available space, reserving the legend.
    axis_names : tuple[str, str, str], optional
        Names for the X, Y and Z axes, by default ``("X", "Y", "Z")``.
    widget_id : str | None, optional
        Explicit ImGui id scope, defaulting to ``label``. Supply distinct ids
        for instances with the same visible label.
    show_title : bool, optional
        Show the panel header, by default ``True``. The plot itself has no title.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.widgets import Scatter3D
    >>> scatter = Scatter3D("Embedding")
    >>> scatter.ui(np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]))
    """

    def __init__(
        self,
        label: str,
        *,
        size: tuple[float, float] = (-1, 400),
        axis_names: tuple[str, str, str] = ("X", "Y", "Z"),
        widget_id: str | None = None,
        show_title: bool = True,
    ) -> None:
        self._label = label
        self._size = size
        self._axis_names = axis_names
        self._widget_id = widget_id
        self._show_title = show_title

    def ui(
        self,
        points: np.ndarray,
        labels: np.ndarray | None = None,
        class_names: list[str] | None = None,
    ) -> None:
        """Render the 3D scatter for the given frame.

        Parameters
        ----------
        points : np.ndarray
            Point coordinates of shape ``(n_points, 3)``.
        labels : np.ndarray | None, optional
            Per-point integer class labels for coloring. If omitted, all points
            share a single series.
        class_names : list[str] | None, optional
            Legend names indexed by class label. Falls back to the label value.
        """
        imgui.push_id(self._widget_id or self._label)
        try:
            if self._show_title:
                panel_header(self._label)
            if len(points) == 0:
                plot_empty(
                    "No points", "Provide point coordinates to display the scatter.", self._size
                )
                return

            xs = np.ascontiguousarray(points[:, 0], dtype=np.float64)
            ys = np.ascontiguousarray(points[:, 1], dtype=np.float64)
            zs = np.ascontiguousarray(points[:, 2], dtype=np.float64)

            ensure_implot3d_style()
            series = _series(labels, class_names)
            footer = plot_legend(series, measure_only=True)
            flags = int(implot3d.Flags_.no_title | implot3d.Flags_.no_legend)
            if implot3d.begin_plot("##scatter", plot_size(self._size, footer=footer), flags):
                implot3d.setup_axes(*self._axis_names)
                for cls, name in series:
                    mask = slice(None) if labels is None else labels == cls
                    color = PALETTE[cls % len(PALETTE)]
                    spec = implot3d.Spec()
                    spec.marker_size = ui_px(3)
                    spec.marker_fill_color = imgui.ImVec4(*map(float, color), 1.0)
                    spec.marker_line_color = spec.marker_fill_color
                    implot3d.plot_scatter(f"{name}##class{cls}", xs[mask], ys[mask], zs[mask], spec)
                implot3d.end_plot()
            plot_legend(series)
        finally:
            imgui.pop_id()


def _series(labels: np.ndarray | None, names: list[str] | None) -> list[tuple[int, str]]:
    """Keep class identity and legend colours stable, even for sparse labels."""
    if labels is None:
        return [(0, "Points")]
    return [
        (int(cls), names[int(cls)] if names and 0 <= int(cls) < len(names) else str(cls))
        for cls in np.unique(labels)
    ]
