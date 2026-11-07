"""Time-axis labels stay readable as a viewer narrows or its font grows."""

import pytest
from imgui_bundle import imgui

from myogestic.widgets.signals._plot import _time_ticks


@pytest.mark.parametrize("window", [0.25, 5.0, 60.0, 3600.0])
@pytest.mark.parametrize("width", [90.0, 180.0, 300.0, 900.0])
@pytest.mark.parametrize("font_scale", [1.0, 2.0])
def test_time_labels_do_not_overlap(imgui_frame, window, width, font_scale):
    imgui.get_style().font_scale_main = font_scale

    def check():
        positions, labels = _time_ticks(window, width)
        assert labels.count("Time (s)") == 1
        assert len(positions) == len(labels)
        assert positions == sorted(positions)
        for i in range(1, len(positions)):
            distance = (positions[i] - positions[i - 1]) / window * width
            half_labels = sum(imgui.calc_text_size(label).x / 2 for label in labels[i - 1 : i + 1])
            assert distance >= half_labels + 4.0

    imgui_frame(check)


def test_wide_time_axis_keeps_the_existing_ticks(imgui_frame):
    def check():
        positions, labels = _time_ticks(5.0, 900.0)
        assert positions == [i / 2 for i in range(11)]
        assert labels == ["0", "0.5", "1", "1.5", "2", "Time (s)", "3", "3.5", "4", "4.5", "5"]

    imgui_frame(check)


@pytest.mark.parametrize("width", [150.0, 330.0, 900.0])
def test_viewer_thins_ticks_using_its_actual_plot_width(implot_frame, monkeypatch, width):
    """Include the channel-name gutter in the space available to time labels."""
    from imgui_bundle import implot

    from myogestic import Stream
    from myogestic.core import Context
    from myogestic.sources import SyntheticSource
    from myogestic.widgets import SignalViewer

    ctx = Context()
    stream = Stream("emg", source=SyntheticSource(n_channels=4, fs=500.0), window_ms=500)
    assert stream.reconnect()
    stream._acquire_step()
    ctx.streams["emg"] = stream
    viewer = SignalViewer("emg", show_controls=False, size=(width, 200))
    ticks, plot_widths = [], []
    real_ticks, real_end = implot.setup_axis_ticks, implot.end_plot

    def axis_ticks(axis, positions, labels, *args, **kwargs):
        if axis == implot.ImAxis_.x1:
            ticks.append((positions, labels))
        return real_ticks(axis, positions, labels, *args, **kwargs)

    def end_plot():
        plot_widths.append(implot.get_plot_size().x)
        real_end()

    monkeypatch.setattr(implot, "setup_axis_ticks", axis_ticks)
    monkeypatch.setattr(implot, "end_plot", end_plot)
    try:
        for _ in range(2):
            implot_frame(lambda: viewer.ui(ctx))
        assert ticks and plot_widths
        positions, labels = ticks[-1]
        assert labels.count("Time (s)") == 1
        for i in range(1, len(positions)):
            distance = (positions[i] - positions[i - 1]) / 5.0 * plot_widths[-1]
            half_labels = sum(imgui.calc_text_size(label).x / 2 for label in labels[i - 1 : i + 1])
            assert distance >= half_labels + 4.0
    finally:
        stream.disconnect()
