"""Heatmap widget for @app.ui (confusion matrix, correlation matrix, etc.).

    from myogestic.widgets.heatmap import heatmap
"""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui, implot


def heatmap(
    label: str,
    data: np.ndarray,
    size: tuple[float, float] = (-1, 300),
    label_fmt: str = "%.1f",
) -> None:
    """2D heatmap."""
    if data.size == 0:
        imgui.text(f"{label}: no data")
        return

    values = np.ascontiguousarray(data, dtype=np.float64)

    if implot.begin_plot(label, imgui.ImVec2(*size)):
        implot.plot_heatmap(
            "##heatmap", values,
            scale_min=float(values.min()),
            scale_max=float(values.max()),
            label_fmt=label_fmt,
        )
        implot.end_plot()
