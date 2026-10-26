"""Participant selection with names kept only in memory and a local key file."""

from __future__ import annotations

import csv
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic._theme import mono_font
from myogestic.core import Context
from myogestic.session import labelled_path
from myogestic.session._core import _slug
from myogestic.widgets.common import (
    CONSOLE_BG,
    CONSOLE_TEXT,
    DANGER,
    PALETTE,
    SUCCESS,
    WARNING,
    fit_text,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    primary,
    primary_button,
    push_selected,
    segmented,
    tinted_row,
    ui_px,
)
from myogestic.widgets.training._session_state import row_gestures, scan_sessions

__all__ = ["ParticipantPanel"]

_COLUMNS = ("id", "first_name", "family_name", "created")


def _rows(key_file: Path) -> list[dict[str, str]]:
    """Read complete, safe rows; a missing or hand-edited key is not fatal."""
    rows = []
    try:
        with key_file.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if reader.fieldnames != list(_COLUMNS):
                return rows
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    continue
                if not row["id"] or _slug(row["id"]) != row["id"]:
                    continue
                try:
                    date.fromisoformat(row["created"])
                except ValueError:
                    continue
                rows.append(row)
    except (OSError, UnicodeError, csv.Error):
        pass
    return rows


def _fold(name: str) -> str:
    """Compare names without surrounding whitespace, case or accents."""
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", name.strip().casefold())
        if not unicodedata.combining(char)
    )


def _lookup(key_file: Path, first: str, family: str) -> str | None:
    """Find the ID for a name without exposing names outside the key file."""
    target = (_fold(first), _fold(family))
    if not any(target):
        return None
    return next(
        (
            row["id"]
            for row in _rows(key_file)
            if (_fold(row["first_name"]), _fold(row["family_name"])) == target
        ),
        None,
    )


def _next_id(key_file: Path) -> str:
    """Offer the number after the largest P-NNN ID, or P-001 for an empty key."""
    numbers = [
        int(match[1]) for row in _rows(key_file) if (match := re.fullmatch(r"P-(\d+)", row["id"]))
    ]
    return f"P-{max(numbers, default=0) + 1:03d}"


def _append(key_file: Path, pid: str, first: str, family: str) -> None:
    """Append a dated CSV row, creating the key's parent and header as needed."""
    key_file.parent.mkdir(parents=True, exist_ok=True)
    with key_file.open("a+", encoding="utf-8", newline="") as stream:
        stream.seek(0)
        existing = stream.read()
        writer = csv.writer(stream)
        if not existing:
            writer.writerow(_COLUMNS)
        elif not existing.endswith(("\n", "\r")):
            stream.write("\n")
        writer.writerow((pid, first, family, date.today().isoformat()))


@dataclass
class _RecordedParticipant:
    """One ID and its cached local display information, never persisted."""

    pid: str
    name: str
    takes: int
    duration_s: float
    class_names: list[str]
    gestures: set[str]
    last: datetime
    model: Path | None
    model_time: datetime | None


def _recorded_participants(base: Path, key_file: Path) -> list[_RecordedParticipant]:
    """Read each take once using the same pending-save rules as Takes."""
    names = {
        row["id"]: " ".join(filter(None, (row["first_name"], row["family_name"])))
        for row in _rows(key_file)
    }
    participants = []
    try:
        folders = sorted(base.iterdir())
    except OSError:
        return participants
    for folder in folders:
        if not folder.is_dir() or not folder.name or _slug(folder.name) != folder.name:
            continue
        try:
            takes = scan_sessions(str(folder))
            if not takes:
                continue
            classes = list(dict.fromkeys(name for take in takes for name in take["class_names"]))
            gestures = {name for take in takes for _, name, _ in row_gestures(take, None)}
            last = max(take["created"] or datetime.fromtimestamp(Path(take["path"]).stat().st_mtime)
                       for take in takes)
            models = [(path.stat().st_mtime, path) for path in folder.glob("*_model.joblib")
                      if path.is_file()]
            saved, model = max(models, default=(None, None))
            participants.append(_RecordedParticipant(
                folder.name, names.get(folder.name, ""), len(takes),
                sum(take["duration_s"] for take in takes), classes, gestures, last,
                model, datetime.fromtimestamp(saved) if saved is not None else None,
            ))
        except OSError:
            # A take or folder can disappear while the dialog is opening.
            continue
    return sorted(participants, key=lambda row: (row.last, row.pid), reverse=True)


def _when(stamp: datetime) -> str:
    """Show local calendar days consistently for takes and saved models."""
    today = date.today()
    if stamp.date() == today:
        return stamp.strftime("Today %H:%M")
    if stamp.date() == today - timedelta(days=1):
        return stamp.strftime("Yesterday %H:%M")
    return stamp.strftime("%Y-%m-%d")


def _duration(seconds: float) -> str:
    """Format the sample-clock duration in minutes and seconds."""
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}:{seconds:02d}"


@dataclass
class _ParticipantState:
    """Private input and local display state, addressed by widget identity."""

    pid: str = ""
    first: str = ""
    family: str = ""
    active_pid: str | None = None
    local_name: str = ""
    error: str = ""
    open_requested: bool = False
    show_names: bool = False
    search: str = ""
    tab: int = 1
    recorded: list[_RecordedParticipant] = field(default_factory=list)
    selected: str = ""


_states: dict[str, _ParticipantState] = {}


class ParticipantPanel:
    """Choose a pseudonymised ID with an optional local name lookup.

    Parameters
    ----------
    key_file : str or Path, optional
        Local CSV mapping IDs to names, by default
        ``"~/myogestic/participant-key.csv"``. Keep it outside the sessions
        directory so copied recordings never carry the names with them.
    widget_id : str, optional
        Stable input-state and popup identity, by default ``"participant"``.
        Use a different ID for each independent participant selector.
    sessions_dir : str or Path, optional
        Recording root, by default ``"sessions"``. Recorded participants
        are discovered once each time the dialog opens, excluding pending saves.
    on_drive : callable or None, optional
        Called as ``on_drive(participant_id, model_path)`` after selecting
        the ID with **Drive with saved model**. The newest ``*_model.joblib``
        by modification time is offered. None hides that action.

    Notes
    -----
    Names stay in widget memory and the key file. Only the slugged ID is
    assigned to ``ctx.participant``. Selection is disabled while the app is
    recording, training or predicting; Start session selects the participant
    without starting a recording.
    """

    def __init__(
        self,
        *,
        key_file: str | Path = "~/myogestic/participant-key.csv",
        widget_id: str = "participant",
        sessions_dir: str | Path = "sessions",
        on_drive: Callable[[str, Path], None] | None = None,
    ) -> None:
        self._key_file = Path(key_file).expanduser()
        self._widget_id = widget_id
        self._sessions_dir = Path(sessions_dir).expanduser()
        self._on_drive = on_drive

    @property
    def _state(self) -> _ParticipantState:
        return _states.setdefault(self._widget_id, _ParticipantState())

    def open(self) -> None:
        """Request the participant modal on the next call to ``ui(ctx)``.

        The request is discarded if the context is not idle on that frame.
        It is safe to call this method outside an ImGui frame.
        """
        self._state.open_requested = True

    def _prepare(self) -> None:
        """Cache the list and reset private display state on every open."""
        state = self._state
        state.recorded = _recorded_participants(self._sessions_dir, self._key_file)
        next_key = int(_next_id(self._key_file)[2:])
        numbers = [int(match[1]) for row in state.recorded
                   if (match := re.fullmatch(r"P-(\d+)", row.pid))]
        state.pid = f"P-{max(next_key, max(numbers, default=0) + 1):03d}"
        state.first = state.family = state.error = state.search = ""
        state.show_names = False
        state.tab = 0 if state.recorded else 1
        state.selected = next((row.pid for row in state.recorded
                               if row.pid == state.active_pid),
                              state.recorded[0].pid if state.recorded else "")

    def _filtered(self) -> list[_RecordedParticipant]:
        """Search IDs, adding the local names only while they are revealed."""
        state = self._state
        query = _fold(state.search)
        return [row for row in state.recorded if query in _fold(row.pid)
                or (state.show_names and query in _fold(row.name))]

    def _close(self) -> None:
        """Hide names immediately, including the frame an action closes the dialog."""
        self._state.show_names = False
        self._state.search = ""
        imgui.close_current_popup()

    def _start(self, ctx: Context, pid: str, first: str, family: str) -> bool:
        """Commit only the ID to context, after any local name has been saved."""
        pid, first, family = _slug(pid), first.strip(), family.strip()
        if ctx.state != "idle" or not pid:
            return False
        state = self._state
        try:
            if first or family:
                existing_id = _lookup(self._key_file, first, family)
                if existing_id is not None and existing_id != pid:
                    state.error = f"This name is already {existing_id} in the key file."
                    return False
                names = (_fold(first), _fold(family))
                if any(
                    row["id"] == pid
                    and (_fold(row["first_name"]), _fold(row["family_name"])) != names
                    for row in _rows(self._key_file)
                ):
                    state.error = f"{pid} already belongs to another participant in the key file."
                    return False
                if existing_id is None:
                    _append(self._key_file, pid, first, family)
        except (OSError, UnicodeError, csv.Error):
            state.error = "Could not save the key file. Check its location and write permissions."
            return False
        ctx.participant = state.active_pid = pid
        state.local_name = " ".join(filter(None, (first, family)))
        state.error = ""
        ctx.log(f"Participant {pid} · saving to {(self._sessions_dir / pid).as_posix()}/")
        return True

    def ui(self, ctx: Context) -> None:
        """Draw the participant chip and its selection modal.

        Parameters
        ----------
        ctx : Context
            Live app context. Only its pseudonymised ``participant`` ID is
            changed, and only while ``state == "idle"``.
        """
        state = self._state
        if state.active_pid != ctx.participant:
            state.active_pid, state.local_name = ctx.participant, ""
            if ctx.participant:
                row = next((r for r in _rows(self._key_file) if r["id"] == ctx.participant), None)
                if row:
                    state.local_name = " ".join(
                        filter(None, (row["first_name"], row["family_name"]))
                    )
        imgui.push_id(self._widget_id)
        try:
            busy = ctx.state != "idle"
            imgui.begin_disabled(busy)
            font = mono_font() if ctx.participant else None
            if font is not None:
                imgui.push_font(font, imgui.get_style().font_size_base)
            if not ctx.participant:
                imgui.push_style_color(imgui.Col_.text, WARNING)
            clicked = imgui.button(f"{ctx.participant or 'Set participant'}###chip")
            if not ctx.participant:
                imgui.pop_style_color()
            if font is not None:
                imgui.pop_font()
            imgui.end_disabled()
            if busy and imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
                imgui.set_tooltip(
                    "Finish recording, training or predicting before changing participant."
                )
            requested = state.open_requested or clicked
            state.open_requested = False
            if requested and not busy:
                self._prepare()
                imgui.open_popup("participant-modal")
            self._dialog(ctx)
        finally:
            imgui.pop_id()

    def _dialog(self, ctx: Context) -> None:
        """Choose a recorded ID or enter a new participant's local details."""
        viewport = imgui.get_main_viewport().work_size
        margin = ui_px(16)
        width = min(ui_px(700), viewport.x - 2 * margin)
        imgui.set_next_window_size(imgui.ImVec2(width, 0))
        imgui.set_next_window_size_constraints(
            imgui.ImVec2(width, 0), imgui.ImVec2(width, viewport.y - 2 * margin),
        )
        flags = (imgui.WindowFlags_.always_auto_resize | imgui.WindowFlags_.no_saved_settings
                 | imgui.WindowFlags_.no_title_bar)
        opened, _ = imgui.begin_popup_modal("participant-modal", None, flags)
        state = self._state
        if not opened:
            state.show_names = False
            return
        try:
            if ctx.state != "idle":
                self._close()
                return
            panel_header("Participant")
            if state.tab == 0 and state.recorded:
                selected = state.show_names
                if selected:
                    push_selected()
                clicked = imgui.button("Hide names" if selected else "Show names")
                if selected:
                    pop_selected()
                if clicked:
                    state.show_names = not selected
                    state.search = ""
            options = [f"Recorded {len(state.recorded)}", "New participant"]
            style = imgui.get_style()
            padding = max(0, (imgui.get_content_region_avail().x
                             - sum(imgui.calc_text_size(label).x for label in options) - 2) / 4)
            imgui.push_style_var(imgui.StyleVar_.frame_padding,
                                 imgui.ImVec2(padding, style.frame_padding.y))
            state.tab = segmented("participant-tabs", options, state.tab)
            imgui.pop_style_var()
            imgui.spacing()
            if state.tab == 0:
                self._recorded_ui(ctx)
            else:
                self._new_ui(ctx)
        finally:
            imgui.end_popup()

    def _recorded_ui(self, ctx: Context) -> None:
        """Render cached takes, keeping the selected identity independent of search."""
        state = self._state
        if not state.recorded:
            imgui.text_wrapped(f"No one recorded in {self._sessions_dir.as_posix()}/ yet")
            _support("Start with a new participant. Everyone you record shows up here next time.")
            if imgui.button("Cancel"):
                self._close()
            if primary_button("New participant", size=(imgui.get_content_region_avail().x, 0)):
                state.tab = 1
            return
        imgui.text_colored(muted(), "Search ID or name" if state.show_names else "Search ID")
        imgui.set_next_item_width(-1)
        _, state.search = imgui.input_text("##Search", state.search)
        imgui.text_colored(muted(), "Last recorded first")
        rows = self._filtered()
        chosen = next((row for row in state.recorded if row.pid == state.selected), None)
        drive = chosen is not None and chosen.model is not None and self._on_drive is not None
        privacy = "Names come from the key file on this computer, never from a recording."
        style = imgui.get_style()
        room = imgui.get_content_region_avail().x
        # Reserve the summary, captions and actions before sizing the scrolling list.
        footer = (imgui.get_frame_height_with_spacing() * (4 if drive else 3)
                  + imgui.calc_text_size(privacy, wrap_width=room).y
                  + 2 * imgui.get_text_line_height_with_spacing() + 5 * style.item_spacing.y
                  + 2 * style.window_padding.y)
        if state.error:
            footer += imgui.calc_text_size(state.error, wrap_width=room).y + style.item_spacing.y
        height = max(imgui.get_text_line_height_with_spacing(), min(
            ui_px(260), imgui.get_main_viewport().work_size.y - 2 * ui_px(16)
            - imgui.get_cursor_pos_y() - footer,
        ))
        imgui.begin_child("recorded-participants", imgui.ImVec2(0, height))
        try:
            if not rows:
                imgui.text_wrapped("No matching participants. Try another ID" +
                                   (" or name." if state.show_names else "."))
            for row in rows:
                if _recorded_row(row, row.pid == state.selected, state.show_names):
                    state.selected = row.pid
        finally:
            imgui.end_child()
        chosen = next((row for row in state.recorded if row.pid == state.selected), None)
        if chosen:
            with tinted_row(primary()) as width:
                _line(f"{chosen.pid} · {chosen.takes} takes · {_duration(chosen.duration_s)}", width,
                      mono=True)
            _support(f"Model saved {_when(chosen.model_time).lower()}" if chosen.model_time else
                     "No model yet — train after Continue.")
        _support(privacy)
        if state.error:
            _support(state.error, DANGER)
        if imgui.button("Cancel"):
            self._close()
        if (chosen and chosen.model is not None and self._on_drive is not None
                and imgui.button("Drive with saved model", imgui.ImVec2(-1, 0))
                and self._start(ctx, chosen.pid, "", "")):
            try:
                self._on_drive(chosen.pid, chosen.model)
            except Exception:
                # Loader errors can contain local names or persisted model contents.
                state.error = "Could not load the saved model. Try Continue and retrain."
            else:
                self._close()
        imgui.begin_disabled(chosen is None)
        label = f"Continue with {chosen.pid}" if chosen else "Choose a participant"
        if (primary_button(label, size=(imgui.get_content_region_avail().x, 0)) and chosen
                and self._start(ctx, chosen.pid, "", "")):
            self._close()
        imgui.end_disabled()

    def _new_ui(self, ctx: Context) -> None:
        """Caption fields above their controls and stack them in narrow dialogs."""
        state = self._state
        style = imgui.get_style()
        room = imgui.get_content_region_avail().x
        name_rows = 1 if room >= ui_px(440) else 2
        captions = ("Stays on this computer, in the key file. Never in a recording.",
                    "Recorded before? Pick them in Recorded — their takes and model come back with them.")
        desired = ((1 + name_rows) * (imgui.get_frame_height_with_spacing()
                                     + imgui.get_text_line_height_with_spacing())
                   + 3 * imgui.get_text_line_height_with_spacing() + 2 * style.window_padding.y
                   + sum(imgui.calc_text_size(text, wrap_width=room).y for text in captions)
                   + 5 * style.item_spacing.y)
        footer = 2 * imgui.get_frame_height_with_spacing() + 2 * style.window_padding.y
        if state.error:
            footer += imgui.calc_text_size(state.error, wrap_width=room).y + style.item_spacing.y
        available = (imgui.get_main_viewport().work_size.y - 2 * ui_px(16)
                     - imgui.get_cursor_pos_y() - footer)
        imgui.begin_child("new-participant-form", imgui.ImVec2(0, max(
            imgui.get_frame_height(), min(desired, available),
        )))
        try:
            self._new_form()
        finally:
            imgui.end_child()
        pid = _slug(state.pid)
        if state.error:
            _support(state.error, DANGER)
        if imgui.button("Cancel"):
            self._close()
        imgui.begin_disabled(not pid)
        if (primary_button("Start session", size=(imgui.get_content_region_avail().x, 0))
                and self._start(ctx, pid, state.first, state.family)):
            self._close()
        imgui.end_disabled()


    def _new_form(self) -> None:
        """Keep fields and path previews together in the scrollable form body."""
        state = self._state
        _, state.pid = _input_row("Participant ID", state.pid, mono=True)
        columns = 2 if imgui.get_content_region_avail().x >= ui_px(440) else 1
        changed = []
        if imgui.begin_table("names", columns, imgui.TableFlags_.sizing_stretch_same):
            for caption, attr in (("First name", "first"), ("Family name", "family")):
                imgui.table_next_column()
                edited, value = _input_row(caption, getattr(state, attr))
                setattr(state, attr, value)
                changed.append(edited)
            imgui.end_table()
        _support(f"{fa.ICON_FA_LOCK}  Stays on this computer, in the key file. Never in a recording.")
        returning = (_lookup(self._key_file, state.first, state.family)
                     if state.first.strip() and state.family.strip() else None)
        if returning:
            if any(changed):
                state.pid = returning
            imgui.text_colored(muted(), "Returning participant")
        pid = _slug(state.pid)
        _preview(pid, self._sessions_dir)
        _support("Recorded before? Pick them in Recorded — their takes and model come back with them.")


def _support(text: str, tone: imgui.ImVec4 | None = None) -> None:
    """Wrap supporting copy so narrow dialogs retain every explanation."""
    imgui.push_style_color(imgui.Col_.text, muted() if tone is None else tone)
    imgui.text_wrapped(text)
    imgui.pop_style_color()


def _line(text: str, width: float, *, mono: bool = False,
          tone: imgui.ImVec4 | None = None) -> None:
    """Ellipsize in the rendering font and expose full text on hover."""
    font = mono_font() if mono else None
    if font is not None:
        imgui.push_font(font, imgui.get_style().font_size_base)
    try:
        shown = fit_text(text, max(0, width))
        if mono:
            mono_text(shown, tone)
        elif tone is not None:
            imgui.text_colored(tone, shown)
        else:
            imgui.text_unformatted(shown)
        if shown != text:
            imgui.set_item_tooltip(text)
    finally:
        if font is not None:
            imgui.pop_font()


def _recorded_row(row: _RecordedParticipant, selected: bool, show_names: bool) -> bool:
    """Draw a clickable row with a stacked variant below the table width."""
    width = imgui.get_content_region_avail().x
    narrow = width < ui_px(600)
    line = imgui.get_text_line_height_with_spacing()
    height = max(ui_px(34), (3 * line if narrow else line) + 2 * ui_px(5))
    if selected:
        push_selected()
    clicked = imgui.button(f"##recorded:{row.pid}", imgui.ImVec2(width, height))
    if selected:
        pop_selected()
    lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    after = imgui.get_cursor_pos()
    draw = imgui.get_window_draw_list()
    if selected:
        draw.add_rect(lo, hi, imgui.get_color_u32(primary()), imgui.get_style().frame_rounding,
                      thickness=ui_px(1))
    pad = ui_px(6)
    x, y = lo.x + pad, lo.y + ui_px(5)
    inner = width - 2 * pad

    def cell(text: str, left: float, top: float, room: float, *, mono: bool = False,
             tone: imgui.ImVec4 | None = None) -> None:
        imgui.set_cursor_screen_pos(imgui.ImVec2(left, top))
        _line(text, room, mono=mono, tone=tone)

    name = (row.name if show_names else "•••••  •••••••") if row.name else ""
    model = fa.ICON_FA_CHECK if row.model else "—"
    if narrow:
        cell(row.pid, x, y, ui_px(68), mono=True)
        cell(name, x + ui_px(76), y, max(0, inner - ui_px(102)), tone=muted())
        cell(model, hi.x - pad - ui_px(20), y, ui_px(20), tone=SUCCESS if row.model else muted())
        gesture_x, gesture_y, gesture_w = x, y + line, max(0, inner - ui_px(85))
        cell(f"{row.takes} · {_duration(row.duration_s)}", hi.x - pad - ui_px(80), y + line,
             ui_px(80), mono=True)
        cell(_when(row.last), x, y + 2 * line, inner, mono=True, tone=muted())
    else:
        name_w = inner - ui_px(430)
        cell(row.pid, x, y, ui_px(72), mono=True)
        cell(name, x + ui_px(80), y, name_w, tone=muted())
        gesture_x, gesture_y, gesture_w = x + ui_px(88) + name_w, y, ui_px(78)
        cell(f"{row.takes} · {_duration(row.duration_s)}", hi.x - pad - ui_px(246), y,
             ui_px(90), mono=True)
        cell(_when(row.last), hi.x - pad - ui_px(150), y, ui_px(124), mono=True, tone=muted())
        cell(model, hi.x - pad - ui_px(20), y, ui_px(20), tone=SUCCESS if row.model else muted())
    if not row.class_names:
        cell("cursor", gesture_x, gesture_y, gesture_w, mono=True, tone=muted())
    else:
        dots = [(index, name) for index, name in enumerate(row.class_names) if name in row.gestures]
        for ordinal, (index, _name) in enumerate(dots):
            offset = ordinal * ui_px(11) + ui_px(4)
            if offset + ui_px(4) > gesture_w:
                break
            draw.add_circle_filled(imgui.ImVec2(gesture_x + offset, gesture_y + line / 2),
                                   ui_px(3), imgui.get_color_u32(imgui.ImVec4(
                                       *PALETTE[index % len(PALETTE)], 1.0)))
        imgui.set_cursor_screen_pos(imgui.ImVec2(gesture_x, gesture_y))
        imgui.dummy(imgui.ImVec2(gesture_w, line))
        imgui.set_item_tooltip(", ".join(name for _, name in dots))
    imgui.set_cursor_pos(after)
    imgui.dummy(imgui.ImVec2(0, 0))
    return clicked


def _input_row(label: str, value: str, *, mono: bool = False) -> tuple[bool, str]:
    """Place a caption above a full-width field in the current table column."""
    imgui.text_colored(muted(), label)
    imgui.set_next_item_width(-1)
    font = mono_font() if mono else None
    if font is not None:
        imgui.push_font(font, imgui.get_style().font_size_base)
    try:
        return imgui.input_text(f"##{label}", value)
    finally:
        if font is not None:
            imgui.pop_font()


def _preview(pid: str, sessions_dir: Path = Path("sessions")) -> None:
    """Show shared recording paths without widening the dialog to fit them."""
    path = labelled_path(sessions_dir, pid)
    lines = (
        f"Folder: {path.parent.as_posix()}/",
        f"Recording: {path.as_posix()}.session.zip",
        f"Model: {path.as_posix()}_model.joblib",
    )
    imgui.push_style_color(imgui.Col_.child_bg, CONSOLE_BG)
    padding = imgui.get_style().window_padding
    height = imgui.get_text_line_height_with_spacing() * len(lines) + 2 * padding.y
    imgui.begin_child("##preview", imgui.ImVec2(0, height),
                      child_flags=imgui.ChildFlags_.always_use_window_padding)
    try:
        for line in lines:
            _line(line, imgui.get_content_region_avail().x, mono=True, tone=CONSOLE_TEXT)
    finally:
        imgui.end_child()
        imgui.pop_style_color()
