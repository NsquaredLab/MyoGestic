"""2D and 3D scatter plots for @app.ui (UMAP, t-SNE, PCA, etc.).

from myogestic.widgets.plots.scatter import Scatter2D, Scatter3D
"""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui, implot, implot3d

from myogestic.widgets.common import PALETTE

__all__ = ["Scatter2D", "Scatter3D"]


class Scatter2D:
    """2D scatter plot with per-class coloring.

    Parameters
    ----------
    label : str
        Plot label shown above the scatter.
    size : tuple[float, float], optional
        Plot size in pixels, by default ``(-1, 300)``.
    marker_size : float, optional
        Marker radius in pixels, by default ``3.0``.
    widget_id : str | None, optional
        Explicit ImGui id scope. Defaults to ``label`` when omitted, so two
        instances with the same plot label don't collide on ImGui ids.
    """

    def __init__(
        self,
        label: str,
        *,
        size: tuple[float, float] = (-1, 300),
        marker_size: float = 3.0,
        widget_id: str | None = None,
    ) -> None:
        self._label = label
        self._size = size
        self._marker_size = marker_size
        self._widget_id = widget_id

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
            if len(points) == 0:
                imgui.text(f"{self._label}: no data")
                return

            xs = np.ascontiguousarray(points[:, 0], dtype=np.float64)
            ys = np.ascontiguousarray(points[:, 1], dtype=np.float64)

            if implot.begin_plot(self._label, imgui.ImVec2(*self._size)):
                if labels is None:
                    spec = implot.Spec()
                    spec.marker_size = self._marker_size
                    implot.plot_scatter("##points", xs, ys, spec)
                else:
                    for cls in np.unique(labels):
                        mask = labels == cls
                        name = (
                            class_names[int(cls)]
                            if class_names and int(cls) < len(class_names)
                            else str(cls)
                        )
                        color = PALETTE[int(cls) % len(PALETTE)]
                        spec = implot.Spec()
                        spec.marker_size = self._marker_size
                        spec.marker_fill_color = imgui.ImVec4(color[0], color[1], color[2], 1.0)
                        implot.plot_scatter(name, xs[mask], ys[mask], spec)
                implot.end_plot()
        finally:
            imgui.pop_id()


class Scatter3D:
    """3D scatter plot with orbit camera.

    Parameters
    ----------
    label : str
        Plot label shown above the scatter.
    size : tuple[float, float], optional
        Plot size in pixels, by default ``(-1, 400)``.
    axis_names : tuple[str, str, str], optional
        Names for the X, Y and Z axes, by default ``("X", "Y", "Z")``.
    widget_id : str | None, optional
        Explicit ImGui id scope. Defaults to ``label`` when omitted, so two
        instances with the same plot label don't collide on ImGui ids.
    """

    def __init__(
        self,
        label: str,
        *,
        size: tuple[float, float] = (-1, 400),
        axis_names: tuple[str, str, str] = ("X", "Y", "Z"),
        widget_id: str | None = None,
    ) -> None:
        self._label = label
        self._size = size
        self._axis_names = axis_names
        self._widget_id = widget_id

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
            if len(points) == 0:
                imgui.text(f"{self._label}: no data")
                return

            xs = np.ascontiguousarray(points[:, 0], dtype=np.float64)
            ys = np.ascontiguousarray(points[:, 1], dtype=np.float64)
            zs = np.ascontiguousarray(points[:, 2], dtype=np.float64)

            if implot3d.begin_plot(self._label, imgui.ImVec2(*self._size)):
                implot3d.setup_axes(*self._axis_names)
                if labels is None:
                    implot3d.plot_scatter("##points", xs, ys, zs)
                else:
                    for cls in np.unique(labels):
                        mask = labels == cls
                        name = (
                            class_names[int(cls)]
                            if class_names and int(cls) < len(class_names)
                            else str(cls)
                        )
                        color = PALETTE[int(cls) % len(PALETTE)]
                        spec = implot3d.Spec()
                        spec.marker_fill_color = imgui.ImVec4(color[0], color[1], color[2], 1.0)
                        implot3d.plot_scatter(name, xs[mask], ys[mask], zs[mask], spec)
                implot3d.end_plot()
        finally:
            imgui.pop_id()
