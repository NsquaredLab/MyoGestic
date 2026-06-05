"""Session manager widget: load/select sessions and class filters for training."""

from __future__ import annotations

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui
from imgui_bundle import portable_file_dialogs as pfd

from myogestic.contracts import TrainingData
from myogestic.widgets.common import PALETTE, panel_header
from myogestic.widgets.training._session_state import (
    SessionWidgetState,
    add_recorded_session,
    class_pool_and_active,
    get_state,
    load_session_files,
)

__all__ = ["add_recorded_session", "session_manager"]


def session_manager(
    base_path: str = "sessions",
    label: str = "Sessions",
    class_names: list[str] | None = None,
) -> TrainingData:
    """Session picker widget. Returns ``TrainingData(paths, class_names, classes)``.

    The widget has two training filters: selected session files and selected
    class indices. Session scanning/state lives in
    ``_session_manager_state.py``. Assign the returned value to
    ``pipeline.training_data`` to make it visible to ``@pipeline.train``::

        @app.ui
        def ui(ctx):
            pipeline.training_data = session_manager(...)
    """
    uid = f"{label}_{base_path}"
    state = get_state(uid)

    panel_header(label, fa.ICON_FA_FOLDER_OPEN)
    render_summary_and_buttons(uid, base_path, state)
    poll_file_dialog(state)

    classes_in_pool, active_classes = class_pool_and_active(state)
    render_class_buttons(
        uid, state.deactivated_classes, classes_in_pool, active_classes, class_names
    )
    render_session_rows(uid, state.sessions, class_names)

    return TrainingData(
        paths=[s["path"] for s in state.sessions if s["selected"]],
        class_names=list(class_names) if class_names else [],
        classes=set(active_classes) if classes_in_pool else set(),
    )


def render_summary_and_buttons(uid: str, base_path: str, state: SessionWidgetState) -> None:
    sessions = state.sessions
    n_selected = sum(1 for s in sessions if s["selected"])
    summary = f"{n_selected}/{len(sessions)} selected"
    if state.last_load_msg:
        summary = f"{summary}  ·  {state.last_load_msg}"

    imgui.align_text_to_frame_padding()
    imgui.text(summary)
    imgui.same_line()
    if imgui.button(f"Load Files...##{uid}"):
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

    if not sessions:
        return
    imgui.same_line()
    if imgui.button(f"Clear##{uid}"):
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


def render_class_buttons(
    uid: str,
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
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.31, 0.61, 0.98, 0.9))
        if imgui.button(f"{name}##{uid}_button{ci}"):
            if is_active:
                deactivated_classes.add(ci)
            else:
                deactivated_classes.discard(ci)
        if is_active:
            imgui.pop_style_color()
        imgui.same_line()
    imgui.new_line()


def render_session_rows(uid: str, sessions: list[dict], class_names: list[str] | None) -> None:
    for i, row in enumerate(sessions):
        changed, checked = imgui.checkbox(f"##{uid}_{i}", row["selected"])
        if changed:
            row["selected"] = checked
        imgui.same_line()
        imgui.text_colored(
            imgui.ImVec4(0.93, 0.95, 0.98, 1.0),
            f"{row.get('date_str', row['name'])}  ·  {row.get('streams_str', '')}",
        )
        render_label_counts(row, class_names)


def render_label_counts(row: dict, class_names: list[str] | None) -> None:
    counts = row.get("label_counts", {})
    named_counts = sorted(
        ((int(k), v) for k, v in counts.items() if int(k) >= 0),
        key=lambda x: x[0],
    )
    if named_counts:
        imgui.same_line()
        imgui.text_colored(imgui.ImVec4(0.55, 0.58, 0.62, 1.0), "·")
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
            imgui.ImVec4(0.55, 0.58, 0.62, 1.0),
            f"·  unlabeled:{unlabeled}",
        )
