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
