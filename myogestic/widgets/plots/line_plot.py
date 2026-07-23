"""Multi-channel line plot for @app.ui.

from myogestic.widgets.plots.line_plot import LinePlot
"""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui, implot

from myogestic.widgets.common import PALETTE, ensure_implot_style

__all__ = ["LinePlot"]


class LinePlot:
    """Multi-channel line plot widget.

    Parameters
    ----------
    label : str
        Plot label shown above the lines.
    size : tuple[float, float], optional
        Plot size in pixels, by default ``(-1, 200)``.
    widget_id : str | None, optional
        Explicit ImGui id scope. Defaults to ``label`` when omitted, so two
        instances with the same plot label don't collide on ImGui ids.

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
    ) -> None:
        self._label = label
        self._size = size
        self._widget_id = widget_id

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
            if len(data) == 0:
                imgui.text_disabled(f"{self._label}: no data")
                return

            if data.ndim == 1:
                data = data[:, np.newaxis]

            ensure_implot_style()
            if implot.begin_plot(self._label, imgui.ImVec2(*self._size)):
                for ch in range(data.shape[1]):
                    name = (
                        channel_names[ch]
                        if channel_names and ch < len(channel_names)
                        else f"ch{ch}"
                    )
                    # Colour from the shared PALETTE (like the scatter + signal
                    # viewer) so channel N is the same colour across the app,
                    # not ImPlot's separate default cycle.
                    c = PALETTE[ch % len(PALETTE)]
                    spec = implot.Spec()
                    spec.line_color = imgui.ImVec4(float(c[0]), float(c[1]), float(c[2]), 1.0)
                    implot.plot_line(name, np.ascontiguousarray(data[:, ch]), spec=spec)
                implot.end_plot()
        finally:
            imgui.pop_id()
