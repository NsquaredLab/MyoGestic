"""Clickable workflow steps with independent selection and completion cues."""

from __future__ import annotations

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import SUCCESS, pop_selected, push_selected, ui_px

__all__ = ["StepBar"]

_active_steps: dict[str, int] = {}


def _step_button(index: int, label: str, done: bool) -> bool:
    """Draw one button, colouring only the completion check when present."""
    if not done:
        return imgui.button(f"{index + 1}  {label}###step{index}")

    padding = imgui.get_style().frame_padding
    content = f"{fa.ICON_FA_CHECK}  {label}"
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

    def ui(self, done: list[bool]) -> int:
        """Draw the steps and return the selected index.

        Parameters
        ----------
        done : list[bool]
            One completion flag per step. Completed steps show a green check;
            every step remains clickable regardless of these flags.

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
        try:
            for index, (label, complete) in enumerate(zip(self.steps, done, strict=True)):
                if index:
                    imgui.same_line(0.0, ui_px(4))
                selected = index == self.active
                if selected:
                    push_selected()
                if _step_button(index, label, complete):
                    self.active = index
                if selected:
                    pop_selected()
        finally:
            imgui.pop_id()
        return self.active
