"""Prediction cards show an idle reason or a labelled probability per class."""

from types import SimpleNamespace

import pytest
from imgui_bundle import imgui

from myogestic.widgets import PredictionLabel


def _record_text(monkeypatch):
    seen = []
    text, colored = imgui.text_unformatted, imgui.text_colored

    def plain(label):
        seen.append(label)
        text(label)

    def color(tone, label):
        seen.append(label)
        colored(tone, label)

    monkeypatch.setattr(imgui, "text_unformatted", plain)
    monkeypatch.setattr(imgui, "text_colored", color)
    return seen


@pytest.mark.parametrize("state,model,reason", [
    ("idle", None, "train or load a model"),
    ("idle", object(), "ready to predict"),
    ("predicting", object(), "waiting for first prediction"),
])
def test_prediction_idle_has_dash_and_reason(imgui_frame, monkeypatch, state, model, reason):
    pipeline = SimpleNamespace(predictions={}, model=model, predict_hz=20,
                               app=SimpleNamespace(ctx=SimpleNamespace(state=state)))
    label = PredictionLabel(pipeline, ["Rest", "Fist"], show_probability=True)
    seen = _record_text(monkeypatch)
    imgui_frame(label.ui)
    assert "—" in seen
    assert reason in seen


def test_prediction_card_shows_every_class_probability(imgui_frame, monkeypatch):
    pipeline = SimpleNamespace(predictions={"class": 1, "proba": [0.2, 0.8]}, model=object(),
                               predict_hz=20, app=SimpleNamespace(ctx=SimpleNamespace(state="predicting")))
    label = PredictionLabel(pipeline, ["Rest", "Fist"], show_probability=True)
    seen, bars = _record_text(monkeypatch), []
    bar = imgui.progress_bar

    def remember(value, size, overlay):
        bars.append((value, size.y))
        bar(value, size, overlay)

    monkeypatch.setattr(imgui, "progress_bar", remember)
    imgui_frame(label.ui)
    assert "Fist" in seen and "Rest" in seen
    assert "every 50 ms" in seen
    assert "20%" in seen and "80%" in seen
    assert [value for value, _ in bars] == [0.2, 0.8]
    assert all(0 < height < imgui.get_text_line_height() for _, height in bars)


def test_prediction_only_source_still_renders(imgui_frame, monkeypatch):
    """The existing screenshot tool supplies only predictions, without a live app."""
    pipeline = SimpleNamespace(predictions={"class": 1, "proba": [0.2, 0.8]})
    seen = _record_text(monkeypatch)
    label = PredictionLabel(pipeline, ["Rest", "Fist"])
    monkeypatch.setattr(imgui, "progress_bar", lambda *a: pytest.fail("probabilities are opt-in"))
    imgui_frame(label.ui)
    assert "Fist" in seen


def test_probability_values_align_with_class_labels(imgui_frame, monkeypatch):
    from myogestic import _theme

    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    positions = {}
    text, colored = imgui.text_unformatted, imgui.text_colored

    def plain(label):
        text(label)
        positions[label] = imgui.get_item_rect_min().y

    def color(tone, label):
        colored(tone, label)
        positions[label] = imgui.get_item_rect_min().y

    monkeypatch.setattr(imgui, "text_unformatted", plain)
    monkeypatch.setattr(imgui, "text_colored", color)
    pipeline = SimpleNamespace(predictions={"class": 1, "proba": [0.2, 0.8]})
    imgui_frame(PredictionLabel(pipeline, ["Rest", "Fist"], show_probability=True).ui)
    assert positions["Rest"] == positions["20%"]
    assert positions["Fist"] == positions["80%"]


@pytest.mark.parametrize("scale", [1., 2.])
@pytest.mark.parametrize("state,model,reason", [
    ("idle", None, "train or load a model"),
    ("idle", object(), "ready to predict"),
    ("predicting", object(), "waiting for first prediction"),
])
def test_idle_and_live_share_hero_size_and_centered_detail(
    imgui_frame, monkeypatch, scale, state, model, reason,
):
    from pathlib import Path

    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    style = imgui.get_style()
    style.scale_all_sizes(scale)
    style.font_scale_main = scale
    fonts = Path(_theme.__file__).parent / "assets" / "fonts"
    atlas = imgui.get_io().fonts
    display = atlas.add_font_from_file_ttf(str(fonts / "InstrumentSerif-Regular.ttf"), 28)
    mono = atlas.add_font_from_file_ttf(str(fonts / "IBMPlexMono-Regular.ttf"), 13)
    monkeypatch.setattr(_theme, "_DISPLAY_FONT", display)
    monkeypatch.setattr(_theme, "_MONO_FONT", mono)
    pipeline = SimpleNamespace(predictions={}, model=model, predict_hz=20,
                               app=SimpleNamespace(ctx=SimpleNamespace(state=state)))
    label = PredictionLabel(pipeline, ["Rest", "Fist"])
    text = imgui.text_colored
    items, cards, base_sizes = {}, [], []

    def capture(tone, value):
        font, size = imgui.get_font(), imgui.get_font_size()
        text(tone, value)
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        items[value] = (font, size, (lo.y + hi.y) / 2, hi.x, right)

    monkeypatch.setattr(imgui, "text_colored", capture)

    def draw():
        base_sizes.append(imgui.get_font_size())
        label.ui()
        cards.append(imgui.get_item_rect_size().y)

    # Auto-sized children settle on the next frame.
    for _ in range(3):
        imgui_frame(draw)
    idle_height = cards[-1]
    pipeline.predictions = {"class": 1}
    pipeline.app.ctx.state = "predicting"
    for _ in range(3):
        imgui_frame(draw)
    assert cards[-1] == idle_height
    for hero, detail in (("—", reason), ("Fist", "every 50 ms")):
        assert items[hero][0] == display
        assert items[hero][1] == pytest.approx(base_sizes[-1] * 2)
        assert items[detail][0] == mono
        assert items[detail][1] == pytest.approx(base_sizes[-1])
        assert items[detail][2] == pytest.approx(items[hero][2], abs=1)
        assert items[detail][3] == pytest.approx(items[detail][4], abs=1)
