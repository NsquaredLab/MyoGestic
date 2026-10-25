"""Session manager widget: load/select sessions and class filters for training."""

from __future__ import annotations

from pathlib import Path

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui
from imgui_bundle import portable_file_dialogs as pfd

from myogestic.contracts import TrainingData
from myogestic.session._core import _slug
from myogestic.widgets.common import (
    PALETTE,
    mono_font,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    push_selected,
    ui_px,
)
from myogestic.widgets.training._session_state import (
    SelectionSummary,
    SessionWidgetState,
    add_recorded_session,
    class_pool_and_active,
    get_state,
    group_sessions,
    load_session_files,
    row_gestures,
    scan_sessions,
    selection_summary,
)

__all__ = ["SelectionSummary", "SessionManager", "add_recorded_session"]


class SessionManager:
    """One-line takes grouped by day, with gesture filters and a selection summary.

    Construct once with the base path / title / class names, then call
    [`ui`][] each frame. The widget has two training filters: selected
    session files and included class indices. Only the newest day starts open;
    the list scrolls while its header, summary and gesture chips stay visible.
    Files loaded outside the scanned folder appear under **Loaded**. Read
    ``selection()`` for selected-take counts and included gesture seconds.
    Assign the returned value to
    ``pipeline.training_data`` to make it visible to ``@pipeline.train``::

        sessions = SessionManager("sessions", class_names=CLASSES)

        @app.ui
        def ui(ctx):
            pipeline.training_data = sessions.ui()

    Parameters
    ----------
    base_path
        Folder scanned for ``.session.zip`` archives and session folders. Not
        read until you press the **Rescan folder** icon, unless ``ui(participant=...)``
        scopes the list to a participant whose takes appear automatically.
    title
        Panel header text. Also part of the widget's ImGui id scope, so two
        managers over the same folder need different titles to keep separate
        selections.
    class_names
        Human-readable names for the label class indices, used to render the
        gesture chips (with totals across all listed takes). ``None`` falls back to whatever each session
        recorded in its own ``meta.json``, then to ``c0``, ``c1``, …

    Examples
    --------
    >>> from myogestic.widgets import SessionManager
    >>> manager = SessionManager("sessions", class_names=["Rest", "Fist"])
    >>> training_data = manager.ui()
    """

    def __init__(
        self,
        base_path: str = "sessions",
        *,
        title: str = "Sessions",
        class_names: list[str] | None = None,
    ) -> None:
        self._base_path = base_path
        self._title = title
        self._class_names = class_names
        self._widget_id = f"{title}_{base_path}"

    def ui(self, participant: str | None = None) -> TrainingData:
        """Render the picker and return the current training selection.

        Parameters
        ----------
        participant
            Participant ID whose subfolder to scan, using the same safe slug
            as recordings. A nonempty ID lists its takes automatically, unticked
            except newly recorded takes. Changing it clears the training selection
            and class filters. ``None`` or an empty ID leaves scanning manual.

        Returns
        -------
        TrainingData
            Selected session paths and active classes for training.
        """
        widget_id = self._widget_id
        class_names = self._class_names
        state = get_state(widget_id)
        participant = _slug(participant) if participant is not None else None
        scan_path = str(Path(self._base_path) / participant) if participant else self._base_path
        if participant != state.participant:
            state.sessions.clear()
            state.deactivated_classes.clear()
            state.last_load_msg = ""
            # A file picker opened for the previous participant must not refill
            # the newly cleared list when it completes.
            state.folder_dialog = None
            state.participant = participant
            if participant:
                state.sessions.extend(scan_sessions(scan_path))

        poll_file_dialog(state)
        render_header(widget_id, self._title, scan_path, state)
        render_summary(widget_id, self.selection(), state)
        render_class_buttons(widget_id, state, class_names)
        render_session_rows(widget_id, scan_path, state, class_names)
        if participant and not state.sessions:
            _render_empty_participant(widget_id, scan_path, state)

        # Read after every click so returned data and Train agree this frame.
        classes_in_pool, active_classes = class_pool_and_active(state)
        return TrainingData(
            paths=[s["path"] for s in state.sessions if s["selected"]],
            class_names=list(class_names) if class_names else [],
            classes=set(active_classes) if classes_in_pool else set(),
        )

    def selection(self) -> SelectionSummary:
        """Return selected-take counts and seconds for included gestures.

        Returns
        -------
        SelectionSummary
            An independent snapshot of the current selection. Reading it does
            not scan files, change filters, or require an ImGui context.
        """
        return selection_summary(get_state(self._widget_id), self._class_names)


def render_header(widget_id: str, title: str, base_path: str, state: SessionWidgetState) -> None:
    style = imgui.get_style()
    icons = [fa.ICON_FA_ARROWS_ROTATE, fa.ICON_FA_FOLDER_OPEN, fa.ICON_FA_BROOM]
    width = sum(imgui.calc_text_size(icon).x + 2 * style.frame_padding.x for icon in icons)
    width += 2 * style.item_spacing.x
    right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
    panel_header(f"Takes · {state.participant}" if state.participant else title,
                 fa.ICON_FA_FOLDER_OPEN, reserve=width + style.item_spacing.x)
    imgui.same_line()
    imgui.set_cursor_pos_x(max(imgui.get_cursor_pos_x(), right - width))
    if imgui.small_button(f"{icons[0]}##{widget_id}_scan"):
        existing = {s["path"] for s in state.sessions}
        found = [row for row in scan_sessions(base_path) if row["path"] not in existing]
        state.sessions.extend(found)
        state.last_load_msg = f"Scanned {base_path}: {len(found)} new"
    imgui.set_item_tooltip(f"Rescan folder: {base_path}\nEarlier takes stay unticked.")
    imgui.same_line()
    if imgui.small_button(f"{icons[1]}##{widget_id}_load"):
        state.folder_dialog = pfd.open_file(
            "Select session files", base_path, ["Session zip", "*.zip"], pfd.opt.multiselect,
        )
    imgui.set_item_tooltip("Load files from elsewhere… Choose one or more session zip files.")
    imgui.same_line()
    if imgui.small_button(f"{icons[2]}##{widget_id}_clear"):
        state.sessions.clear()
        state.deactivated_classes.clear()
        state.last_load_msg = ""
    imgui.set_item_tooltip("Clear the takes list. Files stay on disk.")


def render_summary(widget_id: str, summary: SelectionSummary, state: SessionWidgetState) -> None:
    style = imgui.get_style()
    right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
    width = sum(imgui.calc_text_size(label).x + 2 * style.frame_padding.x for label in ("All", "None"))
    width += style.item_spacing.x
    total = _elapsed_str(sum(summary.class_seconds.values()))
    imgui.text_colored(muted(), f"{summary.n_selected} of {summary.n_total} selected · {total} total")
    if state.last_load_msg:
        imgui.set_item_tooltip(state.last_load_msg)
    imgui.same_line()
    imgui.set_cursor_pos_x(max(imgui.get_cursor_pos_x(), right - width))
    for index, (label, selected) in enumerate((("All", True), ("None", False))):
        if index:
            imgui.same_line()
        if imgui.small_button(f"{label}##{widget_id}"):
            for row in state.sessions:
                row["selected"] = selected


def poll_file_dialog(state: SessionWidgetState) -> None:
    dialog = state.folder_dialog
    if dialog is None or not dialog.ready():  # type: ignore
        return
    result = dialog.result()  # type: ignore
    state.folder_dialog = None
    load_session_files(state, result or [])


def _render_empty_participant(
    widget_id: str, base_path: str, state: SessionWidgetState,
) -> None:
    """Centre the empty participant's guidance and existing file-picker action."""
    left = imgui.get_cursor_pos_x()
    width = imgui.get_content_region_avail().x
    height = imgui.get_text_line_height_with_spacing() * 3
    gap = max(0.0, (imgui.get_content_region_avail().y - height) / 2)
    imgui.dummy(imgui.ImVec2(0, gap))
    for line in (
        f"No takes for {state.participant} yet.",
        "Takes you record appear here, already ticked for training.",
    ):
        imgui.set_cursor_pos_x(left + max(0.0, (width - imgui.calc_text_size(line).x) / 2))
        imgui.text_colored(muted(), line)
    label = "Load files from elsewhere…"
    button_width = imgui.calc_text_size(label).x + imgui.get_style().frame_padding.x * 2
    imgui.set_cursor_pos_x(left + max(0.0, (width - button_width) / 2))
    if imgui.small_button(f"{label}##{widget_id}_empty"):
        state.folder_dialog = pfd.open_file(
            "Select session files", base_path, ["Session zip", "*.zip"], pfd.opt.multiselect,
        )


def render_class_buttons(
    widget_id: str, state: SessionWidgetState, class_names: list[str] | None,
) -> None:
    gestures: dict[tuple[int | None, str], float] = {}
    for row in state.sessions:
        for ci, name, seconds in row_gestures(row, class_names):
            gestures[ci, name] = gestures.get((ci, name), 0.0) + seconds
    right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
    for index, ((ci, name), seconds) in enumerate(gestures.items()):
        label = f"   {name} {_elapsed_str(seconds)}"
        width = imgui.calc_text_size(label).x + 2 * imgui.get_style().frame_padding.x
        if index and imgui.get_item_rect_max().x + imgui.get_style().item_spacing.x + width <= right:
            imgui.same_line()
        included = ci not in state.deactivated_classes
        if included:
            push_selected()
        clicked = imgui.button(f"{label}##{widget_id}_gesture{ci}")
        if included:
            pop_selected()
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        color = PALETTE[(ci if ci is not None else index) % len(PALETTE)]
        imgui.get_window_draw_list().add_circle_filled(
            imgui.ImVec2(lo.x + imgui.get_style().frame_padding.x + ui_px(3), (lo.y + hi.y) / 2),
            ui_px(3), imgui.get_color_u32(imgui.ImVec4(*color, 1.0)),
        )
        if clicked and ci is not None:
            if included:
                state.deactivated_classes.add(ci)
            else:
                state.deactivated_classes.discard(ci)
        imgui.set_item_tooltip(f"{'Exclude' if included else 'Include'} {name} in training")


def render_session_rows(
    widget_id: str, base_path: str, state: SessionWidgetState, class_names: list[str] | None,
) -> None:
    if not state.sessions:
        return
    height = max(ui_px(1), imgui.get_content_region_avail().y - imgui.get_style().item_spacing.y)
    imgui.begin_child(f"{widget_id}_list", imgui.ImVec2(0, height))
    for group in group_sessions(state.sessions, base_path):
        selected = sum(row["selected"] for row in group.rows)
        duration = _elapsed_str(sum(row.get("duration_s", 0.0) for row in group.rows))
        imgui.set_next_item_open(group.default_open, imgui.Cond_.once)
        if imgui.collapsing_header(
            f"{group.label}  {selected}/{len(group.rows)} · {duration}###{widget_id}_{base_path}_{group.key}"
        ):
            for row in group.rows:
                _render_row(widget_id, row, state.deactivated_classes, class_names)
    imgui.end_child()


def _render_row(
    widget_id: str, row: dict, excluded: set[int], class_names: list[str] | None,
) -> None:
    imgui.begin_group()
    right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
    _, row["selected"] = imgui.checkbox(f"##{widget_id}_{row['path']}", row["selected"])
    imgui.same_line()
    created = row.get("created")
    stamp = created.strftime("%H:%M") if created else "—"
    duration = _elapsed_str(row.get("duration_s", 0.0))
    font = mono_font()
    if font is not None:
        imgui.push_font(font, imgui.get_style().font_size_base)
    time_width = imgui.calc_text_size(stamp).x
    duration_width = imgui.calc_text_size(duration).x
    if font is not None:
        imgui.pop_font()
    gap = imgui.get_style().item_spacing.x
    time_x = right - time_width - gap - duration_width
    for index, (ci, name, _) in enumerate(row_gestures(row, class_names)):
        room = time_x - gap - imgui.get_cursor_pos_x()
        if room <= ui_px(10):
            break
        pad = ui_px(5)
        label = name
        while label and imgui.calc_text_size(label).x + 2 * pad > room:
            label = label[:-1]
        if label != name:
            label = label[:-1] + "…" if label else "…"
        width = min(room, imgui.calc_text_size(label).x + 2 * pad)
        imgui.dummy(imgui.ImVec2(width, imgui.get_frame_height()))
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        color = PALETTE[(ci if ci is not None else index) % len(PALETTE)]
        tone = muted() if ci in excluded else imgui.ImVec4(*color, 1.0)
        draw = imgui.get_window_draw_list()
        draw.add_rect_filled(lo, hi, imgui.get_color_u32(imgui.ImVec4(tone.x, tone.y, tone.z, 0.16)), ui_px(4))
        draw.add_text(imgui.ImVec2(lo.x + pad, lo.y + imgui.get_style().frame_padding.y),
                      imgui.get_color_u32(muted() if ci in excluded else imgui.get_style().color_(imgui.Col_.text)), label)
        imgui.same_line()
    imgui.set_cursor_pos_x(max(imgui.get_cursor_pos_x(), time_x))
    imgui.align_text_to_frame_padding()
    mono_text(stamp, muted())
    imgui.same_line()
    imgui.set_cursor_pos_x(max(imgui.get_cursor_pos_x(), right - duration_width))
    mono_text(duration, muted())
    imgui.end_group()
    name = row.get("session_name", "")
    imgui.set_item_tooltip(f"{name + chr(10) if name else ''}{row['name']}\n{row.get('streams_str', '')}")


def _elapsed_str(seconds: float) -> str:
    """Format seconds as the stopwatch duration shown beside a take."""
    minutes, secs = divmod(max(0, int(seconds)), 60)
    return f"{minutes}:{secs:02d}"
