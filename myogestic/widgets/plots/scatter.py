"""2D and 3D scatter plots for @app.ui (UMAP, t-SNE, PCA, etc.).

from myogestic.widgets.plots.scatter import scatter2d, scatter3d
"""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui, implot, implot3d

from myogestic.widgets.common import PALETTE


def scatter2d(
    label: str,
    points: np.ndarray,
    labels: np.ndarray | None = None,
    class_names: list[str] | None = None,
    size: tuple[float, float] = (-1, 300),
    marker_size: float = 3.0,
) -> None:
    """2D scatter plot with per-class coloring."""
    if len(points) == 0:
        imgui.text(f"{label}: no data")
        return

    xs = np.ascontiguousarray(points[:, 0], dtype=np.float64)
    ys = np.ascontiguousarray(points[:, 1], dtype=np.float64)

    if implot.begin_plot(label, imgui.ImVec2(*size)):
        if labels is None:
            spec = implot.Spec()
            spec.marker_size = marker_size
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
                spec.marker_size = marker_size
                spec.marker_fill_color = imgui.ImVec4(color[0], color[1], color[2], 1.0)
                implot.plot_scatter(name, xs[mask], ys[mask], spec)
        implot.end_plot()


def scatter3d(
    label: str,
    points: np.ndarray,
    labels: np.ndarray | None = None,
    class_names: list[str] | None = None,
    size: tuple[float, float] = (-1, 400),
    axis_names: tuple[str, str, str] = ("X", "Y", "Z"),
) -> None:
    """3D scatter plot with orbit camera."""
    if len(points) == 0:
        imgui.text(f"{label}: no data")
        return

    xs = np.ascontiguousarray(points[:, 0], dtype=np.float64)
    ys = np.ascontiguousarray(points[:, 1], dtype=np.float64)
    zs = np.ascontiguousarray(points[:, 2], dtype=np.float64)

    if implot3d.begin_plot(label, imgui.ImVec2(*size)):
        implot3d.setup_axes(*axis_names)
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
