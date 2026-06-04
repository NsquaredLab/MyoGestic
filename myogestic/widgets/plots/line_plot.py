"""Multi-channel line plot for @app.ui.

    from myogestic.widgets.plots.line_plot import line_plot
"""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui, implot


def line_plot(
    label: str,
    data: np.ndarray,
    channel_names: list[str] | None = None,
    size: tuple[float, float] = (-1, 200),
) -> None:
    """Multi-channel line plot."""
    if len(data) == 0:
        imgui.text(f"{label}: no data")
        return

    if data.ndim == 1:
        data = data[:, np.newaxis]

    if implot.begin_plot(label, imgui.ImVec2(*size)):
        for ch in range(data.shape[1]):
            name = channel_names[ch] if channel_names and ch < len(channel_names) else f"ch{ch}"
            implot.plot_line(name, np.ascontiguousarray(data[:, ch]))
        implot.end_plot()
