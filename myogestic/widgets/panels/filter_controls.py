"""Runtime-tunable post-processing filter widget.

A dedicated panel for post-prediction smoothing — visually distinct from
the train/predict pipeline controls. Construct once, call ``.ui()`` each
frame inside ``@app.ui``, and use the holder as a callable in your
``@pipeline.predict`` body::

    from myogestic.widgets.panels.filter_controls import FilterControl

    output_filter = FilterControl(hz=32, default="one_euro")

    @pipeline.predict
    def predict(model, features):
        pred = model.predict(features.reshape(1, -1))[0]
        pred = output_filter(pred)          # uses currently-selected filter
        outlet.push(pred)

    @app.ui
    def ui(ctx):
        output_filter.ui()                  # full panel
"""

from __future__ import annotations

from typing import Any

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.outputs.filters import OneEuroFilter, VectorFilter, make_filter
from myogestic.widgets.common import panel_header

_NAMES = ["identity", "gaussian", "one_euro"]
_DISPLAY = {
    "identity": "Identity",
    "gaussian": "Gaussian",
    "one_euro": "One Euro",
}
_DESCRIPTIONS = {
    "identity": "Passthrough — no smoothing.",
    "gaussian": "Rolling temporal average. Steady, predictable lag.",
    "one_euro": "Adaptive low-pass. Fast moves cut through; slow moves smooth.",
}


class FilterControl:
    """Stateful holder for a runtime-tunable :class:`VectorFilter`.

    Renders a self-contained panel with a header, button-style filter
    selector, parameter controls, and a reset button. Parameters update in
    place where possible (no rebuild) to preserve smoothing history during
    live tuning.

    Parameters
    ----------
    hz
        Sample rate forwarded to ``one_euro`` (ignored by others).
    default
        Initial filter name — ``"identity"`` | ``"gaussian"`` | ``"one_euro"``.
    """

    def __init__(self, hz: float = 50.0, default: str = "one_euro"):
        if default not in _NAMES:
            raise ValueError(f"default must be one of {_NAMES}, got {default!r}")
        self.hz = hz
        self._name = default
        self._params: dict[str, dict[str, Any]] = {
            "identity": {},
            "gaussian": {"window": 5, "sigma": 1.0},
            "one_euro": {"min_cutoff": 1.0, "beta": 0.02, "d_cutoff": 1.0},
        }
        self._filter: VectorFilter = self._build()

    @property
    def name(self) -> str:
        return self._name

    @property
    def filter(self) -> VectorFilter:
        return self._filter

    def __call__(self, x: np.ndarray, t: float | None = None) -> np.ndarray:
        return self._filter(x, t)

    def reset(self) -> None:
        """Clear the active filter's smoothing history."""
        self._filter.reset()

    def _build(self) -> VectorFilter:
        return make_filter(self._name, hz=self.hz, **self._params[self._name])

    # --- UI ---

    def ui(self, label: str = "output_filter") -> None:
        """Render the full panel. Call once per frame inside @app.ui."""
        muted = imgui.get_style().color_(imgui.Col_.text_disabled)
        # Header (shared helper) + right-aligned Reset button on the same row
        panel_header("POST-PROCESSING", fa.ICON_FA_WAVE_SQUARE)
        imgui.same_line()
        # Right-align the reset button. Measure its actual width from the
        # text + frame padding so we don't depend on a hardcoded constant.
        reset_label = f"{fa.ICON_FA_ROTATE_LEFT}  Reset"
        text_w = imgui.calc_text_size(reset_label).x
        frame_pad_x = imgui.get_style().frame_padding.x
        btn_w = text_w + frame_pad_x * 2
        avail = imgui.get_content_region_avail().x
        if avail > btn_w + 4:
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + (avail - btn_w))
        if imgui.small_button(f"{reset_label}##{label}"):
            self.reset()
        if imgui.is_item_hovered():
            imgui.set_tooltip("Clear smoothing history (e.g. on a new session).")

        # Filter type buttons — visually consistent with class buttons
        self._render_buttons(label)

        # Brief description
        imgui.push_style_color(imgui.Col_.text, muted)
        imgui.text_wrapped(_DESCRIPTIONS[self._name])
        imgui.pop_style_color()

        # Parameter controls
        self._render_params(label)

    def _render_buttons(self, label: str) -> None:
        imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(12, 6))
        for i, name in enumerate(_NAMES):
            if i > 0:
                imgui.same_line()
            is_active = self._name == name
            if is_active:
                imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.31, 0.61, 0.98, 0.95))
                imgui.push_style_color(imgui.Col_.text, imgui.ImVec4(1.0, 1.0, 1.0, 1.0))
            if imgui.button(f"{_DISPLAY[name]}##{label}_button_{name}") and not is_active:
                self._name = name
                self._filter = self._build()
            if is_active:
                imgui.pop_style_color(2)
        imgui.pop_style_var()

    def _render_params(self, label: str) -> None:
        params = self._params[self._name]

        if self._name == "identity":
            return  # description above already covers it

        if self._name == "gaussian":
            rebuild = False
            imgui.push_item_width(-100)  # leave room for the value text
            ch, v = imgui.slider_int(f"window (samples)##{label}_g_w", params["window"], 1, 30)
            if ch:
                params["window"] = v
                rebuild = True
            ch, v = imgui.slider_float(f"sigma##{label}_g_s", params["sigma"], 0.1, 10.0, "%.2f")
            if ch:
                params["sigma"] = v
                rebuild = True
            imgui.pop_item_width()
            # Coarse lag hint — exact value depends on the kernel weights
            # (sigma); this is the unweighted-average approximation.
            imgui.push_style_color(
                imgui.Col_.text,
                imgui.get_style().color_(imgui.Col_.text_disabled),
            )
            lag_ms = (params["window"] / 2.0) * (1000.0 / self.hz)
            imgui.text(f"  ≈ {lag_ms:.0f} ms (unweighted avg, sigma-dependent)")
            imgui.pop_style_color()
            if rebuild:
                self._filter = self._build()

        elif self._name == "one_euro":
            f = self._filter
            assert isinstance(f, OneEuroFilter)
            imgui.push_item_width(-100)
            ch, v = imgui.slider_float(
                f"min cutoff##{label}_o_min",
                params["min_cutoff"],
                0.01,
                10.0,
                "%.2f Hz",
            )
            if ch:
                params["min_cutoff"] = v
                f.min_cutoff = v
            ch, v = imgui.slider_float(
                f"beta##{label}_o_b",
                params["beta"],
                0.0,
                1.0,
                "%.3f",
                flags=imgui.SliderFlags_.logarithmic,
            )
            if ch:
                params["beta"] = v
                f.beta = v
            ch, v = imgui.slider_float(
                f"d cutoff##{label}_o_d",
                params["d_cutoff"],
                0.01,
                10.0,
                "%.2f Hz",
            )
            if ch:
                params["d_cutoff"] = v
                f.d_cutoff = v
            imgui.pop_item_width()
            imgui.push_style_color(
                imgui.Col_.text,
                imgui.get_style().color_(imgui.Col_.text_disabled),
            )
            tau_ms = 1000.0 / (2.0 * np.pi * params["min_cutoff"])
            imgui.text(f"  τ at rest ≈ {tau_ms:.0f} ms (actual lag varies with motion)")
            imgui.pop_style_color()
