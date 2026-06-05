"""Show the latest classifier prediction as a centred class-name label.

Reads ``pipeline.predictions`` every frame and renders the predicted class
as a big, centred panel — "what does the model think *right now*" without
having to read the signal viewer or watch the VHI hand. Drop it next to the
pipeline panel::

    from myogestic.widgets import prediction_label

    CLASSES = ["Rest", "Fist"]

    @pipeline.predict
    def predict(model, features):
        ...
        return {"class": class_idx, "proba": proba}   # the convention this widget reads

    @app.ui
    def ui(ctx):
        with grid[5, 0]:
            prediction_label(pipeline, CLASSES)

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


def prediction_label(
    pipeline: Pipeline,
    class_names: Sequence[str],
    *,
    key: str = "class",
    proba_key: str = "proba",
    label: str = "Prediction",
    show_probability: bool = False,
    font_scale: float = 2.0,
) -> None:
    """Render the current predicted class name as a big centred label.

    The class index is looked up in ``pipeline.predictions[key]`` and the
    name is taken from ``class_names``. Colour-codes each class with the
    shared :data:`myogestic.widgets.common.PALETTE` so the same class is
    always the same colour (matches the recording / session-manager
    chips).

    Parameters
    ----------
    pipeline
        The Pipeline whose predictions to read. Untrained or
        first-frame state (``predictions == {}``) renders as a muted "—".
    class_names
        Class names indexed the same way as the model —
        ``class_names[i]`` is the name for class index ``i``.
    key
        Dict key in ``predictions`` holding the class index. Default
        ``"class"`` matches the convention in the bundled examples.
    proba_key
        Dict key holding the per-class probability vector,
        consumed only when ``show_probability`` is on.
    label
        Panel header text.
    show_probability
        When True, render a coloured progress bar of the
        predicted class's probability below the name.
    font_scale
        Multiplier applied to the class name's text size.
        Defaults to 2× the panel font.
    """
    panel_header(label, fa.ICON_FA_BRAIN)
    imgui.spacing()

    idx = pipeline.predictions.get(key)
    if not isinstance(idx, int) or not (0 <= idx < len(class_names)):
        imgui.text_disabled("—  (no prediction yet)")
        imgui.spacing()
        return

    name = class_names[idx]
    rgb = PALETTE[idx % len(PALETTE)]
    rgba = imgui.ImVec4(float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)

    # Big, centred class name. `set_window_font_scale` was removed upstream;
    # the modern API is `push_font(None, unscaled_base_size)` — pass None to
    # keep the current font, and a size in the *unscaled* base unit (style
    # global scale factors are applied on top automatically).
    base_size = imgui.get_style().font_size_base
    imgui.push_font(None, base_size * font_scale)
    try:
        avail = imgui.get_content_region_avail().x
        text_w = imgui.calc_text_size(name).x
        imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(0.0, (avail - text_w) * 0.5))
        imgui.text_colored(rgba, name)
    finally:
        imgui.pop_font()

    if show_probability:
        proba = pipeline.predictions.get(proba_key)
        try:
            p = float(proba[idx])  # type: ignore[index]
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


__all__ = ["prediction_label"]
