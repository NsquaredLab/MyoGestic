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


def panel_header(title: str, icon: str | None = None) -> None:
    """Render a uniform panel-header line: muted, all-caps, optional FA icon.

    Pairs with the button-button + slider styling used by the other widgets in
    this package. Use it at the top of any custom panel to match the look::

        panel_header("MODEL", icons_fontawesome_6.ICON_FA_BRAIN)
        train_button(pipeline)
        ...

    The text color follows the active theme's ``text_disabled`` slot, so it
    reads correctly on both light and dark themes without hardcoding.
    """
    muted = imgui.get_style().color_(imgui.Col_.text_disabled)
    imgui.push_style_color(imgui.Col_.text, muted)
    imgui.text(f"{icon}  {title.upper()}" if icon else title.upper())
    imgui.pop_style_color()
