"""Clickable workflow steps with independent selection and completion cues."""

from __future__ import annotations

import math

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import SUCCESS, fit_text, hairline, pop_selected, push_selected, ui_px

__all__ = ["StepBar"]

_active_steps: dict[str, int] = {}


def _connector(done: bool, top: float, width: float) -> None:
    """Join consecutive steps, carrying the completion cue from the left."""
    spacing = min(ui_px(4), width / 2)
    if width == 0:
        imgui.same_line(0.0, 0.0)
        imgui.set_cursor_pos_y(top)
        return
    imgui.same_line(0.0, spacing)
    imgui.set_cursor_pos_y(top)
    imgui.dummy(imgui.ImVec2(width - 2 * spacing, imgui.get_frame_height()))
    lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    color = imgui.ImVec4(SUCCESS.x, SUCCESS.y, SUCCESS.z, SUCCESS.w * 0.45) if done else hairline()
    y = (lo.y + hi.y) / 2
    imgui.get_window_draw_list().add_line(
        imgui.ImVec2(lo.x, y), imgui.ImVec2(hi.x, y), imgui.get_color_u32(color), thickness=ui_px(1)
    )
    imgui.same_line(0.0, spacing)
    imgui.set_cursor_pos_y(top)


def _content_width(index: int, label: str, done: bool) -> float:
    """Measure the exact glyphs and text runs used by a step button."""
    suffix = f"  {label}" if label else ""
    if not done:
        return imgui.calc_text_size(f"{index + 1}{suffix}").x
    return (imgui.calc_text_size(fa.ICON_FA_CHECK).x
            + (imgui.calc_text_size("  ").x + imgui.calc_text_size(label).x if label else 0))


def _step_button(index: int, label: str, done: bool) -> bool:
    """Draw one button, colouring only the completion check when present."""
    suffix = f"  {label}" if label else ""
    if not done:
        return imgui.button(f"{index + 1}{suffix}###step{index}")

    padding = imgui.get_style().frame_padding
    size = imgui.ImVec2(
        _content_width(index, label, done) + 2 * padding.x, imgui.get_frame_height()
    )
    # Keep the real button's hit box and layout, then put the two text tones
    # inside it. The group retains the whole button rect for same_line and
    # pop_selected, even though the label is the last item submitted.
    imgui.begin_group()
    clicked = imgui.button(f"###step{index}", size)
    origin = imgui.get_item_rect_min()
    imgui.set_cursor_screen_pos(imgui.ImVec2(origin.x + padding.x, origin.y + padding.y))
    imgui.text_colored(SUCCESS, fa.ICON_FA_CHECK)
    if label:
        imgui.same_line(0.0, imgui.calc_text_size("  ").x)
        imgui.text_unformatted(label)
    imgui.end_group()
    return clicked


class StepBar:
    """Navigate a workflow without restricting which step can be opened.

    Parameters
    ----------
    steps : list[str]
        Labels in workflow order. Supply at least one step.
    widget_id : str, optional
        Stable selection and ImGui identity, by default ``"steps"``. Use
        different IDs for independently selectable bars, even with the same labels.

    Attributes
    ----------
    steps : list[str]
        Labels in workflow order.
    active : int
        Selected zero-based index, initially zero, stored by ``widget_id``.
    """

    def __init__(self, steps: list[str], *, widget_id: str = "steps") -> None:
        if not steps:
            raise ValueError("Pass at least one label in steps.")
        self.steps = list(steps)
        self._widget_id = widget_id

    @property
    def active(self) -> int:
        """Selected index for this widget identity."""
        return min(_active_steps.get(self._widget_id, 0), len(self.steps) - 1)

    @active.setter
    def active(self, index: int) -> None:
        if not 0 <= index < len(self.steps):
            raise ValueError("Set active to an index within steps.")
        _active_steps[self._widget_id] = index

    def _labels(self, compact: bool) -> list[str]:
        return [label if not compact or i == self.active else ""
                for i, label in enumerate(self.steps)]

    def _width(self, done: list[bool], *, compact: bool = False,
               padding_x: float | None = None, minimum: bool = False) -> float:
        """Measure navigation using the same text runs as the rendered buttons."""
        labels = self._labels(compact)
        if minimum:
            labels = ["…" if i == self.active else "" for i in range(len(self.steps))]
        padding = imgui.get_style().frame_padding.x if padding_x is None else padding_x
        return (sum(_content_width(i, label, complete)
                    for i, (label, complete) in enumerate(zip(labels, done, strict=True)))
                + len(labels) * 2 * padding + (0 if minimum else (len(labels) - 1) * ui_px(32)))

    def ui(self, done: list[bool], *, compact: bool = False,
           max_width: float | None = None) -> int:
        """Draw the steps and return the selected index.

        Parameters
        ----------
        done : list[bool]
            One completion flag per step. Completed steps show a green check;
            every step remains clickable regardless of these flags.
        compact : bool, optional
            Label only the active step; inactive steps show their number or
            checkmark with the full label on hover. By default False.
        max_width : float or None, optional
            Compact row budget in pixels. Connectors contract first, then the
            active label ellipsizes, with its full text on hover. The budget must
            fit the padded step marks and an active ellipsis. None leaves the
            row unconstrained.

        Returns
        -------
        int
            Active zero-based index, including a selection made this frame.

        Raises
        ------
        ValueError
            If ``done`` and ``steps`` have different lengths.
        """
        if len(done) != len(self.steps):
            raise ValueError("Pass one done flag per step: len(done) must equal len(steps).")
        labels = self._labels(compact)
        connector_w = ui_px(32)
        if compact and max_width is not None:
            natural_w = self._width(done, compact=True)
            if len(labels) > 1:
                connector_w = max(0, math.floor(
                    ui_px(32) - max(0, natural_w - max_width) / (len(labels) - 1),
                ))
            excess = natural_w - (len(labels) - 1) * (ui_px(32) - connector_w) - max_width
            if excess > 0:
                label = labels[self.active]
                labels[self.active] = fit_text(label, max(0, imgui.calc_text_size(label).x - excess))
        # Keep this frame's labels stable even if a click changes the selection.
        active = self.active
        imgui.push_id(self._widget_id)
        # A caller may centre us beside taller text on an existing line.
        # same_line restores that line's top, so connectors explicitly retain
        # the first step's top for every item in the navigation row.
        top = imgui.get_cursor_pos_y()
        try:
            for index, (label, complete) in enumerate(zip(self.steps, done, strict=True)):
                if index:
                    _connector(done[index - 1], top, connector_w)
                selected = index == active
                if selected:
                    push_selected()
                if _step_button(index, labels[index], complete):
                    self.active = index
                if selected:
                    pop_selected()
                if labels[index] != label and imgui.is_item_hovered():
                    imgui.set_tooltip(label)
        finally:
            imgui.pop_id()
        return self.active
