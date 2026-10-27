"""The studio example's own render paths, run headless.

`examples/synthetic/control_map_studio.py` guards its `main()`, so the module imports
without opening a window and its helpers can be driven directly. That matters because a
slider that only misbehaves when you *type* into it is a path no other test reaches: the
sliders render every frame and are covered by simply drawing them, but the typed field
appears only after a double-click, and an ImGui misuse there takes the whole app down
rather than misdrawing a widget.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

STUDIO = pathlib.Path(__file__).parent.parent / "examples" / "synthetic" / "control_map_studio.py"


@pytest.fixture(scope="module")
def studio():
    """The example, imported without running it."""
    pytest.importorskip("imgui_bundle")
    spec = importlib.util.spec_from_file_location("control_map_studio", STUDIO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_typing_a_value_into_a_slider_does_not_crash(studio, imgui_frame):
    """Double-clicking a slider opens a field; drawing it must not assert.

    It did. `imgui.input_float` is `InputScalar` underneath, and ImGui asserts that
    `EnterReturnsTrue` is *not* set on it — the flag is an `InputText` one, and the scalar
    wrappers handle Enter themselves. So the one interaction the slider's own tooltip
    advertises, "double-click (or Ctrl+Click) to type a value", raised

        IM_ASSERT( (flags & ImGuiInputTextFlags_EnterReturnsTrue) == 0 )

    out of the render callback and killed the window. Nothing caught it, because a
    RuntimeError from ImGui's assert is not an exception the frame loop expects to survive.
    """
    studio.levels["close"] = 0.25
    studio.typing["close"] = 0.25
    try:
        imgui_frame(lambda: studio._typed_value_ui("close", 200.0, "close"))
    finally:
        studio.typing.pop("close", None)
        studio.levels.pop("close", None)


def test_the_typed_field_draws_without_a_label(studio, imgui_frame):
    """A hidden id, so the narrowed field does not drag the label in with it.

    The field takes a different ImGui id from the slider it replaces, which is why it
    survives its own opening: the mouse is still down from the second click, and handed the
    slider's id ImGui would see the active widget change type underneath itself and drop
    the field on the frame it appeared.
    """
    studio.levels["close"] = 0.0
    studio.typing["close"] = 0.0
    seen: list[str] = []
    try:
        imgui_frame(lambda: seen.append(studio._typed_value_ui("close", 200.0, None) or ""))
    finally:
        studio.typing.pop("close", None)
        studio.levels.pop("close", None)
    assert seen, "the field did not draw"


def test_connect_reports_a_refusing_target_instead_of_taking_the_window_down(
    studio, tmp_path, monkeypatch
):
    """`_manifests()` asks the target, and asking can now be refused as well as unheard.

    It was called *outside* the `try` that exists for exactly this reason, so the version
    gate raised straight out of a click handler — the failure the comment on that `try`
    says must not happen. The refusal is worth showing; it is not worth the window.
    """

    class TooOld:
        def capabilities(self):
            raise ValueError("speaks control vocabulary 1 ... Update the target.")

    path = tmp_path / "map.toml"
    path.write_text('[dofs]\nclose = "vhi.prediction.index"\n')
    monkeypatch.setattr(studio, "TARGETS", [("vhi", TooOld())])
    monkeypatch.setattr(studio, "documents", [studio._new_document(path)])
    monkeypatch.setattr(studio, "active", 0)

    studio._connect()  # must not raise

    assert "vocabulary 1" in studio.failure, studio.failure
    assert studio.bus is None


@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize(
    "armed,refusal", [(False, ""), (True, ""), (False, "Enable Accessibility access.")]
)
def test_keyboard_card_uses_a_state_row_and_a_balanced_chip(
    studio,
    imgui_frame,
    monkeypatch,
    scale,
    armed,
    refusal,
):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from imgui_bundle import imgui

    from myogestic import _scale, _theme
    from myogestic.widgets import common

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    actions, rows, toggles, buttons, selected = [], [], [], [], []
    keys = SimpleNamespace(
        claims={"walk"},
        armed=armed,
        arm_refusal=refusal,
        arm=lambda: actions.append("arm"),
        disarm=lambda: actions.append("disarm"),
    )
    monkeypatch.setattr(studio, "keys", keys)
    monkeypatch.setattr(studio, "keyboard_error", "")
    original_button, original_checkbox = imgui.button, imgui.checkbox
    bounds = {}

    @contextmanager
    def row(tone=None, **kwargs):
        rows.append(tone)
        with common.tinted_row(tone, **kwargs) as width:
            yield width

    def button(label, *args):
        original_button(label, *args)
        buttons.append((label, imgui.get_item_rect_max().x))
        return label.startswith("Send keys") and not refusal

    def checkbox(*args):
        toggles.append(args[0])
        return original_checkbox(*args)

    def push():
        selected.append("push")
        common.push_selected()

    def pop():
        selected.append("pop")
        common.pop_selected()

    monkeypatch.setattr(studio, "tinted_row", row, raising=False)
    monkeypatch.setattr(studio, "push_selected", push, raising=False)
    monkeypatch.setattr(studio, "pop_selected", pop, raising=False)
    monkeypatch.setattr(imgui, "button", button)
    monkeypatch.setattr(imgui, "checkbox", checkbox)

    def draw():
        imgui.begin_child("keyboard-card", imgui.ImVec2(320, 400))
        bounds["right"] = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        studio._keyboard_ui()
        imgui.end_child()

    imgui_frame(draw)
    assert not toggles, "persistent keyboard arming must be a selected chip"
    assert rows == [common.DANGER if refusal else common.WARNING if armed else common.IDLE]
    assert selected == (["push", "pop"] if armed else [])
    assert actions == ([] if refusal else ["disarm" if armed else "arm"])
    assert buttons and all(right <= bounds["right"] + 1 for _, right in buttons)


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_map_fields_keep_labels_above_full_width_controls(studio, imgui_frame, monkeypatch, scale):
    from types import SimpleNamespace

    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    monkeypatch.setattr(studio, "bus", SimpleNamespace(push=lambda values: None))
    monkeypatch.setattr(studio, "levels", {"a_rather_long_control_name": 0.25, "close": 0.5})
    monkeypatch.setattr(studio, "states", {"operator_gesture": ("Rest", "Fist")})
    labels, fields, values, bounds = [], [], [], {}
    original_text, original_slider, original_combo = (
        imgui.text_colored,
        imgui.slider_float,
        imgui.begin_combo,
    )

    def text(color, label):
        original_text(color, label)
        labels.append((label, imgui.get_item_rect_min().y))

    def slider(label, *args):
        result = original_slider(label, *args)
        fields.append((label, imgui.get_item_rect_min().y, imgui.get_item_rect_size().x))
        return result

    def combo(label, *args):
        result = original_combo(label, *args)
        fields.append((label, imgui.get_item_rect_min().y, imgui.get_item_rect_size().x))
        return result

    def mono(value, *args):
        from myogestic.widgets.common import mono_text

        values.append(value)
        mono_text(value, *args)

    monkeypatch.setattr(imgui, "text_colored", text)
    monkeypatch.setattr(imgui, "slider_float", slider)
    monkeypatch.setattr(imgui, "begin_combo", combo)
    monkeypatch.setattr(studio, "mono_text", mono, raising=False)

    def draw():
        imgui.begin_child("map-fields", imgui.ImVec2(320, 400))
        bounds["width"] = imgui.get_content_region_avail().x
        studio._sliders_ui()
        imgui.end_child()

    imgui_frame(draw)
    assert len(fields) == 3
    assert all(label.startswith("##") for label, _, _ in fields), "captions belong above controls"
    assert all(width >= bounds["width"] - 2 for _, _, width in fields)
    assert all(any(y < field_y for _, y in labels) for _, field_y, _ in fields)
    assert fields[0][1] < fields[1][1] < fields[2][1], "narrow fields must stack"
    assert "0.250" in values and "0.500" in values
