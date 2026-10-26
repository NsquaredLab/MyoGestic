"""Show the latest classifier prediction in a compact card.

Reads ``pipeline.predictions`` every frame and renders the predicted class
as a display label on a surface card — "what does the model think *right now*" without
having to read the signal viewer or watch the VHI hand. Drop it next to the
pipeline panel::

    from myogestic.widgets import PredictionLabel

    CLASSES = ["Rest", "Fist"]

    @pipeline.predict
    def predict(model, features):
        ...
        return {"class": class_idx, "proba": proba}   # the convention this widget reads

    label = PredictionLabel(pipeline, CLASSES)

    @app.ui
    def ui(ctx):
        with grid[5, 0]:
            label.ui()

Pure read-only widget — no callbacks, no state. The caller owns ``CLASSES``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from imgui_bundle import imgui

from myogestic._theme import display_font, mono_font
from myogestic.widgets.common import PALETTE, flash_color, mono_text, muted, primary, ui_px

if TYPE_CHECKING:
    from myogestic.ml import Pipeline


class PredictionLabel:
    """Render the predicted class, cadence and per-class probability bars.

    The class index is looked up in ``pipeline.predictions[class_key]`` and the
    name is taken from ``class_names``. Colour-coded from the shared `PALETTE`,
    so a class keeps the same colour as its recording / session-manager chips.

    Examples
    --------
    >>> from myogestic.widgets import PredictionLabel
    >>> label = PredictionLabel(pipeline, ["Rest", "Fist"])
    >>> label.ui()
    """

    def __init__(
        self,
        pipeline: Pipeline,
        class_names: Sequence[str],
        *,
        class_key: str = "class",
        probability_key: str = "proba",
        title: str = "Prediction",
        show_probability: bool = False,
        font_scale: float = 2.0,
        widget_id: str | None = None,
    ) -> None:
        """Configure the prediction label.

        Parameters
        ----------
        pipeline
            The Pipeline whose predictions to read. Untrained or
            first-frame state (``predictions == {}``) renders as a muted "—".
        class_names
            Class names indexed the same way as the model —
            ``class_names[i]`` is the name for class index ``i``.
        class_key
            Dict key in ``predictions`` holding the class index. Default
            ``"class"`` matches the convention in the bundled examples.
        probability_key
            Dict key holding the per-class probability vector,
            consumed only when ``show_probability`` is on.
        title
            Card identity and tooltip text.
        show_probability
            When True, render one thin categorical bar and mono percentage
            for every class below the name.
        font_scale
            Multiplier applied to the class name's text size.
            Defaults to 2× the panel font.
        widget_id
            Optional per-instance ImGui id scope. Defaults to ``title``.
        """
        self._pipeline = pipeline
        self._class_names = class_names
        self._class_key = class_key
        self._probability_key = probability_key
        self._title = title
        self._show_probability = show_probability
        self._font_scale = font_scale
        self._widget_id = widget_id

    def ui(self) -> None:
        """Render the prediction or idle reason.

        Probability bars share a fixed 0–1 range.
        """
        imgui.push_id(self._widget_id or self._title)
        style = imgui.get_style()
        imgui.push_style_color(imgui.Col_.child_bg, style.color_(imgui.Col_.frame_bg))
        imgui.begin_child("card", imgui.ImVec2(0, 0),
                          imgui.ChildFlags_.auto_resize_y | imgui.ChildFlags_.always_use_window_padding)
        try:
            predictions = self._pipeline.predictions
            idx = predictions.get(self._class_key)
            # Static previews can still supply only the predictions mapping.
            app = getattr(self._pipeline, "app", None)
            state = app.ctx.state if app is not None else "predicting" if predictions else "idle"
            live = state == "predicting" and isinstance(idx, int) and 0 <= idx < len(self._class_names)
            if live:
                hz = getattr(self._pipeline, "predict_hz", 0.0)
                detail = f"every {1000 / hz:.0f} ms" if hz > 0 else "predicting"
            elif state == "predicting":
                detail = "waiting for first prediction"
            elif state != "idle":
                detail = state
            elif getattr(self._pipeline, "model", None) is None:
                detail = "train or load a model"
            else:
                detail = "ready to predict"
            color = muted()
            if live:
                color = imgui.ImVec4(*PALETTE[idx % len(PALETTE)], 1.0)
                color = flash_color(self._widget_id or self._title, idx, color, primary())
            base_size = style.font_size_base
            imgui.push_font(display_font(), base_size * self._font_scale)
            imgui.text_colored(color, self._class_names[idx] if live else "—")
            imgui.pop_font()
            imgui.set_item_tooltip(self._title)
            lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            imgui.push_font(mono_font(), base_size)
            detail_w = imgui.calc_text_size(detail).x
            if hi.x + style.item_spacing.x + detail_w <= right:
                imgui.same_line()
                imgui.set_cursor_screen_pos(imgui.ImVec2(
                    right - detail_w,
                    lo.y + (hi.y - lo.y - imgui.get_text_line_height()) / 2,
                ))
            imgui.text_colored(muted(), detail)
            imgui.pop_font()
            if live and self._show_probability:
                self._probabilities(predictions.get(self._probability_key))
        finally:
            imgui.end_child()
            imgui.pop_style_color()
            imgui.pop_id()

    def _probabilities(self, probabilities: Sequence[float] | None) -> None:
        style = imgui.get_style()
        gap = style.item_spacing.x
        name_w = max(imgui.calc_text_size(name).x for name in self._class_names)
        imgui.push_font(mono_font(), style.font_size_base)
        value_w = imgui.calc_text_size("100%").x
        imgui.pop_font()
        for index, name in enumerate(self._class_names):
            try:
                value = float(probabilities[index])
            except (TypeError, IndexError, ValueError):
                value = None
            left, top = imgui.get_cursor_pos()
            imgui.text_unformatted(name)
            imgui.same_line()
            imgui.set_cursor_pos_x(left + name_w + gap)
            width = max(ui_px(1), imgui.get_content_region_avail().x - value_w - gap)
            height = ui_px(4)
            imgui.set_cursor_pos_y(top + (imgui.get_text_line_height() - height) / 2)
            imgui.push_style_color(imgui.Col_.plot_histogram, imgui.ImVec4(*PALETTE[index % len(PALETTE)], 1.0))
            imgui.push_style_color(imgui.Col_.frame_bg, style.color_(imgui.Col_.popup_bg))
            # A thin bar has no frame padding; charging it to the line would
            # lower the following percentage below its class label.
            imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(style.frame_padding.x, 0))
            imgui.progress_bar(value if value is not None else 0.0, imgui.ImVec2(width, height), "")
            imgui.pop_style_var()
            imgui.pop_style_color(2)
            imgui.same_line()
            imgui.set_cursor_pos_y(top)
            mono_text(f"{value:.0%}" if value is not None else "—", muted())


__all__ = ["PredictionLabel"]
