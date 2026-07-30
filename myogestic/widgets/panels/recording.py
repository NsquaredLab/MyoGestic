"""Recording controls widget.

    from myogestic.widgets import RecordingControls

    recording = RecordingControls(
        CLASSES,
        on_record=app.start_recording,
        on_stop=app.stop_recording,
        on_gesture=lambda i: ctrl_outlet.push_sample(...),
    )

    @app.ui
    def my_ui(ctx):
        recording.ui(ctx)

Record/Stop + label buttons + state pill. Training/prediction controls live
in `myogestic.ml.widgets` (they require `Pipeline(app)`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.core import AppState
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    ON_PILL_TEXT,
    PILL_BG,
    panel_header,
    pop_selected,
    push_selected,
)

if TYPE_CHECKING:
    from myogestic.core import Context


# Layout — local constants so users can read but not override.
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
    draw.add_rect_filled(
        p0, p1, imgui.get_color_u32(PILL_BG), size.y * 0.5
    )
    y = (p0.y + p1.y) * 0.5
    draw.add_rect_filled(
        imgui.ImVec2(p0.x + pad_x - 1, y - 3),
        imgui.ImVec2(p0.x + pad_x + 5, y + 3),
        imgui.get_color_u32(color),
        3.0,
    )
    draw.add_text(
        imgui.ImVec2(p0.x + pad_x + 10, p0.y + pad_y),
        imgui.get_color_u32(ON_PILL_TEXT),
        label,
    )


STATE_COLORS: dict[str, imgui.ImVec4] = {
    AppState.IDLE: IDLE,
    AppState.RECORDING: DANGER,
    # Extensions register their own states by appending to this dict, e.g.:
    #     from myogestic.widgets.panels.recording import STATE_COLORS
    #     STATE_COLORS["training"] = imgui.ImVec4(...)
    # (Populated by myogestic.ml.widgets on import.)
}
_DEFAULT_COLOR = IDLE


def _safe_label_index(current: int, n_classes: int) -> int:
    """Clamp a stale class index to -1 if it's out of range for n_classes."""
    return current if 0 <= current < n_classes else -1


class RecordingControls:
    """Record/Stop toggle + per-class label buttons + state pill.

    Construct once with the class names and callbacks, then call [`ui`][]
    with the live ``ctx`` each frame. Pass ``app.start_recording`` /
    ``app.stop_recording`` for ``on_record`` / ``on_stop`` if you're using
    the standard App.

    Examples
    --------
    >>> from myogestic.widgets import RecordingControls
    >>> controls = RecordingControls(
    ...     ["Rest", "Fist"],
    ...     on_record=app.start_recording,
    ...     on_stop=app.stop_recording,
    ... )
    >>> controls.ui(ctx)
    """

    def __init__(
        self,
        class_names: list[str] | None = None,
        *,
        on_record: Callable[[], None],
        on_stop: Callable[[], None],
        on_gesture: Callable[[int], None] | None = None,
    ) -> None:
        self._class_names = class_names
        self._on_record = on_record
        self._on_stop = on_stop
        self._on_gesture = on_gesture

    def ui(self, ctx: Context) -> None:
        """Render the recording controls. Call once per frame inside ``@app.ui``."""
        _render_recording_controls(
            ctx,
            self._class_names,
            on_record=self._on_record,
            on_stop=self._on_stop,
            on_gesture=self._on_gesture,
        )


def _render_recording_controls(
    ctx: Context,
    class_names: list[str] | None = None,
    *,
    on_record: Callable[[], None],
    on_stop: Callable[[], None],
    on_gesture: Callable[[int], None] | None = None,
) -> None:
    """Record/Stop + per-class label buttons + state pill.

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
    # CLASSES can be swapped between runs; a leftover index would corrupt labels.
    if class_names:
        ctx.current_label = _safe_label_index(ctx.current_label, n_classes)
        # Mirror into ctx so save_meta() can persist them in the session's
        # meta.json without the App knowing about CLASSES.
        ctx.class_names = list(class_names)

    panel_header("RECORDING", fa.ICON_FA_CIRCLE_DOT)

    if class_names:
        imgui.text("Gesture:")

    # try/finally: an exception from on_record / on_stop / on_gesture must not
    # leave the ImGui style stack unbalanced — that trips an IM_ASSERT on the
    # next end_child further up the call chain.
    imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(12, 8))
    try:
        if class_names:
            # Wrap the label buttons onto the next row instead of letting a
            # wide class list run them off the right edge.
            # (get_window_content_region_max isn't in this binding, so derive
            # the row's right edge from the cursor + available width.)
            spacing = imgui.get_style().item_spacing.x
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            for i, name in enumerate(class_names):
                if i > 0 and imgui.get_item_rect_max().x + spacing + _LABEL_BTN_W <= right:
                    imgui.same_line()
                selected = ctx.current_label == i
                if selected:
                    push_selected()
                try:
                    if imgui.button(
                        f"{name}##rec_gesture{i}", imgui.ImVec2(_LABEL_BTN_W, _LABEL_BTN_H)
                    ):
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
                        pop_selected()
            imgui.spacing()

        # Record / Stop
        if ctx.state == AppState.IDLE:
            if imgui.button(
                f"{fa.ICON_FA_CIRCLE}  Record##rec_btn", imgui.ImVec2(_RECORD_BTN_W, 0)
            ):
                on_record()
                # Auto-add the current label at the start of the recording.
                if ctx.session is not None and class_names and 0 <= ctx.current_label < n_classes:
                    ctx.session.add_label(ctx.current_label)
        elif ctx.state == AppState.RECORDING and imgui.button(
            f"{fa.ICON_FA_STOP}  Stop##rec_btn", imgui.ImVec2(_RECORD_BTN_W, 0)
        ):
            on_stop()
    finally:
        imgui.pop_style_var()

    # Status line — state pill + status message + (when recording) the snap hint.
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
    # Nudge the text down by the pad to share a baseline with the taller pill.
    # Don't restore the cursor afterwards — moving the cursor without submitting
    # an item next breaks imgui's window-growth assertion in end_child.
    imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + _PILL_PAD_Y)
    imgui.text(message)
