"""Participant selection with names kept only in memory and a local key file."""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from imgui_bundle import imgui

from myogestic._theme import mono_font
from myogestic.core import Context
from myogestic.session import labelled_path
from myogestic.session._core import _slug
from myogestic.widgets.common import DANGER, WARNING, muted, panel_header, primary_button, ui_px

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
class _ParticipantState:
    """Private input and local display state, addressed by widget identity."""

    pid: str = ""
    first: str = ""
    family: str = ""
    active_pid: str | None = None
    local_name: str = ""
    error: str = ""


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
    ) -> None:
        self._key_file = Path(key_file).expanduser()
        self._widget_id = widget_id

    @property
    def _state(self) -> _ParticipantState:
        return _states.setdefault(self._widget_id, _ParticipantState())

    def _start(self, ctx: Context, pid: str, first: str, family: str) -> bool:
        """Commit only the ID to context, after any local name has been saved."""
        pid, first, family = _slug(pid), first.strip(), family.strip()
        if ctx.state != "idle" or not pid:
            return False
        state = self._state
        try:
            if (first or family) and _lookup(self._key_file, first, family) is None:
                _append(self._key_file, pid, first, family)
        except (OSError, UnicodeError, csv.Error):
            state.error = "Could not save the key file. Check its location and write permissions."
            return False
        ctx.participant = state.active_pid = pid
        state.local_name = " ".join(filter(None, (first, family)))
        state.error = ""
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
            if clicked and not busy:
                state.pid = _next_id(self._key_file)
                state.first = state.family = state.error = ""
                imgui.open_popup("participant-modal")
            if state.local_name:
                imgui.same_line()
                imgui.align_text_to_frame_padding()
                imgui.text_colored(muted(), state.local_name)
            self._dialog(ctx)
        finally:
            imgui.pop_id()

    def _dialog(self, ctx: Context) -> None:
        """Edit names locally and preview the same slugged paths recording uses."""
        flags = (
            imgui.WindowFlags_.always_auto_resize
            | imgui.WindowFlags_.no_saved_settings
            | imgui.WindowFlags_.no_title_bar
        )
        opened, _ = imgui.begin_popup_modal("participant-modal", None, flags)
        if not opened:
            return
        state = self._state
        try:
            if ctx.state != "idle":
                imgui.close_current_popup()
                return
            panel_header("Participant")
            imgui.set_next_item_width(ui_px(320))
            _, state.pid = imgui.input_text("Participant ID", state.pid)
            imgui.set_next_item_width(ui_px(320))
            first_changed, state.first = imgui.input_text("First name", state.first)
            imgui.set_next_item_width(ui_px(320))
            family_changed, state.family = imgui.input_text("Family name", state.family)
            returning = None
            if state.first.strip() and state.family.strip():
                returning = _lookup(self._key_file, state.first, state.family)
            if returning:
                if first_changed or family_changed:
                    state.pid = returning
                imgui.text_colored(muted(), "Returning participant")
            pid = _slug(state.pid)
            path = labelled_path("sessions", pid)
            imgui.spacing()
            imgui.text_colored(muted(), f"Folder: {path.parent.as_posix()}/")
            imgui.text_colored(muted(), f"Recording: {path.as_posix()}.session.zip")
            imgui.text_colored(muted(), f"Model: {path.as_posix()}_model.joblib")
            if state.error:
                imgui.text_colored(DANGER, state.error)
            imgui.begin_disabled(not pid)
            if primary_button("Start session") and self._start(ctx, pid, state.first, state.family):
                imgui.close_current_popup()
            imgui.end_disabled()
            imgui.same_line()
            if imgui.button("Cancel"):
                imgui.close_current_popup()
        finally:
            imgui.end_popup()
