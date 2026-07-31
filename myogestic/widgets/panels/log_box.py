"""Shared log-rendering primitives.

Consumed by both ``process_launcher`` (subprocess stdout) and
``pipeline_panel`` (ML training log) so the popout + tooltip
UX stays identical across the framework. Three thin functions:

* [`render_log`][] — selectable, read-only console text box (mono, dark).
* [`render_log_buttons`][] — popout toggle button (returns
  the updated state to the caller — the panel owns the state, not us).
* [`render_log_popout`][] — floating ``Begin``/``End`` window mirroring
  the inline log, returns whether the user has closed the popout.
"""

from __future__ import annotations

from collections.abc import Sequence

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic._theme import mono_font
from myogestic.widgets.common import CONSOLE_BG, CONSOLE_TEXT


def render_log(
    widget_id: str,
    lines: Sequence[str],
    *,
    height: float = -1.0,
) -> None:
    """Render ``lines`` as a scrollable, read-only text box.

    Uses a read-only ``input_text_multiline`` — the same widget
    [`log_panel`][myogestic.widgets.panels.log_panel.log_panel] uses — so the log
    text can be **selected and copied** (Ctrl/Cmd+C). The previous renderer
    drew each line with ``imgui.text_unformatted``, which paints static
    glyphs that cannot be selected, so log text could not be copied out.

    Parameters
    ----------
    widget_id
        Unique per-panel ID for the box's ImGui label.
    lines
        Any sequence — list, tuple, deque, anything iterable. Caller
        is responsible for thread-safe access; we snapshot under the
        GIL via ``list(lines)`` to dodge concurrent-mutation issues
        with deques/lists appended to from a worker thread.
    height
        Pixel height of the box. ``-1`` (default) fills the
        remaining vertical space of the parent.
    """
    text = "\n".join(list(lines))
    h = height if height > 0 else -1.0
    # Console styling on the selectable read-only box: a sunken dark surface
    # (its frame bg) + light monospace text, in both themes.
    imgui.push_style_color(imgui.Col_.frame_bg, CONSOLE_BG)
    imgui.push_style_color(imgui.Col_.text, CONSOLE_TEXT)
    font = mono_font()
    if font is not None:
        imgui.push_font(font, imgui.get_font_size())
    imgui.input_text_multiline(
        f"##{widget_id}_log",
        text,
        imgui.ImVec2(-1, h),
        flags=imgui.InputTextFlags_.read_only,
    )
    if font is not None:
        imgui.pop_font()
    imgui.pop_style_color(2)


def render_log_buttons(
    widget_id: str,
    *,
    popped_out: bool,
) -> bool:
    """Render the popout toggle button.

    Returns the (possibly updated) ``popped_out`` state to be persisted by the
    caller. Box-out icon = "pop out"; box-in icon = "dock back inline".

    There was an autoscroll toggle beside it. It set a flag that `render_log`
    deleted on arrival — the read-only box scrolls natively — so the button
    changed its own icon and a tooltip claiming the log would stick to the
    bottom, and nothing else.
    """
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
    return popped_out


def render_log_popout(
    widget_id: str,
    lines: Sequence[str],
    *,
    title: str,
) -> bool:
    """Render the floating popout window.

    Returns ``False`` once the user clicks the window's ``[x]`` (so the
    caller can re-dock the log inline).
    """
    imgui.set_next_window_size(imgui.ImVec2(640, 320), imgui.Cond_.first_use_ever)
    visible, still_open = imgui.begin(f"{title}##{widget_id}_popout_window", True)
    try:
        if visible:
            render_log(f"{widget_id}_pop", lines, height=-1.0)
    finally:
        imgui.end()
    # imgui.begin types still_open as bool | None, but passing p_open=True
    # guarantees a bool at runtime; coerce to satisfy the bool return type.
    return bool(still_open)


__all__ = ["render_log", "render_log_buttons", "render_log_popout"]
