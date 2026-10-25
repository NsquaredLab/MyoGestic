"""A shared application header with branding, workflow and session state."""

from __future__ import annotations

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic._theme import mono_font
from myogestic.core import Context
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    INFO,
    WARNING,
    edge_rule,
    fit_text,
    hairline,
    muted,
    status_pill,
    ui_px,
)
from myogestic.widgets.panels.app_logo import AppLogo
from myogestic.widgets.panels.participant import ParticipantPanel
from myogestic.widgets.panels.step_bar import StepBar

__all__ = ["AppHeader"]


class AppHeader:
    """Lead an app with its logo, title, optional workflow and session state.

    Parameters
    ----------
    title : str
        Muted application title. Without steps, long titles ellipsize and show
        their full text on hover; with steps, the title yields to navigation.
    steps : StepBar or None, optional
        Workflow navigation, by default absent.
    participant : ParticipantPanel or None, optional
        Participant selector, by default absent. Its chip yields to the state.
    show_state : bool, optional
        Show the context's state at the right edge, by default True.
    widget_id : str, optional
        Stable ImGui and instance-local measurement identity, by default
        ``"app_header"``. Use distinct IDs for headers in the same window.

    Notes
    -----
    Place in a bare ``Px(52)`` Grid row. No caller style pushes are needed.
    """

    def __init__(
        self, title: str, *, steps: StepBar | None = None,
        participant: ParticipantPanel | None = None, show_state: bool = True,
        widget_id: str = "app_header",
    ) -> None:
        self.title = title
        self.steps = steps
        self.participant = participant
        self.show_state = show_state
        self._widget_id = widget_id
        self._widths: dict[str, dict[str, float]] = {}

    def ui(self, ctx: Context, done: list[bool] | None = None) -> int | None:
        """Draw the header and return the active step, or None without steps.

        Parameters
        ----------
        ctx : Context
            Live participant and application state.
        done : list[bool] or None, optional
            One completion flag per step. None marks all steps incomplete.
            Ignored when no StepBar was supplied.

        Returns
        -------
        int or None
            The active step, including a click made this frame, or None.
        """
        flags = [False] * len(self.steps.steps) if self.steps and done is None else done
        if self.steps and len(flags) != len(self.steps.steps):
            raise ValueError("Pass one done flag per step: len(done) must equal len(steps).")
        imgui.push_id(self._widget_id)
        try:
            return self._draw(ctx, flags)
        finally:
            imgui.pop_id()

    def _draw(self, ctx: Context, done: list[bool] | None) -> int | None:
        edge_rule(bottom=True)
        style = imgui.get_style()
        center = imgui.get_cursor_pos_y() + imgui.get_content_region_avail().y / 2
        imgui.set_cursor_pos_y(center - ui_px(26) / 2)
        AppLogo(variant="line", height=ui_px(26)).ui()
        imgui.same_line(0.0, ui_px(14))
        left = imgui.get_cursor_pos_x()
        available = imgui.get_content_region_avail().x
        right = left + available
        widths = self._widths.setdefault(self._widget_id, {})
        if widths.get("font_size") != imgui.get_font_size() or widths.get("scale") != ui_px(1):
            widths.clear()
            widths.update(font_size=imgui.get_font_size(), scale=ui_px(1))
        state = ctx.state.upper()
        pill_w = widths.get(state, imgui.calc_text_size(state).x + ui_px(40)) if self.show_state else 0
        gap = style.item_spacing.x
        font = mono_font() if ctx.participant else None
        if font is not None:
            imgui.push_font(font, style.font_size_base)
        chip_w = (imgui.calc_text_size(ctx.participant or "Set participant").x
                  + 2 * style.frame_padding.x) if self.participant else 0
        if font is not None:
            imgui.pop_font()
        right_w = chip_w + pill_w + gap * (bool(chip_w) + bool(pill_w))
        padding = imgui.ImVec2(style.frame_padding.x, style.frame_padding.y)
        labels_w = sum(
            imgui.calc_text_size(f"{fa.ICON_FA_CHECK if complete else i + 1}  {label}").x
            for i, (label, complete) in enumerate(zip(self.steps.steps, done, strict=True))
        ) + (len(self.steps.steps) - 1) * ui_px(32) if self.steps else 0
        nav_w = labels_w + len(self.steps.steps) * 2 * padding.x if self.steps else 0
        title_w = 2 * gap + ui_px(1) + imgui.calc_text_size(self.title).x
        show_title = self.steps is None or (
            imgui.get_window_size().x >= ui_px(1100) and available >= title_w + nav_w + right_w
        )
        if show_title:
            self._title(left - ui_px(14) + gap, center, available - right_w - 2 * gap - ui_px(1))
            imgui.same_line(0.0, ui_px(14))
            left = imgui.get_cursor_pos_x()
            available = right - left
        if self.steps and available < nav_w + right_w:
            padding.x = ui_px(4)
            nav_w = labels_w + len(self.steps.steps) * 2 * padding.x
        compact = bool(self.steps and nav_w + pill_w + gap > available)
        if compact:
            nav_w -= sum(
                imgui.calc_text_size(f"  {label}").x
                for i, label in enumerate(self.steps.steps) if i != self.steps.active
            )
        active = None
        if self.steps:
            imgui.set_cursor_pos(imgui.ImVec2(left, center - imgui.get_frame_height() / 2))
            imgui.push_style_var(imgui.StyleVar_.frame_padding, padding)
            try:
                active = self.steps.ui(done, compact=True) if compact else self.steps.ui(done)
            finally:
                imgui.pop_style_var()
        participant_w = max(0.0, min(
            max(chip_w, widths.get("participant", chip_w)), available - nav_w - pill_w - 2 * gap,
        )) if self.participant else 0
        if participant_w:
            imgui.set_cursor_pos(imgui.ImVec2(
                right - pill_w - (gap if self.show_state else 0) - participant_w,
                center - imgui.get_frame_height() / 2,
            ))
            imgui.begin_child("participant", imgui.ImVec2(participant_w, imgui.get_frame_height()),
                              window_flags=(imgui.WindowFlags_.no_background
                                            | imgui.WindowFlags_.no_scrollbar
                                            | imgui.WindowFlags_.no_scroll_with_mouse))
            try:
                imgui.begin_group()
                self.participant.ui(ctx)
                imgui.end_group()
                widths["participant"] = imgui.get_item_rect_size().x
            finally:
                imgui.end_child()
        if self.show_state:
            imgui.set_cursor_pos(imgui.ImVec2(right - pill_w, center - (imgui.get_text_line_height() + ui_px(8)) / 2))
            tone = {"recording": DANGER, "training": WARNING, "predicting": INFO}.get(ctx.state, IDLE)
            status_pill(state, tone)
            widths[state] = imgui.get_item_rect_size().x
        return active

    def _title(self, left: float, center: float, width: float) -> None:
        imgui.set_cursor_pos(imgui.ImVec2(left, center - ui_px(20) / 2))
        imgui.dummy(imgui.ImVec2(ui_px(1), ui_px(20)))
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        imgui.get_window_draw_list().add_line(
            lo, imgui.ImVec2(lo.x, hi.y), imgui.get_color_u32(hairline()), thickness=ui_px(1),
        )
        imgui.same_line(0.0, imgui.get_style().item_spacing.x)
        imgui.set_cursor_pos_y(center - imgui.get_text_line_height() / 2)
        imgui.text_colored(muted(), fit_text(self.title, max(0.0, width)))
        if imgui.is_item_hovered():
            imgui.set_tooltip(self.title)
