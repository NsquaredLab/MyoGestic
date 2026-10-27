"""Timing fields fit their cells and reflow when a recording card is resized."""

import pytest
from imgui_bundle import imgui

from myogestic import _scale, _theme
from myogestic.core import Context
from myogestic.widgets import RecordingControls


@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("dark", [False, True])
def test_timing_fields_fit_and_stack_when_narrow(imgui_frame, monkeypatch, scale, dark):
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    controls = RecordingControls(
        on_record=lambda: None,
        on_stop=lambda: None,
        take_lengths=(3.0, 5.0, 10.0),
        warmups=(0.0, 1.0, 2.0, 3.0),
        timed=True,
        take_length=5.0,
        warmup=2.0,
    )
    captions, bounds, buttons = {}, {}, {}
    text_colored, button = imgui.text_colored, imgui.button

    def rect():
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        return lo.x, lo.y, hi.x, hi.y

    def caption(tone, label):
        if label in ("Take length", "Warm-up"):
            left = imgui.get_cursor_screen_pos().x
            bounds[label] = left, left + imgui.get_content_region_avail().x
        text_colored(tone, label)
        if label in bounds:
            captions[label] = rect()

    def segment(label, *args):
        result = button(label, *args)
        for key, caption in (("length", "Take length"), ("warmup", "Warm-up")):
            if f"##{key}_seg" in label:
                buttons.setdefault(caption, []).append(rect())
        return result

    monkeypatch.setattr(imgui, "text_colored", caption)
    monkeypatch.setattr(imgui, "button", segment)

    # Reuse the same card to exercise both directions of a live resize. Inspect
    # settled item rectangles: a window scrollbar cannot detect column overlap.
    for width in (600, 320, 600):

        def draw(width=width):
            captions.clear()
            bounds.clear()
            buttons.clear()
            imgui.begin_child(
                "timing-card",
                imgui.ImVec2(width, 400),
                child_flags=imgui.ChildFlags_.borders,
            )
            controls.ui(Context())
            imgui.end_child()

        for _ in range(4):
            imgui_frame(draw)

        for label, count in (("Take length", 3), ("Warm-up", 4)):
            assert len(buttons[label]) == count
            left, right = bounds[label]
            for lo_x, lo_y, hi_x, _ in buttons[label]:
                assert left <= lo_x < hi_x <= right + 1, (width, label, bounds, buttons)
                assert lo_y == buttons[label][0][1]
            assert captions[label][0] >= left
            assert captions[label][2] <= right + 1
            assert captions[label][3] <= buttons[label][0][1]

        if width == 320 and scale == 2.0:
            assert buttons["Take length"][-1][3] <= captions["Warm-up"][1]
            assert captions["Take length"][0] == captions["Warm-up"][0]
        else:
            assert captions["Take length"][1] == captions["Warm-up"][1]
            assert buttons["Take length"][0][1] == buttons["Warm-up"][0][1]

    assert controls._timed is True
    assert controls._take_lengths[controls._length_index] == 5.0
    assert controls._warmups[controls._warmup_index] == 2.0
