"""Generic template-row review table.

A reusable accept/reject + click-to-select widget. Caller owns extraction
(the ``Extract Templates`` button + worker thread + how to build rows from
sessions); this widget renders the resulting rows and lets the user check
checkboxes and click rows to select one for inspection.

Reusable from any example that wants an "extract → review → train"
workflow (regression target picking, NN onset detection, …).

Design notes:
- ``TemplateInspectorRow`` is a small mutable dataclass; the widget
  toggles ``accepted`` in place when the user ticks a checkbox. Caller
  reads ``[r for r in rows if r.accepted]`` to pull the selected set.
- The widget returns the currently-selected row's ``key`` (or ``None``)
  so the caller can render a preview / details panel for that row.
- No alias maps, label classification, or model semantics live here —
  those stay in user code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TemplateInspectorRow:
    """One row in the inspector table.

    Parameters
    ----------
    key
        Stable identity (e.g. ``"<session>#<trial_idx>"``). The
        widget uses this for selection and for ImGui id disambiguation.
    label
        Short class/category badge (e.g. ``"OPEN"`` / ``"CLOSED"``).
    accepted
        Mutable. True = include in training. Toggled in place
        by the checkbox.
    info_text
        Optional secondary text shown in the table (e.g.
        session name, source path). May be ``None``.
    energy
        Optional scalar shown as a normalised progress bar in
        the energy column. Caller's choice of metric — RMS energy,
        peak amplitude, anything monotonic. ``None`` hides the bar.
    """
    key: str
    label: str
    accepted: bool = True
    info_text: str | None = None
    energy: float | None = None


# Per-uid selection state. Module-level so two render passes with the
# same uid share state (immediate-mode render survives across frames).
_SELECTED: dict[str, str | None] = {}


def template_inspector(
    uid: str,
    rows: list[TemplateInspectorRow],
    *,
    title: str = "Templates",
    height: float = 240.0,
    label_colors: dict[str, tuple[float, float, float, float]] | None = None,
) -> str | None:
    """Render the table. Returns the selected row's key (or ``None``).

    Parameters
    ----------
    uid
        Stable identity string. Two calls with the same uid share
        selection state across frames; different uids are independent.
    rows
        List of ``TemplateInspectorRow`` to render. Mutated in place
        (only ``accepted`` is touched by the widget).
    title
        Header text shown above the table.
    height
        Table height in pixels.
    label_colors
        Optional ``{label_text: (r, g, b, a)}`` for the
        colored badge in the label column. Unmapped labels render in
        the default text color.

    Returns
    -------
    The ``key`` of the currently-selected row (or ``None`` if no row
    is selected, or the previously-selected row was removed).
    """
    from imgui_bundle import imgui

    label_colors = label_colors or {}
    selected = _SELECTED.get(uid)
    # Drop a stale selection if its row is no longer in the table.
    if selected is not None and not any(r.key == selected for r in rows):
        selected = None
        _SELECTED[uid] = None

    if title:
        imgui.text(title)
    if not rows:
        imgui.text_disabled("(no rows)")
        return selected

    # Energy bar normalisation (relative to current rows).
    e_max = max((r.energy or 0.0) for r in rows) or 1.0

    if imgui.begin_table(
        f"##{uid}_tinsp",
        5,
        imgui.TableFlags_.borders_inner_h
        | imgui.TableFlags_.row_bg
        | imgui.TableFlags_.scroll_y,
        imgui.ImVec2(-1, height),
    ):
        imgui.table_setup_column("Use", imgui.TableColumnFlags_.width_fixed, 30)
        imgui.table_setup_column("Label", imgui.TableColumnFlags_.width_fixed, 70)
        imgui.table_setup_column("Source", imgui.TableColumnFlags_.width_stretch)
        imgui.table_setup_column("Energy", imgui.TableColumnFlags_.width_fixed, 80)
        imgui.table_setup_column("Trial", imgui.TableColumnFlags_.width_fixed, 50)
        for i, row in enumerate(rows):
            imgui.table_next_row()
            imgui.table_next_column()
            changed, new_acc = imgui.checkbox(f"##{uid}_acc{i}", row.accepted)
            if changed:
                row.accepted = new_acc
            imgui.table_next_column()
            color_rgba = label_colors.get(row.label)
            if color_rgba is not None:
                imgui.text_colored(imgui.ImVec4(*color_rgba), row.label)
            else:
                imgui.text(row.label)
            imgui.table_next_column()
            is_selected = row.key == selected
            label_text = row.info_text or row.key
            clicked, _ = imgui.selectable(
                f"{label_text}##{uid}_sel{i}",
                is_selected,
                imgui.SelectableFlags_.span_all_columns,
            )
            if clicked:
                selected = row.key
                _SELECTED[uid] = selected
            imgui.table_next_column()
            if row.energy is not None:
                imgui.progress_bar(
                    min(row.energy / e_max, 1.0), imgui.ImVec2(70, 0), ""
                )
            else:
                imgui.text_disabled("—")
            imgui.table_next_column()
            tail = row.key.split("#")[-1] if "#" in row.key else ""
            imgui.text(tail)
        imgui.end_table()

    return selected


def clear_selection(uid: str) -> None:
    """Drop the cached selection for ``uid`` (e.g. after Clear button)."""
    _SELECTED[uid] = None
