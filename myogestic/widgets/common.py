"""Shared constants and small visual helpers for widgets."""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui, implot

# 10 distinct colors for class labels (Category10-like)
PALETTE = np.array(
    [
        [0.12, 0.47, 0.71],  # blue
        [1.00, 0.50, 0.05],  # orange
        [0.17, 0.63, 0.17],  # green
        [0.84, 0.15, 0.16],  # red
        [0.58, 0.40, 0.74],  # purple
        [0.55, 0.34, 0.29],  # brown
        [0.89, 0.47, 0.76],  # pink
        [0.50, 0.50, 0.50],  # gray
        [0.74, 0.74, 0.13],  # olive
        [0.09, 0.75, 0.81],  # cyan
    ],
    dtype=np.float32,
)


# Semantic status colours — the single source for good / warn / bad / info /
# idle, so the same status reads as the same colour across every widget
# (Apple system palette). Separate from the accent hue used for chrome.
SUCCESS = imgui.ImVec4(48 / 255, 209 / 255, 88 / 255, 1.0)  # systemGreen
WARNING = imgui.ImVec4(255 / 255, 159 / 255, 10 / 255, 1.0)  # systemOrange
DANGER = imgui.ImVec4(255 / 255, 69 / 255, 58 / 255, 1.0)  # systemRed
INFO = imgui.ImVec4(10 / 255, 132 / 255, 255 / 255, 1.0)  # systemBlue
IDLE = imgui.ImVec4(142 / 255, 142 / 255, 147 / 255, 1.0)  # systemGray


_IMPLOT_STYLED = False


def ensure_implot_style() -> None:
    """Apply the app's plot styling to ImPlot once, lazily.

    Call at the top of any plot widget — ImPlot's global style needs a live
    context, so it's set on the first render. Plots then read as part of the
    app instead of stock ImPlot: no chart border (surface tone frames them), a
    transparent plot background so the card shows through, and a faint grid.
    """
    global _IMPLOT_STYLED
    if _IMPLOT_STYLED:
        return
    _IMPLOT_STYLED = True
    st = implot.get_style()
    st.plot_border_size = 0.0
    st.set_color_(implot.Col_.plot_bg, imgui.ImVec4(0.0, 0.0, 0.0, 0.0))
    st.set_color_(implot.Col_.frame_bg, imgui.ImVec4(0.0, 0.0, 0.0, 0.0))
    st.set_color_(implot.Col_.axis_grid, imgui.ImVec4(1.0, 1.0, 1.0, 0.05))
    st.set_color_(implot.Col_.legend_bg, imgui.ImVec4(0.17, 0.17, 0.18, 0.95))


_ELLIPSIS = "…"

# The one definition of the "this control is the active choice" cue, used for
# *persistent selection* (a momentary press is now neutral gray). Wrap the
# active button:  push_selected(); imgui.button(...); pop_selected().  Keeping
# it here means selection can be restyled app-wide from a single place — e.g.
# to the proposed translucent-accent fill + 2px underline — instead of the five
# hard-coded copies this replaced.
_ACCENT = imgui.ImVec4(0.31, 0.61, 0.98, 1.0)
_SELECTED_FILL = imgui.ImVec4(0.31, 0.61, 0.98, 0.28)  # translucent accent tint (rest)
_SELECTED_HOVER = imgui.ImVec4(0.31, 0.61, 0.98, 0.40)


def push_selected() -> None:
    """Tint the next button as the selected / active choice (pair with :func:`pop_selected`).

    Instead of a solid accent fill, the selected control gets a translucent
    accent *tint* plus a 2px accent underline (drawn in :func:`pop_selected`) —
    a calmer "this is on" cue that reads as selection, not a momentary press.
    """
    imgui.push_style_color(imgui.Col_.button, _SELECTED_FILL)
    imgui.push_style_color(imgui.Col_.button_hovered, _SELECTED_HOVER)
    imgui.push_style_color(imgui.Col_.button_active, _SELECTED_HOVER)


def pop_selected() -> None:
    """Undo the tint pushed by :func:`push_selected` and draw the accent underline."""
    imgui.pop_style_color(3)
    p0 = imgui.get_item_rect_min()
    p1 = imgui.get_item_rect_max()
    y = p1.y - 2.0
    imgui.get_window_draw_list().add_rect_filled(
        imgui.ImVec2(p0.x + 3.0, y), imgui.ImVec2(p1.x - 3.0, p1.y), imgui.get_color_u32(_ACCENT), 1.0
    )


def panel_header(title: str, icon: str | None = None, *, reserve: float = 0.0) -> None:
    """Render a uniform panel-header line: muted, all-caps, optional FA icon.

    Pairs with the button + slider styling used by the other widgets in this
    package. Use it at the top of any custom panel to match the look::

        panel_header("MODEL", icons_fontawesome_6.ICON_FA_BRAIN)
        train_button(pipeline)
        ...

    The text color follows the active theme's ``text_disabled`` slot, so it
    reads correctly on both light and dark themes without hardcoding.

    When the panel is too narrow for the full title, the title is truncated
    with a ``…`` ellipsis; when there is no room for any label, only the icon
    is shown. Pass ``reserve`` to leave that many pixels for controls placed
    after the header on the same row (e.g. a right-aligned button), so the
    *title* collapses instead of pushing those controls off the panel.
    """
    muted = imgui.get_style().color_(imgui.Col_.text_disabled)
    imgui.push_style_color(imgui.Col_.text, muted)
    imgui.text(_fit_header(title.upper(), icon, reserve))
    imgui.pop_style_color()


def _fit_header(label: str, icon: str | None, reserve: float) -> str:
    """Fit ``icon + label`` into the available width.

    Returns the full string if it fits; otherwise the label truncated with an
    ellipsis; otherwise (too narrow for any label) just the icon.
    """
    avail = imgui.get_content_region_avail().x - reserve
    prefix = f"{icon}  " if icon else ""
    if imgui.calc_text_size(prefix + label).x <= avail:
        return prefix + label
    if icon is not None and imgui.calc_text_size(f"{icon}  {label[:1]}{_ELLIPSIS}").x > avail:
        return icon
    budget = avail - imgui.calc_text_size(prefix + _ELLIPSIS).x
    return prefix + _truncate_to_width(label, budget) + _ELLIPSIS


def _truncate_to_width(s: str, budget: float) -> str:
    """Longest prefix of ``s`` whose rendered width fits ``budget`` pixels."""
    if budget <= 0:
        return ""
    while s and imgui.calc_text_size(s).x > budget:
        s = s[:-1]
    return s


def panel_header_button(title: str, icon: str | None, button_icon: str, *, tooltip: str = "") -> bool:
    """Render a :func:`panel_header` with a right-aligned icon-only button.

    Returns ``True`` on the frame the button is clicked. The button is
    prioritized: when the row can't fit the header icon + button side by side
    it drops to its own line below the (icon-only) header — the same behaviour
    as the Reset button on the post-processing panel.
    """
    style = imgui.get_style()
    sp = style.item_spacing.x
    btn_w = imgui.calc_text_size(button_icon).x + style.frame_padding.x * 2
    icon_w = imgui.calc_text_size(icon).x if icon else 0.0
    inline = imgui.get_content_region_avail().x >= icon_w + sp + btn_w
    panel_header(title, icon, reserve=(btn_w + sp) if inline else 0.0)
    if inline:
        imgui.same_line()
        avail = imgui.get_content_region_avail().x
        if avail > btn_w:
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + (avail - btn_w))
    # else: the button renders on the next line (no same_line), left-aligned.
    clicked = imgui.small_button(f"{button_icon}##_panel_hdr_btn")
    if tooltip and imgui.is_item_hovered():
        imgui.set_tooltip(tooltip)
    return clicked
