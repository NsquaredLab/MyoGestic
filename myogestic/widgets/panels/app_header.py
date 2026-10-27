"""A shared application header with branding, workflow and session state."""

from __future__ import annotations

from imgui_bundle import hello_imgui, imgui

from myogestic._theme import display_font, mono_font
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
from myogestic.widgets.panels.recording import STATE_COLORS
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
        self,
        title: str,
        *,
        steps: StepBar | None = None,
        participant: ParticipantPanel | None = None,
        show_state: bool = True,
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
        right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
        state = ctx.state.upper()
        pill_w = imgui.calc_text_size(state).x + ui_px(32) if self.show_state else 0
        gap = style.item_spacing.x
        rec = self.show_state and ctx.recording and ctx.state != "recording"
        rec_w = imgui.calc_text_size("REC").x + ui_px(32) + gap if rec else 0
        pill_w += rec_w
        state_w = pill_w + (gap if self.show_state else 0)
        minimum_nav = self.steps._width(done, padding_x=ui_px(4), minimum=True) if self.steps else 0
        logo_budget = imgui.get_content_region_avail().x - state_w - minimum_nav - ui_px(14)
        self._logo(center, logo_budget)
        imgui.same_line(0.0, ui_px(14))
        left = imgui.get_cursor_pos_x()
        available = right - left
        widths = self._widths.setdefault(self._widget_id, {})
        if widths.get("font_size") != imgui.get_font_size() or widths.get("scale") != ui_px(1):
            widths.clear()
            widths.update(font_size=imgui.get_font_size(), scale=ui_px(1))
        font = mono_font() if ctx.participant else None
        if font is not None:
            imgui.push_font(font, style.font_size_base)
        chip_w = (
            (
                imgui.calc_text_size(ctx.participant or "Set participant").x
                + 2 * style.frame_padding.x
            )
            if self.participant
            else 0
        )
        if font is not None:
            imgui.pop_font()
        padding = imgui.ImVec2(style.frame_padding.x, style.frame_padding.y)
        nav_w = self.steps._width(done) if self.steps else 0
        title_w = 2 * gap + ui_px(1) + imgui.calc_text_size(self.title).x
        # The participant yields first, then the title, then navigation padding.
        show_title = self.steps is None or (
            imgui.get_window_size().x >= ui_px(1100) and available >= title_w + nav_w + state_w
        )
        if show_title:
            self._title(
                left - ui_px(14) + gap, center, available - state_w - nav_w - 2 * gap - ui_px(1)
            )
            imgui.same_line(0.0, ui_px(14))
            left = imgui.get_cursor_pos_x()
            available = right - left
        nav_budget = max(0.0, available - state_w)
        if self.steps and nav_budget < nav_w:
            padding.x = ui_px(4)
            nav_w = self.steps._width(done, padding_x=padding.x)
        compact = bool(self.steps and nav_w > nav_budget)
        active = None
        if self.steps:
            imgui.set_cursor_pos(imgui.ImVec2(left, center - imgui.get_frame_height() / 2))
            imgui.push_style_var(imgui.StyleVar_.frame_padding, padding)
            try:
                imgui.begin_group()
                active = self.steps.ui(done, compact=compact, max_width=nav_budget)
                imgui.end_group()
                nav_w = imgui.get_item_rect_size().x
            finally:
                imgui.pop_style_var()
        participant_w = (
            max(
                0.0,
                min(
                    max(chip_w, widths.get("participant", chip_w)),
                    available - nav_w - state_w - gap,
                ),
            )
            if self.participant
            else 0
        )
        if participant_w:
            imgui.set_cursor_pos(
                imgui.ImVec2(
                    right - pill_w - (gap if self.show_state else 0) - participant_w,
                    center - imgui.get_frame_height() / 2,
                )
            )
            imgui.begin_child(
                "participant",
                imgui.ImVec2(participant_w, imgui.get_frame_height()),
                window_flags=(
                    imgui.WindowFlags_.no_background
                    | imgui.WindowFlags_.no_scrollbar
                    | imgui.WindowFlags_.no_scroll_with_mouse
                ),
            )
            try:
                imgui.begin_group()
                self.participant.ui(ctx)
                imgui.end_group()
                widths["participant"] = imgui.get_item_rect_size().x
            finally:
                imgui.end_child()
        if self.show_state:
            imgui.set_cursor_pos(
                imgui.ImVec2(right - pill_w, center - (imgui.get_text_line_height() + ui_px(8)) / 2)
            )
            tone = {"recording": DANGER, "training": WARNING, "predicting": INFO}.get(
                ctx.state, IDLE
            )
            status_pill(state, tone)
            widths[state] = imgui.get_item_rect_size().x
            if rec:
                imgui.same_line()
                status_pill("REC", STATE_COLORS["recording"])
        return active

    def _logo(self, center: float, width: float) -> None:
        """Keep the wordmark visible after navigation has exhausted its fallbacks."""
        height = ui_px(26)
        asset = "myogestic_logo_line.png"
        if hello_imgui.asset_exists(asset):
            size = hello_imgui.image_and_size_from_asset(asset).size
            natural_w = height * size.x / size.y if size.y else height
        else:
            imgui.push_font(display_font(), height / imgui.get_style().font_scale_main)
            natural_w = imgui.calc_text_size("MyoGestic").x
            imgui.pop_font()
        height *= min(1.0, max(1.0, width) / max(1.0, natural_w))
        imgui.set_cursor_pos_y(center - height / 2)
        AppLogo(variant="line", height=height).ui()

    def _title(self, left: float, center: float, width: float) -> None:
        imgui.set_cursor_pos(imgui.ImVec2(left, center - ui_px(20) / 2))
        imgui.dummy(imgui.ImVec2(ui_px(1), ui_px(20)))
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        imgui.get_window_draw_list().add_line(
            lo,
            imgui.ImVec2(lo.x, hi.y),
            imgui.get_color_u32(hairline()),
            thickness=ui_px(1),
        )
        imgui.same_line(0.0, imgui.get_style().item_spacing.x)
        imgui.set_cursor_pos_y(center - imgui.get_text_line_height() / 2)
        imgui.text_colored(muted(), fit_text(self.title, max(0.0, width)))
        if imgui.is_item_hovered():
            imgui.set_tooltip(self.title)
