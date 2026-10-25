"""Clickable workflow steps with independent selection and completion cues."""

from __future__ import annotations

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import SUCCESS, hairline, pop_selected, push_selected, ui_px

__all__ = ["StepBar"]

_active_steps: dict[str, int] = {}


def _connector(done: bool, top: float) -> None:
    """Join consecutive steps, carrying the completion cue from the left."""
    imgui.same_line(0.0, ui_px(4))
    imgui.set_cursor_pos_y(top)
    imgui.dummy(imgui.ImVec2(ui_px(24), imgui.get_frame_height()))
    lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    color = imgui.ImVec4(SUCCESS.x, SUCCESS.y, SUCCESS.z, SUCCESS.w * 0.45) if done else hairline()
    y = (lo.y + hi.y) / 2
    imgui.get_window_draw_list().add_line(
        imgui.ImVec2(lo.x, y), imgui.ImVec2(hi.x, y), imgui.get_color_u32(color), thickness=ui_px(1)
    )
    imgui.same_line(0.0, ui_px(4))
    imgui.set_cursor_pos_y(top)


def _step_button(index: int, label: str, done: bool) -> bool:
    """Draw one button, colouring only the completion check when present."""
    suffix = f"  {label}" if label else ""
    if not done:
        return imgui.button(f"{index + 1}{suffix}###step{index}")

    padding = imgui.get_style().frame_padding
    content = f"{fa.ICON_FA_CHECK}{suffix}"
    size = imgui.ImVec2(
        imgui.calc_text_size(content).x + 2 * padding.x, imgui.get_frame_height()
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

    def ui(self, done: list[bool], *, compact: bool = False) -> int:
        """Draw the steps and return the selected index.

        Parameters
        ----------
        done : list[bool]
            One completion flag per step. Completed steps show a green check;
            every step remains clickable regardless of these flags.
        compact : bool, optional
            Label only the active step; inactive steps show their number or
            checkmark with the full label on hover. By default False.

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
        imgui.push_id(self._widget_id)
        # A caller may centre us beside taller text on an existing line.
        # same_line restores that line's top, so connectors explicitly retain
        # the first step's top for every item in the navigation row.
        top = imgui.get_cursor_pos_y()
        try:
            for index, (label, complete) in enumerate(zip(self.steps, done, strict=True)):
                if index:
                    _connector(done[index - 1], top)
                selected = index == self.active
                if selected:
                    push_selected()
                if _step_button(index, "" if compact and not selected else label, complete):
                    self.active = index
                if selected:
                    pop_selected()
                if compact and not selected and imgui.is_item_hovered():
                    imgui.set_tooltip(label)
        finally:
            imgui.pop_id()
        return self.active
