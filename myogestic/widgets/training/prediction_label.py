"""Show the latest classifier prediction as a centred class-name label.

Reads ``pipeline.predictions`` every frame and renders the predicted class
as a big, centred panel — "what does the model think *right now*" without
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

Pure read-only widget — no callbacks, no state. The example owns ``CLASSES``
so the widget stays generic across examples (binary, multi-DOF, ...).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import PALETTE, panel_header

if TYPE_CHECKING:
    from myogestic.ml import Pipeline


class PredictionLabel:
    """Render the current predicted class name as a big centred label.

    The class index is looked up in ``pipeline.predictions[class_key]`` and the
    name is taken from ``class_names``. Colour-codes each class with the
    shared :data:`myogestic.widgets.common.PALETTE` so the same class is
    always the same colour (matches the recording / session-manager
    chips).
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
            Panel header text.
        show_probability
            When True, render a coloured progress bar of the
            predicted class's probability below the name.
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
        """Render the current predicted class name as a big centred label."""
        imgui.push_id(self._widget_id or self._title)
        try:
            panel_header(self._title, fa.ICON_FA_BRAIN)
            imgui.spacing()

            idx = self._pipeline.predictions.get(self._class_key)
            if not isinstance(idx, int) or not (0 <= idx < len(self._class_names)):
                imgui.text_disabled("—  (no prediction yet)")
                imgui.spacing()
                return

            name = self._class_names[idx]
            rgb = PALETTE[idx % len(PALETTE)]
            rgba = imgui.ImVec4(float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)

            # Big, centred class name. `set_window_font_scale` was removed
            # upstream; the modern API is `push_font(None, unscaled_base_size)`
            # — pass None to keep the current font, and a size in the
            # *unscaled* base unit (style global scale factors are applied on
            # top automatically).
            base_size = imgui.get_style().font_size_base
            imgui.push_font(None, base_size * self._font_scale)
            try:
                avail = imgui.get_content_region_avail().x
                text_w = imgui.calc_text_size(name).x
                imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(0.0, (avail - text_w) * 0.5))
                imgui.text_colored(rgba, name)
            finally:
                imgui.pop_font()

            if self._show_probability:
                proba = self._pipeline.predictions.get(self._probability_key)
                try:
                    p = float(proba[idx])  # type: ignore
                except (TypeError, IndexError):
                    p = None
                imgui.spacing()
                if p is None:
                    imgui.text_disabled("(no probability vector in predictions)")
                else:
                    imgui.push_style_color(imgui.Col_.plot_histogram, rgba)
                    imgui.progress_bar(p, imgui.ImVec2(-1, 0), f"{p:.0%}")
                    imgui.pop_style_color()

            imgui.spacing()
        finally:
            imgui.pop_id()


__all__ = ["PredictionLabel"]
