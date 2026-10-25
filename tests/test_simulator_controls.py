"""Simulator controls publish their value and remain usable in a narrow card."""

from types import SimpleNamespace

import numpy as np
import pytest
from imgui_bundle import imgui

from myogestic.widgets import SimulatorControls
from myogestic.widgets.signals import simulator_controls as controls

PRESETS = [("Rest", 0.0), ("Fist", 1.0)]


@pytest.fixture
def outlet():
    samples = []
    return SimpleNamespace(samples=samples, push_sample=lambda value: samples.append(value.copy()))


def test_export_and_lazy_outlet(monkeypatch, imgui_frame, outlet):
    from myogestic.tools import emg_generator
    from myogestic.widgets import __all__

    created = []
    monkeypatch.setattr(emg_generator, "control_outlet", lambda: created.append(outlet) or outlet)
    widget = SimulatorControls(PRESETS)
    assert "SimulatorControls" in __all__
    assert widget.value == 0.0 and not created
    # Advertise the outlet when the card first appears, before a preset click.
    for _ in range(2):
        imgui_frame(lambda: widget.ui(SimpleNamespace(state="idle")))
    assert created == [outlet] and not outlet.samples
    widget.set(1.0)
    assert created == [outlet]
    np.testing.assert_array_equal(outlet.samples, [[1.0]])
    assert outlet.samples[0].dtype == np.float32


def test_set_can_publish_before_first_frame(monkeypatch, outlet):
    from myogestic.tools import emg_generator

    monkeypatch.setattr(emg_generator, "control_outlet", lambda: outlet)
    widget = SimulatorControls(PRESETS)
    widget.set(2.0)
    assert widget.value == 2.0
    np.testing.assert_array_equal(outlet.samples, [[2.0]])


def _capture_chips(monkeypatch, click=None):
    selected, depth = [], []
    push, pop, button = controls.push_selected, controls.pop_selected, imgui.small_button

    def begin():
        depth.append(True)
        push()

    def end():
        depth.pop()
        pop()

    def chip(label):
        button(label)
        visible = label.split("##")[0]
        if depth:
            selected.append(visible)
        return visible == click

    monkeypatch.setattr(controls, "push_selected", begin)
    monkeypatch.setattr(controls, "pop_selected", end)
    monkeypatch.setattr(imgui, "small_button", chip)
    return selected, depth


def test_chip_pushes_value_and_updates_selection(monkeypatch, imgui_frame, outlet):
    widget = SimulatorControls(PRESETS, outlet=outlet)
    selected, depth = _capture_chips(monkeypatch, click="Fist")
    imgui_frame(lambda: widget.ui(SimpleNamespace(state="predicting")))
    assert widget.value == 1.0 and not depth
    np.testing.assert_array_equal(outlet.samples, [[1.0]])
    selected.clear()
    imgui_frame(lambda: widget.ui(SimpleNamespace(state="idle")))
    assert selected == ["Fist"] and not depth


@pytest.mark.parametrize("value,selected", [(0.0, ["Rest"]), (1.0, ["Fist"]), (2.0, [])])
def test_set_selects_matching_chip(value, selected, monkeypatch, imgui_frame, outlet):
    widget = SimulatorControls(PRESETS, outlet=outlet)
    widget.set(value)
    seen, depth = _capture_chips(monkeypatch)
    imgui_frame(lambda: widget.ui(SimpleNamespace(state="idle")))
    assert seen == selected and not depth
    assert len(outlet.samples) == 1


def test_recording_disables_controls_but_keeps_caption_visible(monkeypatch, imgui_frame, outlet):
    widget = SimulatorControls(PRESETS, outlet=outlet)
    disabled, captions = [], []
    begin, end, wrapped = imgui.begin_disabled, imgui.end_disabled, imgui.text_wrapped

    def disable(value=True):
        disabled.append(value)
        begin(value)

    def enable():
        disabled.pop()
        end()

    def caption(text):
        assert not any(disabled)
        captions.append(text)
        wrapped(text)

    def chip(label):
        assert any(disabled)
        return True

    monkeypatch.setattr(imgui, "begin_disabled", disable)
    monkeypatch.setattr(imgui, "end_disabled", enable)
    monkeypatch.setattr(imgui, "text_wrapped", caption)
    monkeypatch.setattr(imgui, "small_button", chip)
    imgui_frame(lambda: widget.ui(SimpleNamespace(state="recording")))
    assert not outlet.samples and widget.value == 0.0
    assert captions == ["The simulator follows the gesture being recorded."]
    widget.set(1.0)  # The recording callback still owns the signal.
    assert widget.value == 1.0 and len(outlet.samples) == 1


@pytest.mark.parametrize("state", ["idle", "recording"])
def test_narrow_card_fits_light_theme_at_double_scale(
    state, monkeypatch, imgui_frame, outlet,
):
    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    widget = SimulatorControls(
        [*PRESETS, ("A longer preset that must fit the card", 2.0)],
        outlet=outlet,
    )
    bounds, headers = [], []
    header = controls.panel_header

    def remember(title, **kwargs):
        headers.append((title, kwargs))
        header(title, **kwargs)

    monkeypatch.setattr(controls, "panel_header", remember)

    def draw():
        imgui.begin_child("narrow-simulator", imgui.ImVec2(320, 420))
        widget.ui(SimpleNamespace(state=state))
        bounds.append((imgui.get_scroll_max_x(), imgui.get_scroll_max_y(),
                       imgui.get_cursor_pos_y()))
        imgui.end_child()

    for _ in range(4):
        headers.clear()
        imgui_frame(draw)
    assert len(headers) == 1 and headers[0][0] == "Simulated EMG"
    assert headers[0][1]["status"] is not None
    assert bounds[-1][0:2] == (0, 0) and bounds[-1][2] <= 420


def test_widget_ids_keep_duplicate_controls_independent(monkeypatch, imgui_frame, outlet):
    first = SimulatorControls(PRESETS, outlet=outlet, widget_id="first")
    second = SimulatorControls(PRESETS, outlet=outlet, widget_id="second")
    ids, button = [], imgui.small_button

    def capture(label):
        ids.append(imgui.get_id(label))
        return button(label)

    monkeypatch.setattr(imgui, "small_button", capture)
    first.set(1.0)
    imgui_frame(lambda: [widget.ui(SimpleNamespace(state="idle")) for widget in (first, second)])
    assert len(set(ids)) == 4
    assert first.value == 1.0 and second.value == 0.0
