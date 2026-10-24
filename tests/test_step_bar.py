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


def test_step_connectors_render(imgui_frame, monkeypatch):
    from myogestic.widgets import StepBar
    from myogestic.widgets.common import SUCCESS, hairline, ui_px

    bar = StepBar(["Connect", "Record", "Train"], widget_id="connectors")
    lines, buttons = [], []
    add_line, button = imgui.ImDrawList.add_line, imgui.button

    def capture_line(draw_list, start, end, color, thickness=1.0):
        lines.append((tuple(start), tuple(end), color, thickness))
        return add_line(draw_list, start, end, color, thickness=thickness)

    def capture_button(*args, **kwargs):
        result = button(*args, **kwargs)
        buttons.append((tuple(imgui.get_item_rect_min()), tuple(imgui.get_item_rect_max())))
        return result

    monkeypatch.setattr(imgui.ImDrawList, "add_line", capture_line)
    monkeypatch.setattr(imgui, "button", capture_button)
    imgui_frame(lambda: bar.ui([True, False, True]))

    assert len(lines) == 2
    for index, (start, end, _color, thickness) in enumerate(lines):
        assert end[0] - start[0] == pytest.approx(ui_px(24))
        assert start[1] == pytest.approx(end[1])
        assert start[1] == pytest.approx((buttons[index][0][1] + buttons[index][1][1]) / 2)
        assert buttons[index][1][0] <= start[0] < end[0] <= buttons[index + 1][0][0]
        assert thickness == pytest.approx(ui_px(1))
    complete = imgui.color_convert_u32_to_float4(lines[0][2])
    assert tuple(complete)[:3] == pytest.approx(tuple(SUCCESS)[:3], abs=1 / 255)
    assert 0 < complete.w < SUCCESS.w
    assert lines[1][2] == imgui.get_color_u32(hairline())


@pytest.mark.parametrize("done", [[False] * 4, [True, False, True, False], [True] * 4])
def test_step_buttons_share_top_edge(imgui_frame, monkeypatch, done):
    from myogestic.widgets import StepBar

    _theme.apply_theme()
    bar = StepBar(["Connect", "Record", "Train", "Drive"], widget_id=f"aligned:{done}")
    tops = []
    button = imgui.button

    def track(label, *args, **kwargs):
        clicked = button(label, *args, **kwargs)
        tops.append(imgui.get_item_rect_min().y)
        return clicked

    monkeypatch.setattr(imgui, "button", track)

    def draw():
        # Like the app header: larger brand text precedes the navigation.
        imgui.push_font(None, 22)
        imgui.text_unformatted("MyoGestic")
        imgui.pop_font()
        imgui.same_line()
        imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() - 2)
        bar.ui(done)

    imgui_frame(draw)
    assert len(tops) == 4
    assert tops == [tops[0]] * 4


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
