"""Test widget helpers are importable and callable (no GUI)."""

import numpy as np

from myogestic.widgets._common import PALETTE
from myogestic.widgets.heatmap import heatmap
from myogestic.widgets.line_plot import line_plot
from myogestic.widgets.log_panel import log_panel
from myogestic.widgets.popout import popout_panel
from myogestic.widgets.process_launcher import process_launcher
from myogestic.widgets.raw_signal import raw_signal_viewer
from myogestic.widgets.scatter import scatter2d, scatter3d
from myogestic.widgets.signal import signal_viewer
from myogestic.widgets.stream_panel import stream_panel


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
