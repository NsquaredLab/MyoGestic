"""Feature chips preserve selection and extraction while wrapping to fit."""

import numpy as np
import pytest
from imgui_bundle import imgui

from myogestic.widgets import FeatureSelector


@pytest.mark.parametrize("show_header", [True, False])
def test_feature_header_can_be_owned_by_a_step(imgui_frame, monkeypatch, show_header):
    import myogestic.widgets.training.feature_selector as module

    headers = []
    monkeypatch.setattr(module, "panel_header", headers.append)
    selector = FeatureSelector({"RMS": lambda x: x}, show_header=show_header)
    imgui_frame(selector.ui)
    assert headers == (["Features"] if show_header else [])
    assert selector.active_names == ["RMS"]


def test_feature_chips_toggle_in_order_and_allow_empty_selection(imgui_frame, monkeypatch):
    selector = FeatureSelector({"RMS": lambda x: x, "MAV": lambda x: x * 2}, default=["RMS"])
    button = imgui.small_button
    clicked = {"name": "MAV"}
    labels = []

    def press(label):
        labels.append(label)
        button(label)
        return label == clicked["name"]

    monkeypatch.setattr(imgui, "small_button", press)
    monkeypatch.setattr(imgui, "checkbox", lambda *a: pytest.fail("features must be chips"))
    imgui_frame(selector.ui)
    assert labels == ["RMS", "MAV"]
    assert selector.active_names == ["RMS", "MAV"]
    assert np.array_equal(selector(np.array([1])), [1, 2])
    clicked["name"] = "RMS"
    imgui_frame(selector.ui)
    assert selector.active_names == ["MAV"]
    clicked["name"] = "MAV"
    imgui_frame(selector.ui)
    assert selector.n_active == 0
    with pytest.raises(RuntimeError, match="no active features"):
        selector(np.array([1]))


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_feature_chips_wrap_inside_light_panel(imgui_frame, monkeypatch, scale):
    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    selector = FeatureSelector(dict.fromkeys(["RMS", "MAV", "WL", "VAR", "ZC"], lambda x: x))
    button = imgui.small_button
    boxes = []

    def remember(label):
        result = button(label)
        boxes.append((imgui.get_item_rect_min().y, imgui.get_item_rect_max().x))
        return result

    monkeypatch.setattr(imgui, "small_button", remember)
    bounds = []

    def draw():
        imgui.begin_child("chips", imgui.ImVec2(150 * scale, 180 * scale))
        bounds.append(imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x)
        selector.ui()
        imgui.end_child()

    imgui_frame(draw)
    assert len(boxes) == 5
    assert len({y for y, _ in boxes}) > 1
    assert all(right <= bounds[-1] + 1 for _, right in boxes)
