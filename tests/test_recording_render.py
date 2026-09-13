"""Render smoke tests for the recording widgets (spec I2).

These use the `imgui_frame` fixture (see `tests/conftest.py`, and
`tests/test_viz.py` for the established pattern) to run one real ImGui layout
pass per case. A headless frame cannot be clicked, so every assertion here is
necessarily "this ctx/state combination renders without raising" — plus, where
`imgui.get_draw_data()` is available after the frame, that ImGui actually
emitted geometry for it. None of these assert that a *specific* button is
visible, enabled, or positioned — that would need a real renderer to inspect
draw commands per-widget, which this fixture does not provide.
"""

from __future__ import annotations

from imgui_bundle import imgui

from myogestic.core import AppState, Context
from myogestic.session import Session
from myogestic.widgets import RecordButton, RecordingControls


def _rendered_something() -> bool:
    dd = imgui.get_draw_data()
    return bool(dd) and dd.total_vtx_count > 0


def test_recording_controls_render_while_predicting_and_not_recording(
    imgui_frame, recordable_predicting
):
    """`RecordingControls` under a `predicting` state (registered recordable by the
    `recordable_predicting` fixture, the way `myogestic.ml` does) with no take open:
    verifies the frame renders without raising, i.e. the "may start a take from here"
    layout path (`_transport` -> "record") does not crash.
    """
    ctx = Context()
    ctx.state = "predicting"
    flagged = {"record": False, "stop": False}
    controls = RecordingControls(
        on_record=lambda: flagged.__setitem__("record", True),
        on_stop=lambda: flagged.__setitem__("stop", True),
    )

    imgui_frame(lambda: controls.ui(ctx))

    assert _rendered_something()


def test_recording_controls_render_rec_pill_while_recording_under_predicting(imgui_frame, tmp_path):
    """`RecordingControls` with a take open (`ctx.recording = True`) under `predicting`:
    verifies the `REC` pill branch (`ctx.recording and ctx.state != AppState.RECORDING`)
    renders without raising.
    """
    ctx = Context()
    ctx.state = "predicting"
    ctx.recording = True
    ctx.session = Session(str(tmp_path))
    controls = RecordingControls(on_record=lambda: None, on_stop=lambda: None)

    imgui_frame(lambda: controls.ui(ctx))

    assert _rendered_something()


def test_recording_controls_render_state_pill_only_while_recording(imgui_frame):
    """`RecordingControls` with a take open under the plain `recording` state: verifies
    the state-pill-only branch (no extra `REC` pill, since `ctx.state == AppState.RECORDING`
    already) renders without raising.
    """
    ctx = Context()
    ctx.state = AppState.RECORDING
    ctx.recording = True
    controls = RecordingControls(on_record=lambda: None, on_stop=lambda: None)

    imgui_frame(lambda: controls.ui(ctx))

    assert _rendered_something()


def test_record_button_renders_disabled_under_training(imgui_frame):
    """`RecordButton` under `training` (not in `RECORDABLE_STATES` and not recording):
    verifies the disabled-Record + hover-tooltip-guard path renders without raising.
    """
    ctx = Context()
    ctx.state = "training"
    button = RecordButton(on_record=lambda: None, on_stop=lambda: None)

    imgui_frame(lambda: button.ui(ctx))

    assert _rendered_something()
