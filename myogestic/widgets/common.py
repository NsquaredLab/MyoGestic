"""Shared constants and small visual helpers for widgets."""

from __future__ import annotations

import numpy as np
from imgui_bundle import imgui

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


_ELLIPSIS = "…"


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
