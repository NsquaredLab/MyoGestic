"""Live scaling always starts from base sizes and waits for valid display readings."""

from unittest.mock import Mock

import pytest
from imgui_bundle import imgui

from myogestic import _scale, _theme


@pytest.fixture(autouse=True)
def _fresh_scale(imgui_frame, monkeypatch):
    monkeypatch.delenv("MYOGESTIC_UI_SCALE", raising=False)
    _scale.set_ui_scale(None)
    _theme.reset_live_scale()
    imgui.get_main_viewport().dpi_scale = 1.0
    yield
    _scale.set_ui_scale(None)
    _theme.reset_live_scale()


def _style_values():
    """Include every public style field, including sizes the theme never sets."""
    style = imgui.get_style()
    values = {}
    for name in dir(imgui.Style):
        if name.startswith("_") or not isinstance(getattr(imgui.Style, name), property):
            continue
        value = getattr(style, name)
        values[name] = (value.x, value.y) if isinstance(value, imgui.ImVec2) else value
    return values


def _setup_style():
    _theme.apply_theme()
    # Include the viewport tweak and sizes set by an app's own style chain.
    style = imgui.get_style()
    style.window_rounding = 0.0
    style.cell_padding = (9.0, 7.0)
    style.child_border_size = 1.5


@pytest.mark.parametrize(
    "scales",
    [
        (0.75, 0.5, 0.75),
        (0.75, 0.5, 0.75, 0.5, 2.0, 0.5),
        (0.5, 0.75, 0.5, 2.0),
        (2.0, 0.5, 0.75, 1.0),
    ],
)
def test_scale_changes_match_a_single_application_for_every_style_field(scales, imgui_frame):
    _scale.set_ui_scale(scales[-1])
    _theme.apply_live_scale(_setup_style)
    imgui_frame(lambda: imgui.text("Still safe to draw"))
    expected = _style_values()

    imgui.get_current_context().style = imgui.Style()
    _theme.reset_live_scale()
    for scale in scales:
        _scale.set_ui_scale(scale)
        _theme.apply_live_scale(_setup_style)
        assert imgui.get_style().window_border_hover_padding > 0.0
        assert imgui.get_style().child_border_size == pytest.approx(1.5)
        imgui_frame(lambda: imgui.text("Still safe to draw"))

    assert _style_values() == expected


@pytest.mark.parametrize("invalid", [0.0, -1.0, float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("reading", ["os_scale", "width", "height"])
@pytest.mark.parametrize("already_styled", [False, True])
def test_invalid_display_readings_keep_previous_scale_and_skip_restyling(
    invalid, reading, already_styled
):
    if reading == "os_scale" and invalid == 0.0 and not already_styled:
        pytest.skip("an unknown DPI before the first style is styled at 1x; see the next test")
    io = imgui.get_io()
    viewport = imgui.get_main_viewport()
    io.display_size = (1920, 1200)
    viewport.dpi_scale = 1.5
    setup = Mock(wraps=_setup_style)
    if already_styled:
        _theme.apply_live_scale(setup)
    previous_scale = _scale.current_scale()
    previous_style = _style_values()
    previous_calls = setup.call_count
    if reading == "os_scale":
        viewport.dpi_scale = invalid
    elif reading == "width":
        io.display_size = (invalid, 1200)
    else:
        io.display_size = (1920, invalid)

    _theme.apply_live_scale(setup)

    assert _scale.current_scale() == previous_scale
    assert _style_values() == previous_style
    assert setup.call_count == previous_calls

    io.display_size = (1920, 1200)
    viewport.dpi_scale = 1.5
    _theme.apply_live_scale(setup)
    assert _scale.current_scale() == pytest.approx(1.5)
    assert setup.call_count == 1


def test_unknown_dpi_before_the_first_style_styles_at_1x():
    """A backend that never reports a DPI (0) must still get the theme, at 1x."""
    io = imgui.get_io()
    io.display_size = (1920, 1200)
    imgui.get_main_viewport().dpi_scale = 0.0
    setup = Mock(wraps=_setup_style)

    _theme.apply_live_scale(setup)

    setup.assert_called_once_with()
    assert _scale.current_scale() == pytest.approx(_scale.auto_scale(1.0, 1920, 1200))


def test_unchanged_scale_skips_restyling():
    setup = Mock(wraps=_setup_style)
    _scale.set_ui_scale(0.75)
    _theme.apply_live_scale(setup)
    expected = _style_values()

    _theme.apply_live_scale(setup)

    setup.assert_called_once_with()
    assert _style_values() == expected
