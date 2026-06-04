"""Recording controls widget.

    from myogestic.widgets.recording import recording_controls

    @app.ui
    def my_ui(ctx):
        recording_controls(
            ctx,
            CLASSES,
            on_record=app.start_recording,
            on_stop=app.stop_recording,
            on_gesture=lambda i: ctrl_outlet.push_sample(...),
        )

Record/Stop + label buttons + state pill. Training/prediction controls live
in `myogestic.ml.widgets` (they require `Pipeline(app)`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.core import AppState
from myogestic.widgets._common import panel_header

if TYPE_CHECKING:
    from myogestic.core import Context


# Layout — local constants so users can read but not override.
# (Want a different layout? Write your own widget.)
_RECORD_BTN_W = 118
_LABEL_BTN_W = 100
_LABEL_BTN_H = 30


_PILL_PAD_Y = 4.0  # internal vertical padding inside the pill


def _status_pill(label: str, color: imgui.ImVec4) -> None:
    pad_x, pad_y = 10.0, _PILL_PAD_Y
    text = imgui.calc_text_size(label)
    size = imgui.ImVec2(text.x + pad_x * 2 + 12, text.y + pad_y * 2)
    imgui.dummy(size)
    p0, p1 = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    draw = imgui.get_window_draw_list()
    draw.add_rect_filled(p0, p1, imgui.get_color_u32(imgui.ImVec4(0.14, 0.17, 0.21, 1.0)), size.y * 0.5)
    y = (p0.y + p1.y) * 0.5
    draw.add_rect_filled(
        imgui.ImVec2(p0.x + pad_x - 1, y - 3),
        imgui.ImVec2(p0.x + pad_x + 5, y + 3),
        imgui.get_color_u32(color),
        3.0,
    )
    draw.add_text(
        imgui.ImVec2(p0.x + pad_x + 10, p0.y + pad_y),
        imgui.get_color_u32(imgui.ImVec4(0.93, 0.95, 0.98, 1.0)),
        label,
    )


STATE_COLORS: dict[str, imgui.ImVec4] = {
    AppState.IDLE: imgui.ImVec4(0.55, 0.60, 0.68, 1.0),
    AppState.RECORDING: imgui.ImVec4(1.0, 0.28, 0.28, 1.0),
    # Extensions register their own states by appending to this dict, e.g.:
    #     from myogestic.widgets.recording import STATE_COLORS
    #     STATE_COLORS["training"] = imgui.ImVec4(...)
    # (Populated by myogestic.ml.widgets on import.)
}
_DEFAULT_COLOR = imgui.ImVec4(0.5, 0.5, 0.5, 1.0)


def _safe_label_index(current: int, n_classes: int) -> int:
    """Clamp a stale class index to -1 if it's out of range for n_classes.

    Pure helper so the bounds-check logic can be tested without ImGui.
    """
    return current if 0 <= current < n_classes else -1


def recording_controls(
    ctx: Context,
    class_names: list[str] | None = None,
    *,
    on_record: Callable[[], None],
    on_stop: Callable[[], None],
    on_gesture: Callable[[int], None] | None = None,
) -> None:
    """Record/Stop + per-class label buttons + state pill.

    The widget reads `ctx` and drives recording via the explicit callbacks —
    it does not import App. Pass `app.start_recording` / `app.stop_recording`
    if you're using the standard App.

    Clicking a class button while recording snaps a label event at that moment
    (the active class is shown in the "Recording into: …" header). Outside of
    recording it just sets the *next* class to be used when Record is clicked.

    Parameters
    ----------
    ctx
        myogestic Context. Mutated: `current_label` is clamped to a
        valid index for `class_names`, and `class_names` itself is
        mirrored into `ctx.class_names` so `App.stop_recording` can
        persist them in the session metadata.
    class_names
        Per-class label-button names.
    on_record
        Called when Record is clicked (idle → recording).
    on_stop
        Called when Stop is clicked (recording → idle).
    on_gesture
        Optional `(class_index) -> None` for side effects on
        label-button click (e.g. switching a fake-signal generator).
    """
    n_classes = len(class_names) if class_names else 0
    # Defensive: clamp stale current_label to a safe range. Users can swap
    # CLASSES between runs — a leftover index could silently corrupt labels.
    if class_names:
        ctx.current_label = _safe_label_index(ctx.current_label, n_classes)
        # Mirror class_names into ctx so save_meta() can persist them in the
        # session's meta.json without the App needing to know about CLASSES.
        ctx.class_names = list(class_names)

    panel_header("RECORDING", fa.ICON_FA_CIRCLE_DOT)

    # Above the buttons: hint of what they do
    if class_names:
        imgui.text("Gesture:")

    # Per-class label buttons — selects current class; while recording also snaps
    # try/finally so an exception raised by on_record / on_stop /
    # on_gesture (or by their downstream effects, e.g. zarr init in a
    # threadless runtime) doesn't leave the ImGui style stack unbalanced,
    # which would then trip an IM_ASSERT on the next end_child further
    # up the call chain.
    imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(12, 8))
    try:
        if class_names:
            for i, name in enumerate(class_names):
                if i > 0:
                    imgui.same_line()
                selected = ctx.current_label == i
                if selected:
                    imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.31, 0.61, 0.98, 0.9))
                try:
                    if imgui.button(f"{name}##rec_gesture{i}", imgui.ImVec2(_LABEL_BTN_W, _LABEL_BTN_H)):
                        ctx.current_label = i
                        if on_gesture is not None:
                            on_gesture(i)
                        if (
                            ctx.state == AppState.RECORDING
                            and ctx.session is not None
                            and 0 <= i < n_classes
                        ):
                            ctx.session.add_label(i)
                finally:
                    if selected:
                        imgui.pop_style_color()
            imgui.spacing()

        # Record / Stop
        if ctx.state == AppState.IDLE:
            if imgui.button(f"{fa.ICON_FA_CIRCLE}  Record##rec_btn", imgui.ImVec2(_RECORD_BTN_W, 0)):
                on_record()
                # Auto-add the current label at the start of the recording, but
                # only if it's a valid index for the current class_names.
                if (
                    ctx.session is not None
                    and class_names
                    and 0 <= ctx.current_label < n_classes
                ):
                    ctx.session.add_label(ctx.current_label)
        elif ctx.state == AppState.RECORDING and imgui.button(
            f"{fa.ICON_FA_STOP}  Stop##rec_btn", imgui.ImVec2(_RECORD_BTN_W, 0)
        ):
            on_stop()
    finally:
        imgui.pop_style_var()

    # Status line — single state pill + status message + (when recording) the
    # snap affordance hint so the user knows clicking a class label snaps it.
    imgui.spacing()
    color = STATE_COLORS.get(ctx.state, _DEFAULT_COLOR)
    _status_pill(ctx.state.upper(), color)
    imgui.same_line()
    message = ctx.status_message or "Ready"
    if message.startswith("Saved"):
        message = f"{fa.ICON_FA_FLOPPY_DISK}  {message}"
    if ctx.state == AppState.RECORDING:
        n_labels = len(ctx.session.label_track) if ctx.session else 0
        active_name = (
            class_names[ctx.current_label]
            if class_names and 0 <= ctx.current_label < n_classes
            else "—"
        )
        message = f"{n_labels} labels · into: {active_name} (click a class to snap)"
    # Vertically center message with the pill (the pill is taller than a text
    # line by 2*_PILL_PAD_Y, so nudge text down by the pad to share a baseline).
    # Don't restore the cursor afterwards — moving cursor without submitting an
    # item next breaks imgui's window-growth assertion in end_child.
    imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + _PILL_PAD_Y)
    imgui.text(message)
