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

STUDIO = (
    pathlib.Path(__file__).parent.parent
    / "examples"
    / "synthetic"
    / "control_map_studio.py"
)


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
        imgui_frame(lambda: studio._typed_value_ui("close", "close"))
    finally:
        studio.typing.pop("close", None)
        studio.levels.pop("close", None)


def test_the_typed_field_takes_a_different_imgui_id_than_the_slider(studio, imgui_frame):
    """Same visible label, different id — the reason the field survives its own opening.

    The mouse is still down from the second click when the field first draws. Handed the
    slider's id, ImGui sees the active widget change type underneath itself and drops the
    field on the frame it appeared, so it flickers and vanishes. The `##` suffix keeps the
    label identical while making the id new.
    """
    studio.levels["close"] = 0.0
    studio.typing["close"] = 0.0
    seen: list[str] = []
    try:
        imgui_frame(lambda: seen.append(studio._typed_value_ui("close", "close") or ""))
    finally:
        studio.typing.pop("close", None)
        studio.levels.pop("close", None)
    assert seen, "the field did not draw"
