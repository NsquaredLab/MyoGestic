"""Step navigation and primary actions keep their state and ImGui stacks balanced."""

import pytest
from imgui_bundle import imgui

from myogestic import _theme


def _colors():
    """Copy the style so later pushes cannot change the snapshot."""
    return [tuple(imgui.get_style().color_(i)) for i in range(imgui.Col_.count)]


def _item_center():
    lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    return imgui.ImVec2((lo.x + hi.x) / 2, (lo.y + hi.y) / 2)


def _click(frame, draw, position):
    io = imgui.get_io()
    io.mouse_pos = position
    frame(draw)
    io.add_mouse_button_event(0, True)
    frame(draw)
    io.add_mouse_button_event(0, False)
    frame(draw)


def test_step_bar_defaults_to_first_step(imgui_frame):
    from myogestic.widgets import StepBar

    bar = StepBar(["A", "B"])

    def draw():
        assert bar.ui([False, False]) == 0

    imgui_frame(draw)


@pytest.mark.parametrize("done", [[False, False], [True, True]])
def test_step_bar_click_selects(imgui_frame, done):
    from myogestic.widgets import StepBar

    bar = StepBar(["A", "B"], widget_id=f"click:{done}")
    selected, positions = [], []

    def draw():
        before = _colors()
        selected.append(bar.ui(done))
        positions.append(_item_center())
        assert _colors() == before

    imgui_frame(draw)
    _click(imgui_frame, draw, positions[-1])
    imgui_frame(draw)
    assert selected[-2:] == [1, 1]


def test_step_bar_state_is_per_widget_id(imgui_frame):
    from myogestic.widgets import StepBar

    first = StepBar(["A", "B"], widget_id="first")
    second = StepBar(["A", "B"], widget_id="second")
    selections, positions = [], []

    def draw():
        active = first.ui([False, False])
        positions.append(_item_center())
        selections.append((active, second.ui([False, False])))

    imgui_frame(draw)
    _click(imgui_frame, draw, positions[-1])
    assert selections[-1] == (1, 0)
    # Identity survives reconstructing a bar or updating the data it displays.
    first = StepBar(["Connect", "Record"], widget_id="first")
    imgui_frame(draw)
    assert selections[-1] == (1, 0)


def test_step_bar_rejects_mismatched_done():
    from myogestic.widgets import StepBar

    with pytest.raises(ValueError, match="done.*steps"):
        StepBar(["A", "B"]).ui([False])


@pytest.mark.parametrize("dark", [False, True])
def test_primary_button_renders(imgui_frame, monkeypatch, dark):
    from myogestic.widgets.common import primary_button

    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()

    def draw():
        before = _colors()
        assert primary_button("Train") is False
        assert _colors() == before

    imgui_frame(draw)


def test_light_text_dim_alpha(imgui_frame, monkeypatch):
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    assert imgui.get_style().color_(imgui.Col_.text_disabled).w == pytest.approx(199 / 255)
