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
    primary,
    push_selected,
    ui_px,
)
from myogestic.widgets.training._session_state import (
    SessionWidgetState,
    add_recorded_session,
    class_pool_and_active,
    get_state,
    load_session_files,
    scan_sessions,
)

__all__ = ["SessionManager", "add_recorded_session"]


class SessionManager:
    """Session picker widget. ``ui()`` returns ``TrainingData(paths, class_names, classes)``.

    Construct once with the base path / title / class names, then call
    [`ui`][] each frame. The widget has two training filters: selected
    session files and selected class indices. Assign the returned value to
    ``pipeline.training_data`` to make it visible to ``@pipeline.train``::

        sessions = SessionManager("sessions", class_names=CLASSES)

        @app.ui
        def ui(ctx):
            pipeline.training_data = sessions.ui()

    Parameters
    ----------
    base_path
        Folder scanned for ``.session.zip`` archives and session folders. Not
        read until you press **Scan folder**, unless ``ui(participant=...)``
        scopes the list to a participant whose takes appear automatically.
    title
        Panel header text. Also part of the widget's ImGui id scope, so two
        managers over the same folder need different titles to keep separate
        selections.
    class_names
        Human-readable names for the label class indices, used to render the
        per-class filter buttons. ``None`` falls back to whatever each session
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

        # Unfiltered callers retain the explicit Scan workflow; a participant
        # scopes discovery without silently selecting any earlier takes.
        panel_header(self._title, fa.ICON_FA_FOLDER_OPEN)
        poll_file_dialog(state)
        if not participant or state.sessions:
            render_summary_and_buttons(widget_id, scan_path, state)

        classes_in_pool, active_classes = class_pool_and_active(state)
        render_class_buttons(
            widget_id, state.deactivated_classes, classes_in_pool, active_classes, class_names
        )
        render_session_rows(widget_id, state.sessions, class_names)
        if participant and not state.sessions:
            _render_empty_participant(widget_id, scan_path, state)

        return TrainingData(
            paths=[s["path"] for s in state.sessions if s["selected"]],
            class_names=list(class_names) if class_names else [],
            classes=set(active_classes) if classes_in_pool else set(),
        )


def render_summary_and_buttons(widget_id: str, base_path: str, state: SessionWidgetState) -> None:
    sessions = state.sessions
    n_selected = sum(1 for s in sessions if s["selected"])
    summary = f"{n_selected}/{len(sessions)} selected"
    if state.last_load_msg:
        summary = f"{summary}  ·  {state.last_load_msg}"

    imgui.align_text_to_frame_padding()
    imgui.text(summary)
    imgui.same_line()
    if imgui.button(f"Load Files...##{widget_id}"):
        state.folder_dialog = pfd.open_file(
            "Select session files",
            base_path,
            ["Session zip", "*.zip"],
            pfd.opt.multiselect,
        )
    if imgui.is_item_hovered():
        imgui.set_tooltip(
            "Pick one or more session zip files (multi-select).\n"
            "Any .zip with a meta.json inside is treated as a session."
        )

    imgui.same_line()
    if imgui.button(f"Scan folder##{widget_id}"):
        # Merge rather than replace: a session just recorded in this run is in the
        # list but not yet on disk under a name this finds, and losing it to a scan
        # would be losing the only copy the user has looked at.
        existing = {s["path"] for s in sessions}
        found = [r for r in scan_sessions(base_path) if r["path"] not in existing]
        sessions.extend(found)
        state.last_load_msg = f"scanned {base_path}: {len(found)} new"
    if imgui.is_item_hovered():
        imgui.set_tooltip(
            f"List every session already in {base_path}.\n"
            "Earlier takes stay unticked until you choose them for training."
        )

    if not sessions:
        return
    imgui.same_line()
    if imgui.button(f"Clear##{widget_id}"):
        sessions.clear()
        state.last_load_msg = ""
    if imgui.is_item_hovered():
        imgui.set_tooltip("Drop all loaded sessions from the list.")


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
    widget_id: str,
    deactivated_classes: set[int],
    classes_in_pool: set[int],
    active_classes: set[int],
    class_names: list[str] | None,
) -> None:
    if not classes_in_pool:
        return

    imgui.align_text_to_frame_padding()
    imgui.text("Classes:")
    imgui.same_line()
    for ci in sorted(classes_in_pool):
        name = (
            class_names[ci] if class_names is not None and 0 <= ci < len(class_names) else f"c{ci}"
        )
        is_active = ci in active_classes
        if is_active:
            push_selected()
        if imgui.button(f"{name}##{widget_id}_button{ci}"):
            if is_active:
                deactivated_classes.add(ci)
            else:
                deactivated_classes.discard(ci)
        if is_active:
            pop_selected()
        imgui.same_line()
    imgui.new_line()


def render_session_rows(
    widget_id: str, sessions: list[dict], class_names: list[str] | None
) -> None:
    for i, row in enumerate(sessions):
        changed, checked = imgui.checkbox(f"##{widget_id}_{i}", row["selected"])
        if changed:
            row["selected"] = checked
        imgui.same_line()
        # The operator's own name leads when there is one — that is what they
        # will be scanning for. The timestamp always follows, since it is the
        # only part guaranteed unique.
        stamp = row.get("date_str", row["name"])
        given = row.get("session_name", "")
        label = f"{given}  ·  {stamp}" if given else stamp
        duration = _elapsed_str(row.get("duration_s", 0.0))
        font = mono_font()
        if font is not None:
            imgui.push_font(font, imgui.get_style().font_size_base)
        try:
            right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
            duration_width = imgui.calc_text_size(duration).x
            label_width = imgui.get_content_region_avail().x - duration_width - ui_px(12)
            if imgui.calc_text_size(label).x > label_width:
                while label and imgui.calc_text_size(label + "…").x > label_width:
                    label = label[:-1]
                label = label + "…" if label else ""
            mono_text(label, primary())
            imgui.same_line()
            imgui.set_cursor_pos_x(max(imgui.get_cursor_pos_x(), right - duration_width))
            mono_text(duration, muted())
        finally:
            if font is not None:
                imgui.pop_font()
        if row.get("class_seconds"):
            _render_class_seconds(row, class_names)
        else:
            render_label_counts(row, class_names)
        if imgui.is_item_hovered():
            imgui.set_tooltip(f"{row['name']}\n{row.get('streams_str', '')}")


def _elapsed_str(seconds: float) -> str:
    """Format seconds as the stopwatch duration shown beside a take."""
    minutes, secs = divmod(max(0, int(seconds)), 60)
    return f"{minutes}:{secs:02d}"


def _render_class_seconds(row: dict, class_names: list[str] | None) -> None:
    """Draw a wrapping row of categorical, theme-readable duration chips."""
    names = row.get("class_names") or class_names or list(row["class_seconds"])
    right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
    pad = imgui.ImVec2(ui_px(7), ui_px(3))
    for i, (name, seconds) in enumerate(row["class_seconds"].items()):
        label = f"{name} {_elapsed_str(seconds)}"
        text_size = imgui.calc_text_size(label)
        size = imgui.ImVec2(text_size.x + pad.x * 2, text_size.y + pad.y * 2)
        if i and imgui.get_item_rect_max().x + imgui.get_style().item_spacing.x + size.x <= right:
            imgui.same_line()
        imgui.dummy(size)
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        ci = names.index(name) if name in names else i
        color = PALETTE[ci % len(PALETTE)]
        draw = imgui.get_window_draw_list()
        draw.add_rect_filled(
            lo, hi, imgui.get_color_u32(imgui.ImVec4(color[0], color[1], color[2], 0.16)), ui_px(4),
        )
        draw.add_text(
            imgui.ImVec2(lo.x + pad.x, lo.y + pad.y), imgui.get_color_u32(imgui.Col_.text), label,
        )


def render_label_counts(row: dict, class_names: list[str] | None) -> None:
    counts = row.get("label_counts", {})
    named_counts = sorted(
        ((int(k), v) for k, v in counts.items() if int(k) >= 0),
        key=lambda x: x[0],
    )
    if named_counts:
        imgui.same_line()
        imgui.text_colored(muted(), "·")
        sess_names = row.get("class_names") or class_names
        for ci, n in named_counts:
            imgui.same_line()
            c = PALETTE[ci % len(PALETTE)]
            imgui.text_colored(imgui.ImVec4(c[0], c[1], c[2], 1.0), "●")
            imgui.same_line()
            name = (
                sess_names[ci] if sess_names is not None and 0 <= ci < len(sess_names) else f"c{ci}"
            )
            imgui.text(f"{name}:{n}")

    unlabeled = counts.get("-1", 0)
    if unlabeled:
        imgui.same_line()
        imgui.text_colored(
            muted(),
            f"·  unlabeled:{unlabeled}",
        )
