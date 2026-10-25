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

Record/Stop, optional timed takes, and label buttons. Training/prediction controls live
in `myogestic.ml.widgets` (they require `Pipeline(app)`).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic._theme import mono_font
from myogestic.core import AppState
from myogestic.session._core import _SLUG_MAX, _slug
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    ON_PRIMARY_TEXT,
    _truncate_to_width,
    destructive_button,
    mono_text,
    muted,
    panel_header,
    primary_button,
    tinted_row,
    ui_px,
)

if TYPE_CHECKING:
    from myogestic.core import Context


# Shared with the ML extension's state cues.
STATE_COLORS: dict[str, imgui.ImVec4] = {
    AppState.IDLE: IDLE,
    AppState.RECORDING: DANGER,
    # Extensions register their own states by appending to this dict, e.g.:
    #     from myogestic.widgets.panels.recording import STATE_COLORS
    #     STATE_COLORS["training"] = imgui.ImVec4(...)
    # (Populated by myogestic.ml.widgets on import.)
}


@dataclass(frozen=True)
class TakeStatus:
    """An immutable snapshot of the recording controls' current take.

    Durations are monotonic seconds, measured from capture rather than warm-up.
    ``saved_text`` describes the captured duration, including an early stop.
    """

    phase: Literal["idle", "warmup", "recording", "saved"] = "idle"
    timed: bool = False
    gesture: str | None = None
    elapsed_s: float = 0.0
    length_s: float | None = None
    warmup_left_s: float = 0.0
    saved_text: str = ""


class _TakeMachine:
    """Own one take; observe external state before servicing its deadline."""

    def __init__(
        self, on_record: Callable[[], None], on_stop: Callable[[], None],
        *, clock: Callable[[], float] | None = None,
    ) -> None:
        self._on_record = on_record
        self._on_stop = on_stop
        self._clock = clock or time.monotonic
        self.status = TakeStatus()
        self._started = 0.0
        self._deadline = 0.0

    def start(
        self, gesture: str | None, *, length_s: float | None = None,
        warmup_s: float = 0.0, now: float | None = None,
    ) -> None:
        if self.status.phase in ("warmup", "recording"):
            return
        instant = self._clock() if now is None else now
        warmup_s = warmup_s if length_s is not None else 0.0
        self.status = TakeStatus(
            phase="warmup", timed=length_s is not None, gesture=gesture,
            length_s=length_s, warmup_left_s=warmup_s,
        )
        self._deadline = instant + warmup_s
        if not warmup_s:
            self._begin(now)

    def _begin(self, now: float | None) -> None:
        self.status = replace(self.status, phase="recording", warmup_left_s=0.0)
        try:
            self._on_record()
        except Exception:
            self.status = TakeStatus()
            raise
        # Store allocation belongs to setup, not the requested capture length.
        # An explicit ``now`` is the deterministic timestamp supplied by a test.
        self._started = self._clock() if now is None else now

    def advance(
        self, *, recording: bool, valid: bool = True, now: float | None = None,
    ) -> None:
        instant = self._clock() if now is None else now
        phase = self.status.phase
        if not valid:
            self.status = TakeStatus()
            if phase == "recording" and recording:
                self._on_stop()
        elif phase == "warmup":
            if recording:
                self.status = TakeStatus()
            elif instant >= self._deadline:
                self._begin(now)
            else:
                self.status = replace(self.status, warmup_left_s=self._deadline - instant)
        elif phase == "recording":
            if not recording:
                self.status = TakeStatus()
                return
            self.status = replace(self.status, elapsed_s=max(0.0, instant - self._started))
            if self.status.length_s is not None and instant >= self._started + self.status.length_s:
                self.stop(now=instant)
        elif phase == "saved" and (recording or instant >= self._deadline):
            self.status = TakeStatus()

    def stop(self, *, now: float | None = None) -> None:
        if self.status.phase == "warmup":
            self.status = TakeStatus()
        elif self.status.phase == "recording":
            now = self._clock() if now is None else now
            elapsed = max(0.0, now - self._started)
            early = self.status.length_s is not None and elapsed < self.status.length_s
            gesture = f" · {self.status.gesture}" if self.status.gesture else ""
            self.status = replace(
                self.status, phase="saved", elapsed_s=elapsed,
                saved_text=f"Saved{gesture} · {elapsed:.1f} s" + (" (stopped early)" if early else ""),
            )
            self._deadline = now + 2.0
            self._on_stop()


def _safe_label_index(current: int, n_classes: int) -> int:
    """Clamp a stale class index to -1 if it's out of range for n_classes."""
    return current if 0 <= current < n_classes else -1


_POPUP_ID = "Save recording##rec_save"
_NAME_MAX = 64


def _elapsed_str(seconds: float, *, tenths: bool = False) -> str:
    """``m:ss`` for a duration, with optional tenths for a live take."""
    if tenths:
        ticks = max(0, int(round(seconds * 10)))
        minutes, ticks = divmod(ticks, 600)
        return f"{minutes}:{ticks // 10:02d}.{ticks % 10}"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def _record_button(ctx: Context, label: str, size: imgui.ImVec2) -> bool:
    """Render Record with a reason when the participant gate disables it."""
    if not getattr(ctx, "require_participant", False) or getattr(ctx, "participant", ""):
        return imgui.button(label, size)
    imgui.begin_disabled()
    imgui.button(label, size)
    imgui.end_disabled()
    if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
        imgui.set_tooltip("Set a participant ID before recording.")
    return False


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

    Idle shows a full-width red Record action. Capture shows a tinted Recording
    row with a mono elapsed clock and Stop; naming shows the captured duration.
    The dialog previews the file stem, with an optional name, Save and an
    outlined Discard action. A required participant ID gates Record with a
    visible explanation.

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

        A status dot in the header accompanies the capture or naming row. The
        archive icon distinguishes the title from the recording state dot.

        Drawn inside an ImGui id scope named by ``widget_id``, so two recorders
        in one `Grid` cell do not share a button and a naming dialog.
        """
        imgui.push_id(self._widget_id)
        try:
            recording = ctx.state == AppState.RECORDING
            self._sync(recording)
            tone, _ = self._state(recording)

            if self._show_header:
                panel_header("RECORDING", fa.ICON_FA_BOX_ARCHIVE, status=tone)

            self._button(ctx, recording)
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
        self._captured = time.monotonic() - self._started if self._started is not None else 0.0
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
            return IDLE, f"naming · {_elapsed_str(self._captured, tenths=True)} captured"
        if recording:
            elapsed = time.monotonic() - self._started if self._started is not None else 0.0
            return DANGER, f"{_elapsed_str(elapsed, tenths=True)} elapsed"
        return IDLE, "not recording"

    # --- rendering ----------------------------------------------------------
    def _button(self, ctx: Context, recording: bool) -> None:
        """One forward action when idle; a state row while capturing or naming."""
        _, detail = self._state(recording)
        if self._naming:
            with tinted_row() as width:
                imgui.align_text_to_frame_padding()
                self._mono_detail(detail, width)
            return

        height = max(ui_px(52), 2 * imgui.get_text_line_height() + ui_px(12))
        if recording:
            with tinted_row(DANGER, height=height) as width:
                left, top = imgui.get_cursor_pos()
                stop_w = imgui.calc_text_size("Stop").x + 2 * imgui.get_style().frame_padding.x
                text_w = max(0.0, width - stop_w - ui_px(8))
                imgui.text_unformatted(_truncate_to_width("Recording", text_w))
                imgui.set_cursor_pos_y(top + imgui.get_text_line_height() + ui_px(2))
                self._mono_detail(detail, text_w)
                imgui.same_line()
                imgui.set_cursor_pos(imgui.ImVec2(
                    left + width - stop_w,
                    top + (height - ui_px(8) - imgui.get_frame_height()) / 2,
                ))
                if imgui.button("Stop"):
                    self._stop(ctx)
            return

        for slot, color in ((imgui.Col_.button, DANGER), (imgui.Col_.button_hovered, DANGER),
                            (imgui.Col_.button_active, DANGER), (imgui.Col_.text, ON_PRIMARY_TEXT)):
            imgui.push_style_color(slot, color)
        try:
            if _record_button(ctx, f"{fa.ICON_FA_CIRCLE}  Record", imgui.ImVec2(-1, height)):
                self._name = ""
                self._started = time.monotonic()
                self._on_record()
        finally:
            imgui.pop_style_color(4)
        if getattr(ctx, "require_participant", False) and not getattr(ctx, "participant", ""):
            imgui.push_style_color(imgui.Col_.text, muted())
            imgui.text_wrapped("Set a participant first — recordings are saved under their ID.")
            imgui.pop_style_color()

    @staticmethod
    def _mono_detail(text: str, width: float) -> None:
        """Keep a readout on one line, with its full value available on hover."""
        font = mono_font()
        if font is not None:
            imgui.push_font(font, imgui.get_style().font_size_base)
        try:
            shown = text
            if imgui.calc_text_size(text).x > width:
                ellipsis = "…" if imgui.calc_text_size("…").x <= width else ""
                shown = _truncate_to_width(text, width - imgui.calc_text_size(ellipsis).x) + ellipsis
            mono_text(shown, muted())
        finally:
            if font is not None:
                imgui.pop_font()
        imgui.set_item_tooltip(text)

    def _file_stem(self, ctx: Context) -> str:
        """Preview the archive stem without writing metadata or changing the session."""
        session = ctx.session
        if session is None:
            return ""
        # Match save_meta's recorded-time labels; metadata is only written at Save.
        first, last = 0.0, 0.0
        for timestamps in session.ts_stores.values():
            if timestamps.shape[0]:
                first, last = float(timestamps[0]), float(timestamps[-1])
                break
        recorded = set()
        for i, event in enumerate(session.label_track):
            if not 0 <= event.class_index < len(ctx.class_names):
                continue
            index = int(event.class_index)
            if index != event.class_index:
                continue
            end = session.label_track[i + 1].timestamp if i + 1 < len(session.label_track) else last
            if min(last, end) > max(first, event.timestamp):
                recorded.add(ctx.class_names[index])
        slugs = [_slug(name) for name in sorted(recorded, key=ctx.class_names.index) if _slug(name)]
        labels = "+".join(slugs)
        if len(labels) > _SLUG_MAX:
            labels = f"{len(slugs)}-classes"
        return "_".join(part for part in (session.path.name, labels, _slug(self._name)) if part)

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
        width = min(ui_px(360), imgui.get_main_viewport().work_size.x - ui_px(24))
        imgui.set_next_window_size(imgui.ImVec2(width, 0))
        opened, _ = imgui.begin_popup_modal(_POPUP_ID, None, imgui.WindowFlags_.always_auto_resize)
        if not opened:
            return
        try:
            imgui.text_unformatted("Name (optional)")
            imgui.set_next_item_width(-1)
            if imgui.is_window_appearing():
                imgui.set_keyboard_focus_here()
            changed, typed = imgui.input_text_with_hint(
                "##rec_name", "e.g. subject-03 fist", self._name
            )
            if changed:
                self._name = typed[:_NAME_MAX]
            imgui.text_colored(muted(), "File stem")
            self._mono_detail(self._file_stem(ctx), imgui.get_content_region_avail().x)
            imgui.spacing()

            if primary_button(f"{fa.ICON_FA_FLOPPY_DISK}  Save", (-1, 0)):
                self._save(ctx)
                imgui.close_current_popup()
            if self._on_discard is not None:
                duration = _elapsed_str(self._captured, tenths=True)
                imgui.push_style_var(imgui.StyleVar_.frame_border_size, ui_px(1))
                try:
                    discarded = destructive_button(
                        f"{fa.ICON_FA_TRASH}  Discard {duration}",
                        tooltip=f"Delete these {duration} of data permanently",
                    )
                finally:
                    imgui.pop_style_var()
                if discarded:
                    self._discard()
                    imgui.close_current_popup()
        finally:
            imgui.end_popup()



class RecordingControls:
    """Record labelled takes, with an optional warm-up and fixed duration.

    Construct once, then call ``ui(ctx)`` every frame. ``take`` is an immutable
    snapshot for an app's countdown or signal overlay. For unlabelled capture
    with a naming dialog, use `RecordButton`.

    Parameters
    ----------
    class_names
        Gesture tiles. Idle clicks choose the next take's label; start/stop
        mode also permits label changes during capture. Timed takes lock it.
        Names are copied to ``ctx.class_names`` for session metadata.
    on_record
        Begin capture, normally ``app.start_recording``.
    on_stop
        Stop and save capture, normally ``app.stop_recording``.
    on_gesture
        Optional side effect when a gesture tile is selected.
    show_header
        Render the standard panel header.
    take_lengths
        Positive durations in seconds. Empty keeps start/stop only.
    warmups
        Nonnegative countdown durations in seconds; zero means Off.
        Must contain at least one value.
    timed : bool, optional
        Open in Timed mode instead of Start / stop. Defaults to ``False``.
        ``True`` requires nonempty ``take_lengths`` or raises ``ValueError``.
    take_length : float or None, optional
        Initially selected entry of ``take_lengths``. ``None`` selects the
        first entry when offered. A value outside the sequence raises
        ``ValueError`` naming the allowed values.
    warmup : float or None, optional
        Initially selected entry of ``warmups``. ``None`` selects the first
        entry. A value outside the sequence raises ``ValueError`` naming the
        allowed values.
    """

    def __init__(
        self,
        class_names: list[str] | None = None,
        *,
        on_record: Callable[[], None],
        on_stop: Callable[[], None],
        on_gesture: Callable[[int], None] | None = None,
        show_header: bool = True,
        take_lengths: Sequence[float] = (),
        warmups: Sequence[float] = (0.0,),
        timed: bool = False,
        take_length: float | None = None,
        warmup: float | None = None,
    ) -> None:
        self._class_names = class_names
        self._on_record = on_record
        self._on_stop = on_stop
        self._on_gesture = on_gesture
        self._show_header = show_header
        self._take_lengths = tuple(take_lengths)
        self._warmups = tuple(warmups)
        if any(not math.isfinite(n) or n <= 0 for n in self._take_lengths):
            raise ValueError("Give take_lengths finite, positive durations in seconds.")
        if not self._warmups or any(not math.isfinite(n) or n < 0 for n in self._warmups):
            raise ValueError("Give warmups finite, nonnegative durations; use (0.0,) for Off.")
        if timed and not self._take_lengths:
            raise ValueError("Give take_lengths at least one duration when timed=True.")
        if take_length is not None and take_length not in self._take_lengths:
            raise ValueError(f"Choose take_length from take_lengths: {self._take_lengths}.")
        if warmup is not None and warmup not in self._warmups:
            raise ValueError(f"Choose warmup from warmups: {self._warmups}.")
        self._length_index = self._take_lengths.index(take_length) if take_length is not None else 0
        self._warmup_index = self._warmups.index(warmup) if warmup is not None else 0
        self._timed = timed
        self._ctx: Context | None = None
        self._session = None
        self._participant = ""
        self._label = -1
        self._streams: tuple = ()
        self._stop_revision = 0
        self._machine = _TakeMachine(self._begin_recording, self._on_stop)

    @property
    def take(self) -> TakeStatus:
        """Read the take as of the most recent ``ui`` call, without side effects."""
        return self._machine.status

    def ui(self, ctx: Context, *, visible: bool = True) -> None:
        """Advance once per frame, and optionally render the controls.

        Call with ``visible=False`` while another workflow step is open so a
        timed take still stops on its first frame at or after the deadline.
        """
        self._sync(ctx)
        if visible:
            from ._recording_controls import _render_recording_controls

            imgui.push_id(str(id(self)))
            try:
                _render_recording_controls(ctx, self)
            finally:
                imgui.pop_id()

    def _gesture(self, ctx: Context) -> str | None:
        names = self._class_names or []
        return names[ctx.current_label] if 0 <= ctx.current_label < len(names) else None

    def _remember(self, ctx: Context) -> None:
        self._ctx = ctx
        self._session = ctx.session
        self._participant = ctx.participant
        self._label = ctx.current_label
        self._streams = tuple(
            (name, stream, stream.info) for name, stream in ctx.streams.items()
            if stream.info is not None
        )
        self._stop_revision = ctx._recording_stop_revision

    def _start(self, ctx: Context) -> None:
        if ctx.state != AppState.IDLE or (ctx.require_participant and not ctx.participant):
            return
        if self._class_names:
            ctx.current_label = _safe_label_index(ctx.current_label, len(self._class_names))
            ctx.class_names = list(self._class_names)
            if self._timed and self._gesture(ctx) is None:
                return
        self._remember(ctx)
        self._machine.start(
            self._gesture(ctx),
            length_s=self._take_lengths[self._length_index] if self._timed else None,
            warmup_s=self._warmups[self._warmup_index] if self._timed else 0.0,
        )

    def _begin_recording(self) -> None:
        ctx = self._ctx
        self._on_record()
        self._session = ctx.session
        if ctx.state != AppState.RECORDING:
            self._machine.advance(recording=False)
            return
        if ctx.session is not None and self._gesture(ctx) is not None:
            ctx.session.add_label(ctx.current_label)

    def _sync(self, ctx: Context) -> None:
        if self._class_names:
            ctx.current_label = _safe_label_index(ctx.current_label, len(self._class_names))
            ctx.class_names = list(self._class_names)
        phase = self.take.phase
        if phase == "idle" and ctx.state == AppState.RECORDING:
            # An external capture still needs a Stop control and an elapsed read.
            self._remember(ctx)
            self._machine._started = self._machine._clock()
            self._machine.status = TakeStatus(phase="recording", gesture=self._gesture(ctx))
            return
        owned = ctx.state == AppState.RECORDING and ctx.session is self._session
        valid = self._ctx is ctx and ctx.participant == self._participant
        if phase in ("warmup", "recording"):
            if self.take.timed:
                valid = valid and ctx.current_label == self._label and self._gesture(ctx) == self.take.gesture
            valid = valid and all(
                ctx.streams.get(name) is stream and stream.info is info and stream.status == "connected"
                for name, stream, info in self._streams
            )
            if phase == "warmup":
                valid = valid and ctx.state == AppState.IDLE and ctx.session is self._session
                valid = valid and ctx._recording_stop_revision == self._stop_revision
        self._machine.advance(recording=owned, valid=valid)
        if self.take.phase == "recording" and not self.take.timed:
            self._machine.status = replace(self.take, gesture=self._gesture(ctx))
