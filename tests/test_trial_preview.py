"""Trial previews retain waveform semantics while using the scaled review kit."""

from pathlib import Path

import numpy as np
import pytest
from imgui_bundle import imgui, implot

from myogestic import _scale, _theme
from myogestic.widgets import TrialPreview, common


@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("dark", [False, True])
def test_preview_header_band_and_scaled_plot(implot_frame, monkeypatch, scale, dark):
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    monkeypatch.setattr(common, "_IMPLOT_STYLED", False)
    text, bands, sizes = [], [], []
    plain, mono = imgui.text, imgui.text_unformatted
    shaded, begin = implot.plot_shaded, implot.begin_plot

    def capture(label):
        text.append(label)
        plain(label)

    def capture_mono(label):
        text.append(label)
        mono(label)

    def capture_band(label, xs, hi, lo, spec):
        bands.append(spec)
        shaded(label, xs, hi, lo, spec)

    def capture_size(label, size, **kwargs):
        sizes.append((size.x, size.y))
        return begin(label, size, **kwargs)

    monkeypatch.setattr(imgui, "text", capture)
    monkeypatch.setattr(imgui, "text_unformatted", capture_mono)
    monkeypatch.setattr(implot, "plot_shaded", capture_band)
    monkeypatch.setattr(implot, "begin_plot", capture_size)
    preview = TrialPreview(widget_id="band", band=(0.2, 0.6), size=(-1, 120))
    implot_frame(lambda: preview.ui(np.zeros((2, 100)), 100))
    assert "TRIAL PREVIEW" in text
    assert any("0.200–0.600 s" in label for label in text)
    assert sizes[-1] == (-1, 120 * scale)
    token = common.TRIAL_BAND
    assert bands[-1].fill_alpha == pytest.approx(token.w)
    assert tuple(bands[-1].fill_color)[:3] == pytest.approx(tuple(token)[:3])
    assert 0 < token.w < 1


def test_custom_band_samples_first_and_manual_range_still_work(implot_frame, monkeypatch):
    lines, bands = [], []
    line, shaded = implot.plot_line, implot.plot_shaded

    def capture_line(label, xs, ys, spec):
        lines.append((xs.copy(), ys.copy()))
        line(label, xs, ys, spec)

    def capture_band(label, xs, hi, lo, spec):
        bands.append((hi.copy(), lo.copy(), spec.fill_alpha, tuple(spec.fill_color)))
        shaded(label, xs, hi, lo, spec)

    monkeypatch.setattr(implot, "plot_line", capture_line)
    monkeypatch.setattr(implot, "plot_shaded", capture_band)
    preview = TrialPreview(
        widget_id="custom",
        data_layout="samples_first",
        title="Custom",
        band=(0, 0.1),
        band_color=(0.1, 0.2, 0.3, 0.4),
        gain=2,
        scale_mode="manual",
        y_range=(-1, 1),
    )
    implot_frame(lambda: preview.ui(np.array([[1.0, 2.0], [3.0, 4.0]]), 10))
    np.testing.assert_allclose(lines[0][1], [2, 6])
    np.testing.assert_allclose(lines[1][1], [2, 6])
    np.testing.assert_allclose(bands[0][0], [1.2, 1.2])
    np.testing.assert_allclose(bands[0][1], [-3.2, -3.2])
    assert bands[0][2] == pytest.approx(0.4)
    assert bands[0][3][:3] == pytest.approx((0.1, 0.2, 0.3))


@pytest.mark.parametrize("as_window", [False, True])
def test_empty_preview_still_shows_header_and_next_step(implot_frame, monkeypatch, as_window):
    seen = []
    disabled = imgui.text_disabled

    def capture(label):
        seen.append(label)
        disabled(label)

    monkeypatch.setattr(imgui, "text_disabled", capture)
    preview = TrialPreview(widget_id="empty-preview", as_window=as_window)
    implot_frame(lambda: preview.ui(np.empty((0, 0)), 100))
    assert any("Select a template" in label for label in seen)


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_preview_readout_fits_narrow_panel_in_mono(implot_frame, monkeypatch, scale):
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    font_path = Path(_theme.__file__).parent / "assets/fonts/IBMPlexMono-Regular.ttf"
    mono_font = imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 13)
    monkeypatch.setattr(_theme, "_MONO_FONT", mono_font)
    plain = imgui.text_unformatted
    items, bounds = [], []

    def capture(label):
        plain(label)
        items.append((label, imgui.get_item_rect_max().x, imgui.get_font()))

    monkeypatch.setattr(imgui, "text_unformatted", capture)
    preview = TrialPreview(widget_id="narrow-preview", size=(-1, 100))

    def draw():
        imgui.begin_child("preview-panel", imgui.ImVec2(320, 380))
        bounds.append(imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x)
        preview.ui(np.ones((2, 100)), 100)
        imgui.end_child()

    for _ in range(2):
        implot_frame(draw)
    assert items[-1][0].startswith("window 0.000")
    assert items[-1][1] <= bounds[-1] + 1
    assert items[-1][2] == mono_font
