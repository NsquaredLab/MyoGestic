"""Test widget classes are importable and render-ready (no GUI)."""

import numpy as np

from myogestic.widgets.common import PALETTE
from myogestic.widgets.panels.log_panel import LogPanel
from myogestic.widgets.panels.popout import popout_panel
from myogestic.widgets.panels.process_launcher import ProcessLauncher
from myogestic.widgets.plots.heatmap import Heatmap
from myogestic.widgets.plots.line_plot import LinePlot
from myogestic.widgets.plots.scatter import Scatter2D, Scatter3D
from myogestic.widgets.signals.raw import RawSignalViewer
from myogestic.widgets.signals.stream_panel import StreamPanel
from myogestic.widgets.signals.viewer import SignalViewer


def test_palette_shape():
    assert PALETTE.shape == (10, 3)
    assert PALETTE.dtype == np.float32


def test_widget_classes_have_ui():
    """Every widget is a class exposing a `.ui()` render method."""
    for widget_cls in (
        Scatter2D,
        Scatter3D,
        Heatmap,
        LinePlot,
        SignalViewer,
        RawSignalViewer,
        ProcessLauncher,
        StreamPanel,
        LogPanel,
    ):
        assert isinstance(widget_cls, type)
        assert callable(getattr(widget_cls, "ui", None))


def test_popout_panel_is_callable():
    assert callable(popout_panel)


def test_imports_from_widgets_init():
    from myogestic.widgets import (
        LogPanel,
        ProcessLauncher,
        SignalViewer,
        StreamPanel,
        popout_panel,
    )

    for widget_cls in (SignalViewer, ProcessLauncher, StreamPanel, LogPanel):
        assert hasattr(widget_cls, "ui")
    assert callable(popout_panel)


def test_heatmap_renders_with_per_cell_ticks(implot_frame):
    """The heatmap renders one tick per cell — default index labels, custom
    labels, and a non-square grid — without error."""
    cm = np.array([[0.9, 0.1], [0.2, 0.8]])
    hm = Heatmap("Confusion")
    implot_frame(lambda: hm.ui(cm))
    implot_frame(lambda: hm.ui(cm, x_tick_labels=["A", "B"], y_tick_labels=["A", "B"]))
    implot_frame(lambda: hm.ui(np.arange(6.0).reshape(2, 3)))
