"""Shared log-rendering primitives.

Consumed by both ``process_launcher`` (subprocess stdout) and
``pipeline_panel`` (ML training log) so the autoscroll + popout + tooltip
UX stays identical across the framework. Three thin functions:

* :func:`render_log` — scrollable child window with smart autoscroll.
* :func:`render_log_buttons` — autoscroll + popout toggle buttons (returns
  the updated state to the caller — the panel owns the state, not us).
* :func:`render_log_popout` — floating ``Begin``/``End`` window mirroring
  the inline log, returns whether the user has closed the popout.
"""

from __future__ import annotations

from collections.abc import Sequence

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic._theme import mono_font

# A sunken dark "console" surface with light mono text — reads as program
# output in both light and dark themes (terminals stay dark on a light UI).
_CONSOLE_BG = imgui.ImVec4(0.075, 0.078, 0.086, 1.0)
_CONSOLE_TEXT = imgui.ImVec4(0.88, 0.89, 0.91, 1.0)


def render_log(
    widget_id: str,
    lines: Sequence[str],
    *,
    height: float = -1.0,
    autoscroll: bool = True,
) -> None:
    """Render ``lines`` as a scrollable child window with smart autoscroll.

    Smart autoscroll: only snaps to the bottom when the user is **already**
    at (or within 1 px of) the bottom — scrolling up to inspect older
    lines pauses the auto-follow until the user scrolls back down. This
    means the autoscroll button toggles the *default* behavior; the user
    can always opt out for a frame by scrolling up.

    Parameters
    ----------
    widget_id
        Unique per-panel ID for the child window's ImGui label.
    lines
        Any sequence — list, tuple, deque, anything iterable. Caller
        is responsible for thread-safe access; we snapshot under the
        GIL via ``list(lines)`` to dodge concurrent-mutation issues
        with deques/lists appended to from a worker thread.
    height
        Pixel height of the log box. ``-1`` (default) fills the
        remaining vertical space of the parent.
    autoscroll
        Stick-to-bottom toggle (typically wired to a button
        elsewhere on the parent panel).
    """
    imgui.push_style_color(imgui.Col_.child_bg, _CONSOLE_BG)
    imgui.push_style_color(imgui.Col_.text, _CONSOLE_TEXT)
    imgui.begin_child(
        f"##{widget_id}_log_child",
        imgui.ImVec2(-1, height),
        child_flags=imgui.ChildFlags_.borders,
        window_flags=imgui.WindowFlags_.horizontal_scrollbar,
    )
    font = mono_font()
    if font is not None:
        imgui.push_font(font, imgui.get_font_size())
    for line in list(lines):
        imgui.text_unformatted(line)
    if font is not None:
        imgui.pop_font()
    if autoscroll and imgui.get_scroll_y() >= imgui.get_scroll_max_y() - 1:
        imgui.set_scroll_here_y(1.0)
    imgui.end_child()
    imgui.pop_style_color(2)


def render_log_buttons(
    widget_id: str,
    *,
    autoscroll: bool,
    popped_out: bool,
) -> tuple[bool, bool]:
    """Render the autoscroll + popout toggle buttons.

    Returns the (possibly updated) ``(autoscroll, popped_out)`` state to
    be persisted by the caller. Visual: double-chevron-down = autoscroll
    ON; single arrow = OFF. Box-out icon = "pop out"; box-in icon = "dock
    back inline".
    """
    icon = fa.ICON_FA_ANGLES_DOWN if autoscroll else fa.ICON_FA_ARROW_DOWN
    if imgui.button(f"{icon}##{widget_id}_autoscroll"):
        autoscroll = not autoscroll
    imgui.set_item_tooltip(
        "Autoscroll ON — log sticks to the bottom as new lines arrive "
        "(pauses when you scroll up to inspect older lines)."
        if autoscroll
        else "Autoscroll OFF — log stays where you scrolled."
    )

    imgui.same_line()
    icon = (
        fa.ICON_FA_DOWN_LEFT_AND_UP_RIGHT_TO_CENTER
        if popped_out
        else fa.ICON_FA_UP_RIGHT_AND_DOWN_LEFT_FROM_CENTER
    )
    if imgui.button(f"{icon}##{widget_id}_popout"):
        popped_out = not popped_out
    imgui.set_item_tooltip(
        "Dock the log back inline" if popped_out else "Pop the log out into a floating window"
    )
    return autoscroll, popped_out


def render_log_popout(
    widget_id: str,
    lines: Sequence[str],
    *,
    title: str,
    autoscroll: bool,
) -> bool:
    """Render the floating popout window.

    Returns ``False`` once the user clicks the window's ``[x]`` (so the
    caller can re-dock the log inline).
    """
    imgui.set_next_window_size(imgui.ImVec2(640, 320), imgui.Cond_.first_use_ever)
    visible, still_open = imgui.begin(f"{title}##{widget_id}_popout_window", True)
    try:
        if visible:
            render_log(f"{widget_id}_pop", lines, height=-1.0, autoscroll=autoscroll)
    finally:
        imgui.end()
    # imgui.begin types still_open as bool | None, but passing p_open=True
    # guarantees a bool at runtime; coerce to satisfy the bool return type.
    return bool(still_open)


__all__ = ["render_log", "render_log_buttons", "render_log_popout"]
