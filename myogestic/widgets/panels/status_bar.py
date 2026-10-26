"""A compact session footer with acquisition, storage and optional model status."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.core import Context
from myogestic.widgets.common import IDLE, SUCCESS, edge_rule, fit_text, muted

if TYPE_CHECKING:
    from myogestic.ml import Pipeline

__all__ = ["StatusBar"]


class StatusBar:
    """Show acquisition, participant storage and an optional fitted model.

    Parameters
    ----------
    stream : str, optional
        Acquisition stream to describe, by default ``"emg"``.
    sessions_dir : str or Path, optional
        Root of the participant folders, by default ``"sessions"``.
    pipeline : Pipeline or None, optional
        Read ``model`` and ``last_saved_model`` for a right-aligned model
        readout. Without a pipeline, no model text is drawn.
    widget_id : str, optional
        Stable ImGui identity, by default ``"status_bar"``.

    Notes
    -----
    Place in a bare ``Px(26)`` Grid row. No caller style pushes are needed.
    Long acquisition details and model names ellipsize; hover for the full text.
    """

    def __init__(
        self, stream: str = "emg", *, sessions_dir: str | Path = "sessions",
        pipeline: Pipeline | None = None, widget_id: str = "status_bar",
    ) -> None:
        self.stream = stream
        self.sessions_dir = Path(sessions_dir)
        self.pipeline = pipeline
        self._widget_id = widget_id

    def ui(self, ctx: Context) -> None:
        """Draw the footer from the context's live streams and participant.

        Parameters
        ----------
        ctx : Context
            Acquisition state and the participant whose folder is displayed.
        """
        imgui.push_id(self._widget_id)
        try:
            self._draw(ctx)
        finally:
            imgui.pop_id()

    def _draw(self, ctx: Context) -> None:
        stream = ctx.streams.get(self.stream)
        connected = stream is not None and stream.status == "connected" and stream.info is not None
        if connected:
            info = stream.info
            source = f"{stream.name} · {info.n_channels} ch / {info.fs:g} Hz"
        else:
            source = f"{self.stream} · disconnected"
        folder = self.sessions_dir / ctx.participant
        text = f"{source} · {ctx.participant or 'No participant'} · {folder}"
        model = ""
        if self.pipeline is not None:
            if self.pipeline.model is None:
                model = "Model: none"
            elif self.pipeline.last_saved_model:
                model = f"Model: {Path(self.pipeline.last_saved_model).name}"
            else:
                model = "Model: fitted (not saved)"

        edge_rule(bottom=False)
        imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + max(
            0.0, (imgui.get_content_region_avail().y - imgui.get_text_line_height()) / 2,
        ))
        imgui.text_colored(SUCCESS if connected else IDLE, fa.ICON_FA_CIRCLE)
        imgui.same_line()
        available = imgui.get_content_region_avail().x
        right = imgui.get_cursor_pos_x() + available
        model_w = min(imgui.calc_text_size(model).x, available * 0.4) if model else 0.0
        gap = imgui.get_style().item_spacing.x if model else 0.0
        imgui.text_colored(muted(), fit_text(text, max(0.0, available - model_w - gap)))
        if imgui.is_item_hovered():
            imgui.set_tooltip(text)
        if model:
            shown = fit_text(model, model_w)
            imgui.same_line()
            imgui.set_cursor_pos_x(right - imgui.calc_text_size(shown).x)
            imgui.text_colored(muted(), shown)
            if imgui.is_item_hovered():
                imgui.set_tooltip(model)
