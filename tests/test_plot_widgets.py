"""Plot chrome, shared scales and independent raw-viewer controls."""

from types import SimpleNamespace

import numpy as np
import pytest
from imgui_bundle import imgui, implot, implot3d

from myogestic import _scale
from myogestic.widgets import common
from myogestic.widgets.plots import heatmap, line_plot, scatter
from myogestic.widgets.signals import raw

PLOTS = (
    (heatmap, heatmap.Heatmap, implot, np.arange(6.0).reshape(2, 3)),
    (line_plot, line_plot.LinePlot, implot, np.arange(12.0).reshape(4, 3)),
    (scatter, scatter.Scatter2D, implot, np.arange(8.0).reshape(4, 2)),
    (scatter, scatter.Scatter3D, implot3d, np.arange(12.0).reshape(4, 3)),
)


def _stream(data=None):
    data = np.arange(24.0).reshape(8, 3) if data is None else data
    calls = []

    def snapshot(window):
        calls.append(window)
        return 0, len(data), 100.0, np.arange(len(data)) / 100.0, data

    return SimpleNamespace(
        status="connected",
        _window=1.0,
        last_error=None,
        info=SimpleNamespace(fs=100.0, channel_names=["one", "two", "three"]),
        get_raw_snapshot_stable=snapshot,
        calls=calls,
    )


@pytest.mark.parametrize("module,cls,api,data", PLOTS)
def test_plot_header_can_be_hidden_and_internal_title_is_off(
    implot_frame,
    monkeypatch,
    module,
    cls,
    api,
    data,
):
    headers, plots = [], []
    monkeypatch.setattr(module, "panel_header", lambda title, *a, **k: headers.append(title))
    begin = api.begin_plot

    def capture(title, size, flags=0):
        plots.append((title, size, flags))
        return begin(title, size, flags)

    monkeypatch.setattr(api, "begin_plot", capture)
    implot_frame(lambda: cls("Example", size=(-1, 80)).ui(data))
    implot_frame(lambda: cls("Hidden", show_title=False, size=(-1, 80)).ui(data))
    assert headers == ["Example"]
    assert len(plots) == 2
    for title, _, flags in plots:
        assert title.startswith("##")
        assert flags & api.Flags_.no_title
        assert flags & api.Flags_.no_legend


@pytest.mark.parametrize("module,cls,api,data", PLOTS)
def test_empty_plots_keep_header_and_explain_next_step(
    implot_frame,
    monkeypatch,
    module,
    cls,
    api,
    data,
):
    headers, messages = [], []
    monkeypatch.setattr(module, "panel_header", lambda title, *a, **k: headers.append(title))
    monkeypatch.setattr(imgui, "text_colored", lambda color, text: messages.append(text))
    implot_frame(lambda: cls("Empty").ui(data[:0]))
    assert headers == ["Empty"]
    assert any("no " in text.lower() for text in messages)
    assert any("provide" in text.lower() for text in messages)


def test_shared_line_range_defaults_to_shared_and_can_switch_to_auto(implot_frame, monkeypatch):
    limits, axes = [], []
    real_limits, real_axis = implot.setup_axis_limits, implot.setup_axis

    def capture_limits(axis, lo, hi, cond=0):
        limits.append((axis, lo, hi, cond))
        return real_limits(axis, lo, hi, cond)

    def capture_axis(axis, label=None, flags=0):
        axes.append((axis, flags))
        return real_axis(axis, label, flags)

    monkeypatch.setattr(implot, "setup_axis_limits", capture_limits)
    monkeypatch.setattr(implot, "setup_axis", capture_axis)
    plot = line_plot.LinePlot("Shared", y_range=(-10.0, 10.0), size=(-1, 100))
    implot_frame(lambda: plot.ui(np.array([0.01, 0.02])))
    assert (implot.ImAxis_.y1, -10.0, 10.0, imgui.Cond_.always) in limits
    limits.clear()
    monkeypatch.setattr(line_plot, "segmented", lambda *args: 0)
    implot_frame(lambda: plot.ui(np.array([0.01, 0.02])))
    assert not any(axis == implot.ImAxis_.y1 for axis, *_ in limits)
    assert axes[-1][1] & implot.AxisFlags_.auto_fit
    # Choosing Auto for this instance must not change another plot's initial mode.
    other = line_plot.LinePlot("Other", y_range=(-20.0, 20.0), size=(-1, 100))
    monkeypatch.setattr(line_plot, "segmented", lambda wid, opts, current: current)
    implot_frame(lambda: other.ui(np.array([1.0, 2.0])))
    assert (implot.ImAxis_.y1, -20.0, 20.0, imgui.Cond_.always) in limits


def test_heatmap_scale_uses_the_same_colormap_and_range(implot_frame, monkeypatch):
    readouts, maps = [], []
    monkeypatch.setattr(heatmap, "mono_text", lambda text, *a: readouts.append(text))
    sample = implot.sample_colormap

    def capture(t, cmap=None):
        maps.append(cmap)
        return sample(t, cmap)

    monkeypatch.setattr(implot, "sample_colormap", capture)
    plot = heatmap.Heatmap("Range", colormap=implot.Colormap_.plasma, size=(-1, 100))
    implot_frame(lambda: plot.ui(np.ones((2, 2)), vrange=(-2.0, 8.0)))
    assert any("-2" in text and "8" in text for text in readouts)
    assert maps and set(maps) == {implot.Colormap_.plasma}


@pytest.mark.parametrize("module,cls,api,data", PLOTS)
def test_fixed_sizes_scale_but_fill_width_does_not(
    implot_frame, monkeypatch, module, cls, api, data
):
    monkeypatch.setattr(_scale, "_current", 2.0)
    seen = []
    monkeypatch.setattr(api, "begin_plot", lambda title, size, *a, **k: seen.append(size) or False)
    implot_frame(lambda: cls("Scaled", size=(-1, 70)).ui(data))
    assert seen[0].x == -1
    assert seen[0].y == 140


@pytest.mark.parametrize("light", [False, True])
def test_scatter3d_style_follows_theme(implot_frame, light):
    (imgui.style_colors_light if light else imgui.style_colors_dark)()
    implot_frame(lambda: scatter.Scatter3D("3D", size=(-1, 100)).ui(np.ones((2, 3))))
    style = implot3d.get_style()
    assert style.get_color(implot3d.Col_.plot_bg).w == 0
    assert style.get_color(implot3d.Col_.frame_bg).w == 0
    assert style.get_color(implot3d.Col_.plot_border).w == 0
    grid = style.get_color(implot3d.Col_.axis_grid)
    border = common.hairline(0.5)
    assert tuple(grid) == pytest.approx(tuple(border))


def test_raw_viewers_have_independent_channels_windows_and_bounded_reads(implot_frame, monkeypatch):
    raw._raw_viewers.clear()
    stream = _stream()
    ctx = SimpleNamespace(streams={"emg": stream})
    a = raw.RawSignalViewer("emg", widget_id="raw:a", size=(-1, 80))
    b = raw.RawSignalViewer("emg", widget_id="raw:b", size=(-1, 80))
    implot_frame(lambda: a.ui(ctx))
    implot_frame(lambda: b.ui(ctx))
    sa, sb = raw._raw_viewers["raw:a"], raw._raw_viewers["raw:b"]
    sa.channels = {1}
    sa.window = 0.25
    implot_frame(lambda: a.ui(ctx))
    assert sa is not sb and sb.channels == {0, 1, 2} and sb.window == 1.0
    assert stream.calls[-1] == 0.25


@pytest.mark.parametrize("data", [np.empty((0, 3)), np.empty((5, 0))])
def test_raw_empty_snapshots_are_actionable(implot_frame, monkeypatch, data):
    messages = []
    real_text = imgui.text_colored
    monkeypatch.setattr(
        imgui,
        "text_colored",
        lambda color, text: (messages.append(text), real_text(color, text))[1],
    )
    ctx = SimpleNamespace(streams={"emg": _stream(data)})
    viewer = raw.RawSignalViewer("emg", widget_id="empty", size=(-1, 80))
    implot_frame(lambda: viewer.ui(ctx))
    assert any("sample" in text.lower() or "channel" in text.lower() for text in messages)


def test_raw_footer_and_title(implot_frame, monkeypatch):
    headers, footers = [], []
    monkeypatch.setattr(raw, "panel_header", lambda title, *a, **k: headers.append(title))
    monkeypatch.setattr(raw, "mono_text", lambda text, *a: footers.append(text))
    ctx = SimpleNamespace(streams={"emg": _stream()})
    implot_frame(lambda: raw.RawSignalViewer("emg", widget_id="footer").ui(ctx))
    assert headers == ["Raw · emg"]
    assert any("100 Hz · 3/3 ch · 8 pts/ch raw ·" in text and "fps" in text for text in footers)


@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize("kind", ["heat", "line", "2d", "3d", "raw"])
def test_plot_chrome_fits_narrow_cells_at_scale_two(implot_frame, monkeypatch, light, kind):
    monkeypatch.setattr(_scale, "_current", 2.0)
    style = imgui.get_style()
    style.scale_all_sizes(2.0)
    style.font_scale_main = 2.0
    (imgui.style_colors_light if light else imgui.style_colors_dark)()
    name = "a very long series label that must be clipped " * 3
    ctx = SimpleNamespace(streams={"emg": _stream()})
    widget, data = {
        "heat": (heatmap.Heatmap(name, size=(-1, 60)), np.ones((2, 2))),
        "line": (line_plot.LinePlot(name, size=(-1, 60), y_range=(-1, 1)), np.ones((4, 3))),
        "2d": (scatter.Scatter2D(name, size=(-1, 60)), np.ones((4, 2))),
        "3d": (scatter.Scatter3D(name, size=(-1, 60)), np.ones((4, 3))),
        "raw": (raw.RawSignalViewer("emg", size=(-1, 60)), ctx),
    }[kind]
    overflows = []

    def draw():
        imgui.begin_child(
            "narrow", imgui.ImVec2(320, 400), window_flags=imgui.WindowFlags_.horizontal_scrollbar
        )
        if kind == "line":
            widget.ui(data, channel_names=[name] * 3)
        elif kind in ("2d", "3d"):
            widget.ui(data, labels=np.array([0, 1, 0, 1]), class_names=[name] * 2)
        else:
            widget.ui(data)
        overflows.append(imgui.get_scroll_max_x())
        imgui.end_child()

    for _ in range(3):
        implot_frame(draw)
    assert overflows[-1] <= 1


def test_legend_and_series_keep_palette_identity_with_repeated_names(implot_frame, monkeypatch):
    plotted, legends = [], []
    real_plot, real_legend = implot.plot_line, line_plot.plot_legend

    def capture(label, values, *, spec):
        plotted.append((label, tuple(spec.line_color)))
        real_plot(label, values, spec=spec)

    def legend(series, **kwargs):
        if not kwargs.get("measure_only"):
            legends.extend(series)
        return real_legend(series, **kwargs)

    monkeypatch.setattr(implot, "plot_line", capture)
    monkeypatch.setattr(line_plot, "plot_legend", legend)
    implot_frame(
        lambda: line_plot.LinePlot("Same names", size=(-1, 80)).ui(
            np.ones((4, 2)), ["same", "same"]
        )
    )
    assert len({label for label, _ in plotted}) == 2
    assert legends == [(0, "same"), (1, "same")]
    for i, (_, color) in enumerate(plotted):
        assert color[:3] == pytest.approx(common.PALETTE[i])


@pytest.mark.parametrize(
    "cls,api,dim", [(scatter.Scatter2D, implot, 2), (scatter.Scatter3D, implot3d, 3)]
)
def test_unlabelled_scatter_uses_palette_zero(implot_frame, monkeypatch, cls, api, dim):
    colors = []
    real = api.plot_scatter

    def capture(*args):
        colors.append(tuple(args[-1].marker_fill_color))
        real(*args)

    monkeypatch.setattr(api, "plot_scatter", capture)
    implot_frame(lambda: cls("Points", size=(-1, 80)).ui(np.ones((2, dim))))
    assert colors[0][:3] == pytest.approx(common.PALETTE[0])


def test_raw_channels_popup_click_balances_styles_and_reaches_empty_state(
    implot_frame, monkeypatch
):
    raw._raw_viewers.clear()
    stream = _stream(np.ones((8, 1)))
    ctx = SimpleNamespace(streams={"emg": stream})
    viewer = raw.RawSignalViewer("emg", widget_id="click", size=(-1, 80))
    real_button = imgui.button
    clicked = set()

    def click(label, *args):
        result = real_button(label, *args)
        if ("channels_button" in label or label == "##series0") and label not in clicked:
            clicked.add(label)
            return True
        return result

    monkeypatch.setattr(imgui, "button", click)
    for _ in range(3):
        implot_frame(lambda: viewer.ui(ctx))
    assert "##series0" in clicked
    assert raw._raw_viewers["click"].channels == set()
    assert len(raw._raw_viewers["click"].specs) <= 1


def test_raw_missing_and_disconnected_keep_their_headers(implot_frame, monkeypatch):
    from myogestic.stream import Stream

    headers = []
    real = raw.panel_header

    def header(title, *args, **kwargs):
        headers.append((title, kwargs.get("status")))
        real(title, *args, **kwargs)

    monkeypatch.setattr(raw, "panel_header", header)
    viewer = raw.RawSignalViewer("missing", show_connect=False, size=(-1, 80))
    implot_frame(lambda: viewer.ui(SimpleNamespace(streams={})))
    ctx = SimpleNamespace(streams={"missing": Stream("missing", source=None, window_ms=1000)})
    implot_frame(lambda: viewer.ui(ctx))
    assert [title for title, _ in headers] == ["Raw · missing", "Raw · missing"]
    assert all(tone == common.IDLE for _, tone in headers)


@pytest.mark.parametrize("limits", [(1, 1), (2, -2), (np.nan, 1), (0, np.inf)])
def test_invalid_shared_ranges_explain_the_required_value(limits):
    with pytest.raises(ValueError, match="finite low < high"):
        line_plot.LinePlot("Invalid", y_range=limits)


@pytest.mark.parametrize("kind", ["heat", "line", "2d", "3d", "raw"])
def test_fill_height_keeps_the_legend_or_footer_inside_the_cell(implot_frame, kind):
    ctx = SimpleNamespace(streams={"emg": _stream()})
    widget, data = {
        "heat": (heatmap.Heatmap("Heat", size=(-1, -1)), np.ones((2, 2))),
        "line": (line_plot.LinePlot("Line", size=(-1, -1)), np.ones((4, 3))),
        "2d": (scatter.Scatter2D("2D", size=(-1, -1)), np.ones((4, 2))),
        "3d": (scatter.Scatter3D("3D", size=(-1, -1)), np.ones((4, 3))),
        "raw": (raw.RawSignalViewer("emg", size=(-1, -1)), ctx),
    }[kind]
    overflow = []

    def draw():
        imgui.begin_child("fill", imgui.ImVec2(320, 400))
        widget.ui(data)
        overflow.append(imgui.get_scroll_max_y())
        imgui.end_child()

    for _ in range(3):
        implot_frame(draw)
    assert overflow[-1] <= 1
