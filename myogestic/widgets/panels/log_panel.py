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

from myogestic.widgets.common import panel_header_button
from myogestic.widgets.panels.log_box import render_log

if TYPE_CHECKING:
    from myogestic.core import Context


class LogPanel:
    """Render the app log as a scrollable, read-only panel."""

    def __init__(
        self,
        *,
        height: float = -1.0,
        title: str = "Log",
        show_header: bool = True,
        widget_id: str | None = None,
    ) -> None:
        """Configure the log panel.

        Parameters
        ----------
        height
            Panel height in pixels. Pass a value ``<= 0`` (default) to
            fill the remaining vertical space of the parent cell — matches
            the ImGui convention where ``-1`` means "fill available".
        title
            Header label (only shown when ``show_header=True``).
        show_header
            Render the button-style ``panel_header`` above the log.
        widget_id
            Optional per-instance ImGui id scope. Defaults to ``title``.
        """
        self._height = height
        self._title = title
        self._show_header = show_header
        self._widget_id = widget_id

    def ui(self, ctx: Context) -> None:
        """Render the app log.

        Parameters
        ----------
        ctx
            App context; reads from ``ctx.logs``.
        """
        imgui.push_id(self._widget_id or self._title)
        try:
            # Clear is a right-aligned icon button on the header row (same look
            # as the post-processing panel's Reset). Without a header, it keeps
            # its own line above the log.
            if self._show_header:
                clear = panel_header_button(
                    self._title, fa.ICON_FA_TERMINAL, fa.ICON_FA_BROOM, tooltip="Clear the log"
                )
            else:
                clear = imgui.small_button(f"{fa.ICON_FA_BROOM}##clear")
                if imgui.is_item_hovered():
                    imgui.set_tooltip("Clear the log")
            if clear:
                ctx.logs.clear()

            # Shared log renderer: a child window with a horizontal scrollbar
            # and non-wrapping lines, so long entries scroll sideways in a
            # narrow panel instead of wrapping or clipping (same UX as the
            # process / training logs). Auto-follows the tail.
            h = self._height if self._height > 0 else -1.0
            render_log(
                self._widget_id or self._title,
                ctx.logs or ["(no events yet)"],
                height=h,
            )
        finally:
            imgui.pop_id()


__all__ = ["LogPanel"]
