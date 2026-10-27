"""Corner notifications rendered automatically by the App."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import DANGER, INFO, SUCCESS, WARNING, hairline, muted, ui_px

if TYPE_CHECKING:
    from myogestic.core import Context

_LIFETIMES: dict[str, float | None] = {
    "success": 6.0,
    "info": 6.0,
    "warning": 10.0,
    "danger": None,
}
_TONES = {"success": SUCCESS, "info": INFO, "warning": WARNING, "danger": DANGER}


@dataclass(eq=False)
class Notification:
    """One app event, with a monotonic clock adjusted while the overlay is hovered.

    Parameters
    ----------
    title
        Short description of the event.
    detail
        Supporting text displayed below the title.
    kind
        One of ``"success"``, ``"info"``, ``"warning"``, or ``"danger"``.
    created
        Monotonic creation time in seconds; the UI shifts it to pause expiry.
    """

    title: str
    detail: str
    kind: str
    created: float

    def __post_init__(self) -> None:
        if self.kind not in _LIFETIMES:
            raise ValueError("Notification kind must be 'success', 'info', 'warning', or 'danger'.")


def _draw_notification(notification: Notification) -> bool:
    """Draw one toast and return whether its dismiss button was clicked."""
    imgui.push_id(str(id(notification)))
    style = imgui.get_style()
    start = imgui.get_cursor_pos()
    right = start.x + imgui.get_content_region_avail().x
    button_width = imgui.calc_text_size(fa.ICON_FA_XMARK).x + 2 * style.frame_padding.x
    imgui.set_cursor_pos_x(right - button_width)
    dismissed = imgui.small_button(fa.ICON_FA_XMARK)
    imgui.set_cursor_pos(start)

    radius = ui_px(4)
    pos = imgui.get_cursor_screen_pos()
    imgui.get_window_draw_list().add_circle_filled(
        imgui.ImVec2(pos.x + radius, pos.y + imgui.get_frame_height() / 2),
        radius,
        imgui.get_color_u32(_TONES[notification.kind]),
    )
    imgui.dummy(imgui.ImVec2(radius * 2, imgui.get_frame_height()))
    imgui.same_line()
    imgui.align_text_to_frame_padding()
    imgui.push_text_wrap_pos(right - button_width - style.item_spacing.x)
    imgui.text_unformatted(notification.title)
    imgui.pop_text_wrap_pos()
    if notification.detail:
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.push_text_wrap_pos(right)
        imgui.text_unformatted(notification.detail)
        imgui.pop_text_wrap_pos()
        imgui.pop_style_color()
    imgui.pop_id()
    return dismissed


def render_notifications(ctx: Context) -> None:
    """Draw up to three toasts at the main viewport's bottom-right corner.

    Parameters
    ----------
    ctx
        Shared context. Only the UI thread prunes its notification list;
        workers may append to it even while this snapshot is being drawn.
    """
    snapshot = list(ctx.notifications)
    if not snapshot:
        return
    # Remove individual objects, never replace the live list with the snapshot:
    # a worker may have appended after the snapshot was taken. Identity equality
    # also keeps two otherwise identical notifications independently dismissible.
    for notification in snapshot[:-3]:
        ctx.notifications.remove(notification)
    visible = snapshot[-3:]

    viewport = imgui.get_main_viewport()
    margin = ui_px(18)
    width = ui_px(372)
    imgui.set_next_window_viewport(viewport.id_)
    imgui.set_next_window_pos(
        imgui.ImVec2(
            viewport.work_pos.x + viewport.work_size.x - margin,
            viewport.work_pos.y + viewport.work_size.y - margin,
        ),
        pivot=imgui.ImVec2(1, 1),
    )
    imgui.set_next_window_size(imgui.ImVec2(width, 0))
    imgui.set_next_window_size_constraints(
        imgui.ImVec2(width, 0), imgui.ImVec2(width, float("inf"))
    )
    flags = (
        imgui.WindowFlags_.no_decoration
        | imgui.WindowFlags_.no_focus_on_appearing
        | imgui.WindowFlags_.no_nav
        | imgui.WindowFlags_.no_saved_settings
        | imgui.WindowFlags_.no_docking
        | imgui.WindowFlags_.always_auto_resize
    )
    imgui.push_style_color(imgui.Col_.window_bg, imgui.get_style().color_(imgui.Col_.popup_bg))
    imgui.push_style_color(imgui.Col_.border, hairline())
    # A hairline stays one pixel: ui_px(1) rounds to no border at all below scale 1.0.
    imgui.push_style_var(imgui.StyleVar_.window_border_size, 1.0)
    expanded, _ = imgui.begin(f"##notifications-{id(ctx)}", flags=flags)
    if expanded:
        now = time.monotonic()
        paused = imgui.get_io().delta_time if imgui.is_window_hovered() else 0.0
        drawn = 0
        for notification in visible:
            notification.created += min(paused, max(0.0, now - notification.created))
            lifetime = _LIFETIMES[notification.kind]
            if lifetime is not None and now - notification.created >= lifetime:
                ctx.notifications.remove(notification)
                continue
            if drawn:
                imgui.separator()
            if _draw_notification(notification):
                ctx.notifications.remove(notification)
            drawn += 1
    imgui.end()
    imgui.pop_style_var()
    imgui.pop_style_color(2)
