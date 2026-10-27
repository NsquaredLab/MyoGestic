"""Compact template review with kept chips and gesture filters.

A reusable accept/reject + click-to-select widget. Caller owns extraction
(the ``Extract Templates`` button + worker thread + how to build rows from
sessions); this widget renders one-line rows with kept/out chips and lets
the user select a source for inspection. Gesture chips filter the visible
rows without changing which templates are kept for training.

Reusable from any example that wants an "extract → review → train"
workflow (regression target picking, NN onset detection, …).

Design notes:
- ``TemplateInspectorRow`` is a small mutable dataclass; the widget
  toggles ``accepted`` in place when the user clicks a kept/out chip. Caller
  reads ``[r for r in rows if r.accepted]`` to pull the selected set.
- The widget returns the currently-selected row's ``key`` (or ``None``)
  so the caller can render a preview / details panel for that row.
- No alias maps, label classification, or model semantics live here —
  those stay in user code.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from imgui_bundle import imgui

from myogestic._theme import mono_font
from myogestic.widgets.common import (
    PALETTE,
    _truncate_to_width,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    primary,
    push_selected,
    ui_px,
)


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
        by the kept/out chip, or the All / None buttons.
    info_text
        Optional secondary text shown in the table (e.g.
        session name, source path). May be ``None``.
    energy
        Optional scalar shown as a normalised progress bar in
        the energy column. Caller's choice of metric — RMS energy,
        peak amplitude, anything monotonic. ``None`` hides the bar.

    Examples
    --------
    >>> from myogestic.widgets import TemplateInspectorRow
    >>> row = TemplateInspectorRow("session#0", "Fist", accepted=True, energy=0.8)
    """

    key: str
    label: str
    accepted: bool = True
    info_text: str | None = None
    energy: float | None = None


# Per-widget_id selection state. Module-level so two render passes with the
# same widget_id share state (immediate-mode render survives across frames).
_SELECTED: dict[str, str | None] = {}
_FILTER: dict[str, str | None] = {}


class TemplateInspector:
    """Review templates with kept/out chips, gesture filters and source selection.

    Construct once with a stable ``widget_id`` (+ optional title / height /
    label colors), then call [`ui`][] each frame with the current rows.
    ``ui()`` returns the selected row's key (or ``None``).

    Parameters
    ----------
    widget_id
        Stable identity string. Two inspectors with the same widget_id share
        selection and gesture-filter state; different widget_ids are independent.
    title
        Header text shown above the table.
    height
        Table height at UI scale 1.0, scaled with the rest of the interface.
    label_colors
        Optional ``{label_text: (r, g, b, a)}`` identity colours for gesture
        dots and tag tints. Unmapped labels use PALETTE in sorted label order.
        Tag text always follows the active theme, including with caller colours.

    Notes
    -----
    All / None changes every row, including rows hidden by a gesture filter.
    Click an active gesture chip again to show all gestures. Filtering leaves
    the selected preview unchanged; removing its row clears the selection.

    Examples
    --------
    >>> from myogestic.widgets import TemplateInspector, TemplateInspectorRow
    >>> rows = [TemplateInspectorRow("session#0", "Fist")]
    >>> inspector = TemplateInspector("templates")
    >>> selected = inspector.ui(rows)
    """

    def __init__(
        self,
        widget_id: str,
        *,
        title: str = "Templates",
        height: float = 240.0,
        label_colors: dict[str, tuple[float, float, float, float]] | None = None,
    ) -> None:
        self._widget_id = widget_id
        self._title = title
        self._height = height
        self._label_colors = label_colors

    def ui(self, rows: list[TemplateInspectorRow]) -> str | None:
        """Render the table for ``rows``; return the selected row's key.

        ``rows`` is mutated in place (only ``accepted`` is touched). Returns
        ``None`` when no row is selected or the selection was removed.
        """
        widget_id = self._widget_id
        selected = _SELECTED.get(widget_id)
        # Drop a stale selection if its row is no longer in the table.
        if selected is not None and not any(r.key == selected for r in rows):
            selected = None
            _SELECTED[widget_id] = None

        imgui.push_id(widget_id)
        imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(ui_px(4), 0))
        try:
            _header(self._title, rows)
            if not rows:
                _FILTER[widget_id] = None
                imgui.push_text_wrap_pos(0)
                imgui.text_disabled("Extract templates from your selected sessions to review them.")
                imgui.pop_text_wrap_pos()
                return selected
            labels = sorted({row.label for row in rows})
            colors = {
                label: imgui.ImVec4(
                    *(self._label_colors or {}).get(label, (*PALETTE[i % len(PALETTE)], 1.0))
                )
                for i, label in enumerate(labels)
            }
            active = _FILTER.get(widget_id)
            if active not in labels:
                active = None
            active = _filters(rows, colors, active)
            _FILTER[widget_id] = active
            visible = [row for row in rows if active is None or row.label == active]
            e_max = max((_energy(row) for row in rows), default=0.0) or 1.0
            imgui.push_style_var(imgui.StyleVar_.cell_padding, imgui.ImVec2(ui_px(3), ui_px(4)))
            try:
                if imgui.begin_table(
                    "##templates",
                    5,
                    imgui.TableFlags_.scroll_y,
                    imgui.ImVec2(-1, ui_px(self._height)),
                ):
                    _columns(rows)
                    for row in visible:
                        if _row(row, colors[row.label], e_max, selected):
                            selected = row.key
                            _SELECTED[widget_id] = selected
                    imgui.end_table()
            finally:
                imgui.pop_style_var()
        finally:
            imgui.pop_style_var()
            imgui.pop_id()
        return selected


def clear_selection(widget_id: str) -> None:
    """Drop the cached selection for ``widget_id`` (e.g. after Clear button)."""
    _SELECTED[widget_id] = None


def _fit(text: str, width: float) -> str:
    """Ellipsize a single line using the current font."""
    text = " ".join(text.splitlines())
    if imgui.calc_text_size(text).x <= width:
        return text
    if width < imgui.calc_text_size("…").x:
        return ""
    return _truncate_to_width(text, width - imgui.calc_text_size("…").x) + "…"


def _header(title: str, rows: list[TemplateInspectorRow]) -> None:
    """Keep count and bulk actions beside the title, wrapping when necessary."""
    style = imgui.get_style()
    count = f"{sum(row.accepted for row in rows)} of {len(rows)} kept"
    imgui.push_font(mono_font(), style.font_size_base)
    count_w = imgui.calc_text_size(count).x
    imgui.pop_font()
    actions_w = imgui.calc_text_size("All").x + imgui.calc_text_size("None").x
    actions_w += 4 * style.frame_padding.x + style.item_spacing.x
    detail_w = count_w + style.item_spacing.x + actions_w
    inline = imgui.get_content_region_avail().x >= detail_w + ui_px(110)
    if title:
        panel_header(title, reserve=detail_w + style.item_spacing.x if inline else 0)
        if inline:
            imgui.same_line()
            imgui.set_cursor_pos_x(
                imgui.get_cursor_pos_x() + max(0, imgui.get_content_region_avail().x - detail_w)
            )
    mono_text(count, muted())
    imgui.same_line()
    if imgui.get_content_region_avail().x < actions_w:
        imgui.new_line()
    if imgui.small_button("All##keep_all"):
        for row in rows:
            row.accepted = True
    imgui.same_line()
    if imgui.small_button("None##keep_none"):
        for row in rows:
            row.accepted = False


def _filters(
    rows: list[TemplateInspectorRow], colors: dict[str, imgui.ImVec4], active: str | None
) -> str | None:
    """Wrap gesture-count chips, with a categorical dot and selected cue."""
    style = imgui.get_style()
    width = imgui.get_content_region_avail().x
    right = imgui.get_cursor_screen_pos().x + width
    previous = None
    for label, color in colors.items():
        count = sum(row.label == label for row in rows)
        suffix = f" · {count}"
        budget = width - 2 * style.frame_padding.x - imgui.calc_text_size("   " + suffix).x
        text = "   " + _fit(label, budget) + suffix
        chip_w = imgui.calc_text_size(text).x + 2 * style.frame_padding.x
        if previous is not None and previous + style.item_spacing.x + chip_w <= right:
            imgui.same_line()
        on = label == active
        if on:
            push_selected()
        if imgui.small_button(f"{text}##filter:{label}"):
            active = None if on else label
        if on:
            pop_selected()
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        imgui.get_window_draw_list().add_circle_filled(
            imgui.ImVec2(lo.x + style.frame_padding.x + ui_px(3), (lo.y + hi.y) / 2),
            ui_px(3),
            imgui.get_color_u32(color),
        )
        if imgui.is_item_hovered():
            imgui.set_tooltip(f"{label}: {count} templates. Click again to show all gestures.")
        previous = hi.x
    return active


def _columns(rows: list[TemplateInspectorRow]) -> None:
    """Reserve measured controls, sharing the remaining space among row details."""
    style = imgui.get_style()
    keep_w = imgui.calc_text_size("Kept").x + 2 * style.frame_padding.x
    imgui.push_font(mono_font(), style.font_size_base)
    trial_w = min(ui_px(45), max(imgui.calc_text_size(_trial(row)).x for row in rows))
    imgui.pop_font()
    available = imgui.get_content_region_avail().x - style.scrollbar_size
    remaining = max(ui_px(12), available - keep_w - trial_w - 10 * style.cell_padding.x)
    for name, width in (
        ("Use", keep_w),
        ("Label", remaining * 0.35),
        ("Source", 0),
        ("Energy", min(ui_px(60), remaining * 0.2)),
        ("Trial", trial_w),
    ):
        flags = (
            imgui.TableColumnFlags_.width_stretch
            if name == "Source"
            else imgui.TableColumnFlags_.width_fixed
        )
        imgui.table_setup_column(name, flags, width)


def _trial(row: TemplateInspectorRow) -> str:
    """A trial number with its visible marker, when supplied in the row key."""
    return "#" + row.key.rsplit("#", 1)[1] if "#" in row.key else "—"


def _energy(row: TemplateInspectorRow) -> float:
    """Only finite nonnegative energies contribute to the shared bar scale."""
    return max(0.0, row.energy) if row.energy is not None and isfinite(row.energy) else 0.0


def _row(
    row: TemplateInspectorRow, color: imgui.ImVec4, e_max: float, selected: str | None
) -> bool:
    """Render one compact row; only its source selection changes the preview."""
    imgui.push_id(row.key)
    imgui.table_next_row(min_row_height=ui_px(26))
    if row.key == selected:
        imgui.table_set_bg_color(
            imgui.TableBgTarget_.row_bg0, imgui.get_color_u32(imgui.Col_.text_selected_bg)
        )
    imgui.table_next_column()
    kept = row.accepted
    if kept:
        push_selected()
    if imgui.small_button(f"{'Kept' if kept else 'Out'}##keep"):
        row.accepted = not kept
    if kept:
        pop_selected()
    imgui.table_next_column()
    pos = imgui.get_cursor_screen_pos()
    width = imgui.get_content_region_avail().x
    imgui.get_window_draw_list().add_rect_filled(
        pos,
        imgui.ImVec2(pos.x + width, pos.y + imgui.get_text_line_height()),
        imgui.get_color_u32(imgui.ImVec4(color.x, color.y, color.z, color.w * 0.18)),
        ui_px(3),
    )
    imgui.text_colored(primary(), _fit(row.label, width))
    if imgui.is_item_hovered():
        imgui.set_tooltip(row.label)
    imgui.table_next_column()
    source = row.info_text or row.key
    imgui.push_font(mono_font(), imgui.get_style().font_size_base)
    shown = _fit(source, imgui.get_content_region_avail().x)
    clicked, _ = imgui.selectable(f"{shown}###select", row.key == selected)
    imgui.pop_font()
    if imgui.is_item_hovered():
        imgui.set_tooltip(source)
    imgui.table_next_column()
    if row.energy is not None:
        imgui.set_cursor_pos_y(
            imgui.get_cursor_pos_y() + (imgui.get_text_line_height() - ui_px(3)) / 2
        )
        imgui.progress_bar(
            _energy(row) / e_max,
            imgui.ImVec2(max(ui_px(1), imgui.get_content_region_avail().x), ui_px(3)),
            "",
        )
    else:
        mono_text("—", muted())
    imgui.table_next_column()
    imgui.push_font(mono_font(), imgui.get_style().font_size_base)
    trial = _fit(_trial(row), imgui.get_content_region_avail().x)
    imgui.set_cursor_pos_x(
        imgui.get_cursor_pos_x()
        + max(0, imgui.get_content_region_avail().x - imgui.calc_text_size(trial).x)
    )
    imgui.text_unformatted(trial)
    imgui.pop_font()
    if imgui.is_item_hovered():
        imgui.set_tooltip(_trial(row))
    imgui.pop_id()
    return clicked
