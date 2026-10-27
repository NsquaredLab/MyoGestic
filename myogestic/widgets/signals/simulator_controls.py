"""Persistent controls for the synthetic EMG generator."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from imgui_bundle import imgui

from myogestic.widgets.common import (
    IDLE,
    SUCCESS,
    fit_text,
    muted,
    panel_header,
    pop_selected,
    push_selected,
)

if TYPE_CHECKING:
    from mne_lsl.lsl import StreamOutlet

    from myogestic.core import Context


class SimulatorControls:
    """Steer synthetic EMG independently of the active workflow step.

    Parameters
    ----------
    presets
        Label and control-value pairs, such as ``[("Rest", 0.0), ("Fist", 1.0)]``.
        The initial value is ``0.0`` (rest).
    outlet
        Control-stream outlet. If omitted, create ``emg_generator.control_outlet()``
        on the first ``ui`` or ``set`` call, so construction has no LSL side effects.
    widget_id
        Stable ImGui identity; use a distinct ID for each card in the same window.

    Notes
    -----
    Manual controls are disabled while recording. Call ``set`` from the recording
    gesture callback to keep the generator and selected chip in sync.
    """

    def __init__(
        self,
        presets: list[tuple[str, float]],
        *,
        outlet: StreamOutlet | None = None,
        widget_id: str = "simulator",
    ) -> None:
        self._presets = list(presets)
        self._outlet = outlet
        self._widget_id = widget_id
        self._value = 0.0

    @property
    def value(self) -> float:
        """Current control value; any matching preset chip is selected."""
        return self._value

    def _ensure_outlet(self) -> StreamOutlet:
        if self._outlet is None:
            from myogestic.tools.emg_generator import control_outlet

            self._outlet = control_outlet()
        return self._outlet

    def set(self, value: float) -> None:
        """Publish a value and select any matching preset, including during recording."""
        value = float(value)
        self._ensure_outlet().push_sample(np.array([value], dtype=np.float32))
        self._value = value

    def ui(self, ctx: Context) -> None:
        """Draw one compact card; the recording gesture owns the value during a take."""
        # Advertise before the first click so the generator can discover the stream.
        self._ensure_outlet()
        imgui.push_id(self._widget_id)
        recording = ctx.recording
        panel_header("Simulated EMG", status=SUCCESS if self._value else IDLE)
        imgui.set_item_tooltip("Active signal" if self._value else "Rest signal")
        imgui.begin_disabled(recording)
        style = imgui.get_style()
        width = imgui.get_content_region_avail().x
        right = imgui.get_cursor_screen_pos().x + width
        for i, (label, value) in enumerate(self._presets):
            shown = fit_text(label, max(1.0, width - 2 * style.frame_padding.x))
            chip_width = imgui.calc_text_size(shown).x + 2 * style.frame_padding.x
            if i and imgui.get_item_rect_max().x + style.item_spacing.x + chip_width <= right:
                imgui.same_line()
            selected = self._value == value
            if selected:
                push_selected()
            clicked = imgui.small_button(f"{shown}##preset_{i}")
            if selected:
                pop_selected()
            imgui.set_item_tooltip(label)
            if clicked and not recording:
                self.set(value)
        imgui.end_disabled()
        if recording:
            imgui.push_style_color(imgui.Col_.text, muted())
            imgui.text_wrapped("The simulator follows the gesture being recorded.")
            imgui.pop_style_color()
        imgui.pop_id()
