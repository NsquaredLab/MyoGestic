"""Test widget helpers are importable and callable (no GUI)."""

import numpy as np

from myogestic.widgets.common import PALETTE
from myogestic.widgets.panels.log_panel import log_panel
from myogestic.widgets.panels.popout import popout_panel
from myogestic.widgets.panels.process_launcher import process_launcher
from myogestic.widgets.plots.heatmap import heatmap
from myogestic.widgets.plots.line_plot import line_plot
from myogestic.widgets.plots.scatter import scatter2d, scatter3d
from myogestic.widgets.signals.raw import raw_signal_viewer
from myogestic.widgets.signals.stream_panel import stream_panel
from myogestic.widgets.signals.viewer import signal_viewer


def test_palette_shape():
    assert PALETTE.shape == (10, 3)
    assert PALETTE.dtype == np.float32


def test_scatter2d_is_callable():
    assert callable(scatter2d)


def test_scatter3d_is_callable():
    assert callable(scatter3d)


def test_heatmap_is_callable():
    assert callable(heatmap)


def test_line_plot_is_callable():
    assert callable(line_plot)


def test_signal_viewer_is_callable():
    assert callable(signal_viewer)


def test_raw_signal_viewer_is_callable():
    assert callable(raw_signal_viewer)


def test_process_launcher_is_callable():
    assert callable(process_launcher)


def test_stream_panel_is_callable():
    assert callable(stream_panel)


def test_log_panel_is_callable():
    assert callable(log_panel)


def test_popout_panel_is_callable():
    assert callable(popout_panel)


def test_imports_from_widgets_init():
    from myogestic.widgets import (
        log_panel,
        popout_panel,
        process_launcher,
        signal_viewer,
        stream_panel,
    )

    assert callable(signal_viewer)
    assert callable(process_launcher)
    assert callable(stream_panel)
    assert callable(log_panel)
    assert callable(popout_panel)
