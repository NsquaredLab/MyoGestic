"""`carousel` steps a card at a time and only asks to look when somebody does."""

import pytest
from imgui_bundle import imgui

from myogestic.widgets import CarouselItem, carousel

CARDS = [
    CarouselItem("Galvani", "…A1B2 · RSSI −61", "this app's"),
    CarouselItem("Galvani", "…C3D4"),
]


@pytest.fixture
def clicking(monkeypatch):
    """Press the button whose id ends with the given suffix on the next frame."""
    pressed = []
    button = imgui.button

    def press(label, *args):
        result = button(label, *args)
        return bool(pressed) and label.endswith(pressed[0]) or result

    monkeypatch.setattr(imgui, "button", press)
    return pressed


@pytest.mark.parametrize(
    ("start", "click", "expected"),
    [
        (0, "##w_next", (1, False)),
        (1, "##w_prev", (0, False)),
        # Past the last card: one beyond it, which means "look for more".
        (1, "##w_next", (2, False)),
        (0, "##w_rescan", (0, True)),
    ],
)
def test_steps_and_asks_to_look(imgui_frame, clicking, start, click, expected):
    clicking.append(click)
    out = []
    imgui_frame(lambda: out.append(carousel("w", CARDS, start, can_look=True)))
    assert out == [expected]


def test_nothing_is_asked_for_without_a_click(imgui_frame, clicking):
    out = []
    imgui_frame(lambda: out.append(carousel("w", [], 5, can_look=True)))
    assert out == [(0, False)], "an empty list draws a placeholder card and clamps"
