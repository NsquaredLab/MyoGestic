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

import time
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
    destructive_button,
    mono_text,
    muted,
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


_POPUP_ID = "Save recording##rec_save"
_NAME_MAX = 64


def _elapsed_str(seconds: float) -> str:
    """``m:ss`` for a duration, the way a stopwatch reads."""
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


class RecordButton:
    """One button that records, and asks what to call the take when it stops.

    The plain-recording counterpart to `RecordingControls`: no per-class label
    buttons, no gesture protocol — press Record, press Stop, name what you just
    captured. For an app whose job is *collect some data*, rather than one
    building a labelled training set.

    Capture ends the instant Stop is pressed — the streams are detached before
    the dialog opens — so the seconds spent typing a name are never recorded.
    The name is written to the session's ``meta.json`` and into the archive
    filename, so it shows up in `SessionManager` and is findable on disk.

    Parameters
    ----------
    on_record
        Called when Record is clicked (idle → recording). Pass
        ``app.start_recording``.
    on_stop
        Called when the dialog is saved. Pass ``app.stop_recording``.
    on_discard
        Called when the dialog is discarded. Pass ``app.discard_recording``.
        Omit it and the dialog offers no Discard — appropriate for an app where
        deleting a take should not be one click away.
    widget_id
        ImGui id scope and state key. Defaults to ``"recorder"``. Give each
        instance its own when an app renders more than one: ImGui derives a
        control's identity from its label plus the enclosing scope, and a
        `Grid` cell is a single child window — so two of these in one cell
        share every slider, popup and plot until they are told apart.
    show_header
        Render the standard ``panel_header``.

    Examples
    --------
    >>> from myogestic.widgets import RecordButton
    >>> recorder = RecordButton(
    ...     on_record=app.start_recording,
    ...     on_stop=app.stop_recording,
    ...     on_discard=app.discard_recording,
    ... )
    >>> recorder.ui(ctx)
    """

    def __init__(
        self,
        *,
        on_record: Callable[[], None],
        on_stop: Callable[[], None],
        on_discard: Callable[[], None] | None = None,
        show_header: bool = True,
        widget_id: str | None = None,
    ) -> None:
        self._on_record = on_record
        self._widget_id = widget_id or "recorder"
        self._on_stop = on_stop
        self._on_discard = on_discard
        self._show_header = show_header
        self._name = ""
        self._naming = False
        self._started: float | None = None
        self._captured = 0.0

    def ui(self, ctx: Context) -> None:
        """Render the recorder. Call once per frame inside ``@app.ui``.

        Deliberately the same shape as `DevicePicker`: status dot in the header,
        one full-width action, one muted detail line. Stacked in the same column
        the two panels should read as one instrument, not two widgets that grew
        up apart. The header icon is an archive rather than the usual record
        circle — beside a status dot, a second circle reads as a second state.

        Drawn inside an ImGui id scope named by ``widget_id``, so two recorders
        in one `Grid` cell do not share a button and a naming dialog.
        """
        imgui.push_id(self._widget_id)
        try:
            recording = ctx.state == AppState.RECORDING
            self._sync(recording)
            tone, detail = self._state(recording)

            if self._show_header:
                # No tooltip: the line below the button already says this, and the
                # elapsed clock in it would need keeping in step in two places.
                panel_header("RECORDING", fa.ICON_FA_BOX_ARCHIVE, status=tone)

            self._button(ctx, recording)
            # Mono: the clock ticks while you watch it, and the UI face's digits are
            # not tabular, so a proportional one shuffles the text as it counts.
            mono_text(detail, muted())
            self._dialog(ctx)
        finally:
            imgui.pop_id()

    # --- logic (no ImGui: everything here is unit-testable) -----------------

    def _sync(self, recording: bool) -> None:
        """Drop a stale dialog.

        Somebody else — a protocol script, a headless driver — can call
        ``stop_recording`` while the dialog is open, leaving nothing to name.
        """
        if self._naming and not recording:
            self._reset()

    def _stop(self, ctx: Context) -> None:
        """End capture *now*, and switch to naming.

        Detaching here rather than in the dialog's Save is the whole point: the
        operator's reaction time and however long they spend typing would
        otherwise be appended to the recording. `App.stop_recording` detaches
        again when it finally runs, which is harmless — ``detach_session`` takes
        the stream lock and simply clears an already-cleared session.
        """
        for stream in ctx.streams.values():
            stream.detach_session()
        self._captured = time.monotonic() - self._started if self._started else 0.0
        self._started = None
        self._naming = True

    def _save(self, ctx: Context) -> None:
        """Attach the typed name to the session, then let the App finalise it."""
        if ctx.session is not None:
            # Read back by `Session.save_meta`, which `stop_recording` calls
            # before packing — so this has to land before, not after.
            ctx.session.name = self._name.strip()
        self._on_stop()
        self._reset()

    def _discard(self) -> None:
        """Throw the take away. Only offered when the app provided a handler."""
        if self._on_discard is not None:
            self._on_discard()
        self._reset()

    def _reset(self) -> None:
        self._naming = False
        self._name = ""
        self._started = None

    def _state(self, recording: bool) -> tuple[imgui.ImVec4, str]:
        """State tone and its one-line detail, matching `DevicePicker`'s status line."""
        if self._naming:
            return IDLE, f"naming · {_elapsed_str(self._captured)}"
        if recording:
            elapsed = time.monotonic() - self._started if self._started else 0.0
            return DANGER, f"recording · {_elapsed_str(elapsed)}"
        return IDLE, "not recording"

    # --- rendering ----------------------------------------------------------
    def _button(self, ctx: Context, recording: bool) -> None:
        """Record ↔ Stop, full width. The glyph shows what clicking will do."""
        full = imgui.ImVec2(-1, 0)
        if self._naming:
            imgui.begin_disabled()
            imgui.button(f"{fa.ICON_FA_STOP}  Stop", full)
            imgui.end_disabled()
            return

        if recording:
            if imgui.button(f"{fa.ICON_FA_STOP}  Stop", full):
                self._stop(ctx)
        elif imgui.button(f"{fa.ICON_FA_CIRCLE_DOT}  Record", full):
            self._name = ""
            self._started = time.monotonic()
            self._on_record()

    def _dialog(self, ctx: Context) -> None:
        """The naming modal. Deliberately has no way out but Save or Discard.

        Re-opened every frame while naming because ImGui closes popups on Esc:
        dismissing it would strand a finalised-but-unpacked session with no
        control left to resolve it.
        """
        if self._naming and not imgui.is_popup_open(_POPUP_ID):
            imgui.open_popup(_POPUP_ID)

        # Centre on the viewport, not on whatever panel happens to host the
        # widget — the dialog is app-modal, so it should not look anchored to a
        # cell in the grid.
        center = imgui.get_main_viewport().get_center()
        imgui.set_next_window_pos(center, imgui.Cond_.appearing, imgui.ImVec2(0.5, 0.5))
        opened, _ = imgui.begin_popup_modal(_POPUP_ID, None, imgui.WindowFlags_.always_auto_resize)
        if not opened:
            return
        try:
            imgui.text(f"Captured {_elapsed_str(self._captured)}.")
            imgui.set_next_item_width(280)
            if imgui.is_window_appearing():
                imgui.set_keyboard_focus_here()
            changed, typed = imgui.input_text_with_hint(
                "##rec_name", "e.g. subject-03 fist", self._name
            )
            if changed:
                self._name = typed[:_NAME_MAX]
            imgui.text_colored(
                muted(), "Optional — the timestamp always identifies the session."
            )
            imgui.spacing()

            if imgui.button(f"{fa.ICON_FA_FLOPPY_DISK}  Save", imgui.ImVec2(120, 0)):
                self._save(ctx)
                imgui.close_current_popup()
            if self._on_discard is not None:
                imgui.same_line()
                if destructive_button(
                    f"{fa.ICON_FA_TRASH}  Discard",
                    tooltip=f"Delete these {_elapsed_str(self._captured)} of data permanently",
                ):
                    self._discard()
                    imgui.close_current_popup()
        finally:
            imgui.end_popup()



class RecordingControls:
    """Record/Stop toggle + per-class label buttons + state pill.

    Construct once with the class names and callbacks, then call [`ui`][]
    with the live ``ctx`` each frame. Pass ``app.start_recording`` /
    ``app.stop_recording`` for ``on_record`` / ``on_stop`` if you're using
    the standard App. For plain capture with no gesture protocol, use
    `RecordButton` instead.

    Parameters
    ----------
    class_names
        One label button per name. Clicking one while recording snaps a label
        event at that moment; outside a recording it sets the class the next
        Record will start in. ``None`` renders the transport alone. The names
        are mirrored into ``ctx.class_names`` so `App.stop_recording` persists
        them in the session's ``meta.json`` — old recordings stay
        self-describing.
    on_record
        Called when Record is clicked (idle → recording).
    on_stop
        Called when Stop is clicked (recording → idle).
    on_gesture
        Optional ``(class_index) -> None`` for side effects on a label-button
        click — cueing a subject, switching a fake-signal generator.

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
