"""The FollowRun card's responsive controls and readouts."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from imgui_bundle import imgui

from myogestic.widgets.common import (
    DANGER,
    IDLE,
    SUCCESS,
    mono_font,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    primary_button,
    push_selected,
    tinted_row,
    ui_px,
)

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.widgets.follow import FollowRun


def _text(value: str, *, mono: bool = False) -> None:
    """Keep a readout inside its cell, exposing its complete text on hover."""
    font = mono_font() if mono else None
    if font is not None:
        imgui.push_font(font, imgui.get_style().font_size_base)
    shown = value
    width = imgui.get_content_region_avail().x
    while shown and imgui.calc_text_size(shown + "…").x > width:
        shown = shown[:-1]
    if shown != value:
        shown += "…"
    if font is not None:
        imgui.pop_font()
    if mono:
        mono_text(shown)
    else:
        imgui.text_unformatted(shown)
    imgui.set_item_tooltip(value)


def draw(run: FollowRun, ctx: Context, disabled_reason: str) -> None:
    """Render one card with a single forward action and no hardware dependencies."""
    s = run._state
    tone = SUCCESS if run.running else DANGER if s.phase == "error" else IDLE
    imgui.push_id(run._widget_id)
    panel_header("Follow the control hand", status=tone)
    with tinted_row(tone):
        _text(
            {
                "idle": "Ready",
                "running": "Running",
                "saving": "Saving…",
                "results": "Run saved",
                "error": "Could not score the saved run",
            }[s.phase]
        )
    locked = run.running or s.phase == "saving"
    imgui.begin_disabled(locked)
    imgui.text_colored(muted(), "Gesture")
    left = imgui.get_cursor_pos_x()
    right = left + imgui.get_content_region_avail().x
    for index, name in enumerate(run.gestures):
        if index:
            width = imgui.calc_text_size(name).x + 2 * imgui.get_style().frame_padding.x
            # The previous button's local right edge, plus spacing and the next chip.
            prev_right = imgui.get_item_rect_max().x - imgui.get_window_pos().x
            if prev_right + imgui.get_style().item_spacing.x + width <= right:
                imgui.same_line()
        selected = s.gesture == index
        if selected:
            push_selected()
        shown = name
        while (
            shown
            and imgui.calc_text_size(shown + "…").x + 2 * imgui.get_style().frame_padding.x
            > right - left
        ):
            shown = shown[:-1]
        label = shown if shown == name else shown + "…"
        clicked = imgui.button(f"{label}##gesture-{index}")
        if selected:
            pop_selected()
        imgui.set_item_tooltip(name)
        if clicked and not locked:
            s.gesture = index
    columns = 2 if imgui.get_content_region_avail().x >= ui_px(360) else 1
    if imgui.begin_table("settings", columns):
        for attr, caption in (
            ("move_s", "Movement (s)"),
            ("hold_high_s", "Hold at top (s)"),
            ("hold_low_s", "Hold at bottom (s)"),
            ("peak", "Peak (%)"),
            ("reps", "Repetitions"),
        ):
            imgui.table_next_column()
            imgui.align_text_to_frame_padding()
            imgui.text_colored(muted(), caption)
            imgui.set_next_item_width(-1)
            value = getattr(s.trajectory, attr)
            if attr == "reps":
                changed, value = imgui.input_int("##" + attr, value)
                value = min(200, max(1, value))
            elif attr == "peak":
                changed, value = imgui.slider_float(
                    "##peak", value * 100, 0, 100, "%.0f%%", imgui.SliderFlags_.always_clamp
                )
                value /= 100
            else:
                changed, value = imgui.input_float("##" + attr, value, format="%.1f")
                value = (
                    min(600.0, max(0.1 if attr == "move_s" else 0.0, value))
                    if math.isfinite(value)
                    else getattr(s.trajectory, attr)
                )
            if changed and not locked:
                s.trajectory = replace(s.trajectory, **{attr: value})
        imgui.end_table()
    imgui.end_disabled()
    if locked:
        _text("Settings unlock after saving.")
    if run.running:
        phase = (
            "Get ready"
            if s.elapsed < s.trajectory.lead_s
            else s.trajectory.phase_at(s.elapsed).replace("_", " ")
        )
        _text(phase)
        imgui.progress_bar(
            min(1.0, s.elapsed / s.trajectory.total_duration), imgui.ImVec2(-1, 0), ""
        )
        _text(f"{s.elapsed:.1f} / {s.trajectory.total_duration:.1f} s", mono=True)
    if s.score is not None and imgui.begin_table("results", 3 if columns == 2 else 1):
        for key, caption, suffix in (
            ("rmse", "RMSE", ""),
            ("r", "Pearson r", ""),
            ("lag_s", "Lag", " s"),
        ):
            imgui.table_next_column()
            imgui.align_text_to_frame_padding()
            imgui.text_colored(muted(), caption)
            value = s.score[key]
            _text("—" if value is None else f"{value:.3f}{suffix}", mono=True)
        imgui.end_table()
    reason = (
        "Saving the run…"
        if s.phase == "saving"
        else "Stop the current recording first."
        if ctx.recording and not run.running
        else disabled_reason
    )
    disabled = bool(reason) and not run.running
    imgui.begin_disabled(disabled)
    clicked = primary_button(
        "Stop" if run.running else "Start", size=(imgui.get_content_region_avail().x, 0)
    )
    imgui.end_disabled()
    if clicked and not disabled:
        if run.running:
            run.stop(ctx)
        else:
            run.start(ctx)
    if disabled:
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped(reason)
        imgui.pop_style_color()
    imgui.pop_id()
