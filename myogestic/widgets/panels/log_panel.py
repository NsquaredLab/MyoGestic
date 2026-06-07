"""General app-event log panel for @app.ui.

Displays whatever lines have been pushed via ``ctx.log(...)``. Independent
from ``pipeline.train_log`` (model-training only) — this is for high-level
app events (recording saved, model loaded, stream reconnected, process
crashed). The widget is read-only and auto-scrolls to the latest line when
the user is already pinned to the bottom.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import panel_header

if TYPE_CHECKING:
    from myogestic.core import Context


def log_panel(
    ctx: Context,
    height: float = -1.0,
    title: str = "App Log",
    show_header: bool = True,
) -> None:
    """Render the app log as a scrollable, read-only panel.

    Parameters
    ----------
    ctx
        App context; reads from ``ctx.logs``.
    height
        Panel height in pixels. Pass a value ``<= 0`` (default) to
        fill the remaining vertical space of the parent cell — matches
        the ImGui convention where ``-1`` means "fill available".
    title
        Header label (only shown when ``show_header=True``).
    show_header
        Render the button-style ``panel_header`` above the log.
    """
    if show_header:
        panel_header(title, fa.ICON_FA_TERMINAL)

    if imgui.button(f"{fa.ICON_FA_BROOM}  Clear##log_panel"):
        ctx.logs.clear()

    text = "\n".join(ctx.logs) if ctx.logs else "(no events yet)"
    h = height if height > 0 else -1.0
    imgui.input_text_multiline(
        "##log_panel",
        text,
        imgui.ImVec2(-1, h),
        flags=imgui.InputTextFlags_.read_only,
    )


__all__ = ["log_panel"]
