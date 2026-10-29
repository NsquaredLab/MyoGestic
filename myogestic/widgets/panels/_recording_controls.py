"""Gesture tiles, timing choices, and the constant-height take action row."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.core import RECORDABLE_STATES
from myogestic.widgets.common import (
    COUNT_WARMUP_ON_LIGHT,
    DANGER,
    PALETTE,
    RECORD_FILL,
    SUCCESS,
    WARNING,
    action_row,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    primary,
    push_selected,
    segmented,
    tinted_row,
    ui_px,
)

from .recording import _record_button, _stop_pill, _stop_pill_width

if TYPE_CHECKING:
    from myogestic.core import RECORDABLE_STATES, Context

    from .recording import RecordingControls, TakeStatus


def _clock(seconds: float) -> str:
    tenths = round(max(0.0, seconds) * 10)
    minutes, tenths = divmod(tenths, 600)
    return f"{minutes}:{tenths // 10:02d}.{tenths % 10}"


def _fit(text: str, width: float) -> str:
    if imgui.calc_text_size(text).x <= width:
        return text
    while text and imgui.calc_text_size(text + "…").x > width:
        text = text[:-1]
    return text + "…" if text else ""


def _segments_min_width(options: list[str]) -> float:
    # Match segmented()'s two-pixel gaps, before any button padding is added.
    return sum(imgui.calc_text_size(text).x for text in options) + 2 * (len(options) - 1)


def _segments(key: str, options: list[str], index: int, width: float) -> int:
    style = imgui.get_style()
    pad = max(0.0, (width - _segments_min_width(options)) / (2 * len(options)))
    imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(pad, style.frame_padding.y))
    try:
        return segmented(key, options, index)
    finally:
        imgui.pop_style_var()


def _timing_choices(controls: RecordingControls) -> None:
    if not controls._take_lengths:
        return
    active = controls.take.phase in ("warmup", "recording")
    imgui.begin_disabled(active)
    try:
        selected = _segments(
            "take-mode",
            ["Start / stop", "Timed"],
            int(controls._timed),
            imgui.get_content_region_avail().x,
        )
        if not active:
            controls._timed = bool(selected)
        if not controls._timed:
            return
        fields = [
            (caption, key, [f"{n:g} s" if n else "Off" for n in values], index)
            for caption, key, values, index in (
                ("Take length", "length", controls._take_lengths, controls._length_index),
                ("Warm-up", "warmup", controls._warmups, controls._warmup_index),
            )
        ]
        min_width = max(
            max(imgui.calc_text_size(caption).x, _segments_min_width(options))
            for caption, _, options, _ in fields
        )
        # A borderless table has no outer padding; each column contributes one
        # cell-padding width to the gap between the two fields.
        two_columns = 2 * (min_width + imgui.get_style().cell_padding.x)
        columns = 2 if imgui.get_content_region_avail().x >= two_columns else 1
        if imgui.begin_table("take-options", columns, imgui.TableFlags_.sizing_stretch_same):
            try:
                for start in range(0, len(fields), columns):
                    row = fields[start : start + columns]
                    for caption, _, _, _ in row:
                        imgui.table_next_column()
                        imgui.text_colored(muted(), caption)
                    for _, key, options, index in row:
                        imgui.table_next_column()
                        selected = _segments(
                            key, options, index, imgui.get_content_region_avail().x
                        )
                        if not active:
                            if key == "length":
                                controls._length_index = selected
                            else:
                                controls._warmup_index = selected
            finally:
                imgui.end_table()
    finally:
        imgui.end_disabled()


def _gesture_tiles(ctx: Context, controls: RecordingControls) -> None:
    names = controls._class_names or []
    if not names:
        return
    imgui.text_colored(muted(), "Gesture")
    style = imgui.get_style()
    spacing = style.item_spacing.x
    available = imgui.get_content_region_avail().x
    columns = max(1, min(len(names), int((available + spacing) / (ui_px(110) + spacing))))
    width = max(1.0, (available - spacing * (columns - 1)) / columns)
    height = ui_px(44)
    dot, gap = ui_px(6), ui_px(6)
    locked = controls.take.timed and controls.take.phase in ("warmup", "recording")
    current = controls._gesture_index(ctx)
    for i, name in enumerate(names):
        if i % columns:
            imgui.same_line()
        selected = current == i
        disabled = locked and not selected
        imgui.begin_disabled(disabled)
        if selected:
            push_selected()
        try:
            clicked = imgui.button(f"##rec_gesture{i}", imgui.ImVec2(width, height))
            lo = imgui.get_item_rect_min()
            label = _fit(name, max(0.0, width - dot - gap - 2 * style.frame_padding.x))
            size = imgui.calc_text_size(label)
            left = lo.x + (width - dot - gap - size.x) / 2
            draw = imgui.get_window_draw_list()
            color = PALETTE[i % len(PALETTE)]
            draw.add_circle_filled(
                imgui.ImVec2(left + dot / 2, lo.y + height / 2),
                dot / 2,
                imgui.get_color_u32(imgui.ImVec4(*color, 1.0)),
            )
            draw.add_text(
                imgui.ImVec2(left + dot + gap, lo.y + (height - size.y) / 2),
                imgui.get_color_u32(primary()),
                label,
            )
            if label != name:
                imgui.set_item_tooltip(name)
            if clicked and not locked:
                ctx.current_label = i
                if ctx.recording and ctx.session is not None and not locked:
                    ctx.session.add_label(i)
                    controls._machine.status = replace(controls.take, gesture=name)
                if controls._on_gesture is not None:
                    controls._on_gesture(i)
        finally:
            if selected:
                pop_selected()
            imgui.end_disabled()


def _lock_caption(controls: RecordingControls) -> None:
    """Say how to unlock the gestures, under the action that does it.

    Below the action row rather than the tiles: a caption appearing above the row would
    push Stop down from where Record was at the start of every take.
    """
    if not (controls.take.timed and controls.take.phase in ("warmup", "recording")):
        return
    caption = (
        "Cancel the warm-up to change gestures."
        if controls.take.phase == "warmup"
        else "Stop the recording to change gestures."
    )
    imgui.push_text_wrap_pos(0.0)
    imgui.text_colored(muted(), caption)
    imgui.pop_text_wrap_pos()


def _count_color(warmup: bool) -> imgui.ImVec4:
    """The countdown digit's colour, readable on its own row tint in either theme.

    The status tones are made for a dark surface: on the light theme's pale tints a
    `DANGER` digit is 2.5:1 and a `WARNING` one 1.6:1, so it takes simpetru-figstyle's
    darker shades there (3.9:1 and 2.9:1). The theme is read from its canvas, the way
    `muted` reads the text colour.
    """
    canvas = imgui.get_style().color_(imgui.Col_.window_bg)
    if canvas.x + canvas.y + canvas.z < 1.5:
        return WARNING if warmup else DANGER
    return COUNT_WARMUP_ON_LIGHT if warmup else RECORD_FILL


def _take_detail(take: TakeStatus) -> str:
    """The take's numbers, for the row's mono line."""
    if take.phase == "warmup":
        return "nothing recorded yet"
    if take.phase == "saved":
        if take.length_s is not None and take.elapsed_s < take.length_s:
            # Qualifier first, so a narrow step truncates the numbers, not the news.
            return f"stopped early · {_clock(take.elapsed_s)} of {_clock(take.length_s)}"
        return f"{_clock(take.elapsed_s)} recorded"
    if take.timed:
        return f"{_clock(take.elapsed_s)} / {_clock(take.length_s)}"
    return f"{_clock(take.elapsed_s)} elapsed"


def _take_row(take: TakeStatus, inner: float, height: float, action: str) -> None:
    """One take state: glyph, title and mono numbers, and the action's name on the right.

    The glyph is the count you guide by: whole seconds to go while a warm-up or a timed
    take counts down, a dot for an open-ended take, a check once it is saved.
    """
    warmup, saved = take.phase == "warmup", take.phase == "saved"
    left, top = imgui.get_cursor_pos()
    right = left + inner
    action_w = (
        0.0
        if not action
        else imgui.calc_text_size(action).x
        if warmup
        else _stop_pill_width(action)
    )
    text_right = right - action_w - ui_px(8)
    middle = top + (height - ui_px(8)) / 2  # the row's vertical centre
    # One glyph column for every state, so the titles line up as a take moves on.
    imgui.push_font(None, imgui.get_style().font_size_base * 2.2)
    column = imgui.calc_text_size("0").x
    if warmup or (take.phase == "recording" and take.timed):
        left_s = take.warmup_left_s if warmup else take.length_s - take.elapsed_s
        digit = str(max(0, math.ceil(left_s)))
        imgui.set_cursor_pos(
            imgui.ImVec2(
                left + (column - imgui.calc_text_size(digit).x) / 2,
                middle - imgui.get_text_line_height() / 2,
            )
        )
        imgui.text_colored(_count_color(warmup), digit)
    imgui.pop_font()
    if not (warmup or (take.phase == "recording" and take.timed)):
        glyph = fa.ICON_FA_CIRCLE_CHECK if saved else fa.ICON_FA_CIRCLE
        imgui.set_cursor_pos(
            imgui.ImVec2(
                left + (column - imgui.calc_text_size(glyph).x) / 2,
                middle - imgui.get_text_line_height() / 2,
            )
        )
        imgui.text_colored(SUCCESS if saved else DANGER, glyph)
    text_left = left + column + ui_px(10)
    lines = 2 * imgui.get_text_line_height() + ui_px(2)
    imgui.set_cursor_pos(imgui.ImVec2(text_left, middle - lines / 2))
    imgui.begin_group()
    title = "Saved" if saved else "Get ready" if warmup else "Recording"
    if take.gesture:
        title += f" · {take.gesture}"
    imgui.text_unformatted(_fit(title, text_right - text_left))
    imgui.set_item_tooltip(title)
    imgui.set_cursor_pos(
        imgui.ImVec2(text_left, middle - lines / 2 + imgui.get_text_line_height() + ui_px(2))
    )
    mono_text(_fit(_take_detail(take), text_right - text_left), muted())
    imgui.end_group()
    if warmup:
        imgui.set_cursor_pos(
            imgui.ImVec2(right - action_w, middle - imgui.get_text_line_height() / 2)
        )
        imgui.text_unformatted(action)
    elif action:
        _stop_pill(action, right, top, height)


def _action(ctx: Context, controls: RecordingControls) -> None:
    take = controls.take
    height = max(ui_px(52), 2 * imgui.get_text_line_height() + ui_px(12))
    if take.phase == "idle":
        gesture = controls._gesture(ctx)
        label = f"Record {gesture}" if gesture else "Record"
        if controls._timed:
            label += f" · {controls._take_lengths[controls._length_index]:g} s"
        needs_gesture = controls._timed and bool(controls._class_names) and gesture is None
        imgui.begin_disabled(ctx.recording or ctx.state not in RECORDABLE_STATES or needs_gesture)
        try:
            if _record_button(
                ctx,
                f"{fa.ICON_FA_CIRCLE}  {label}##rec_btn",
                imgui.ImVec2(imgui.get_content_region_avail().x, height),
            ):
                controls._start(ctx)
        finally:
            imgui.end_disabled()
        if needs_gesture and imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
            imgui.set_tooltip("Choose a gesture before starting a timed take.")
        return

    warmup = take.phase == "warmup"
    saved = take.phase == "saved"
    tone = SUCCESS if saved else WARNING if warmup else DANGER
    origin = imgui.get_cursor_screen_pos()
    width = imgui.get_content_region_avail().x
    if saved:
        with tinted_row(tone, height=height) as inner:
            _take_row(take, inner, height, "")
    else:
        # Where Record was: the whole row is the action, so the second click lands
        # where the first one did.
        with action_row("##rec_btn", tone, height=height) as (clicked, inner):
            _take_row(
                take, inner, height, "Cancel" if warmup else "Stop early" if take.timed else "Stop"
            )
        if clicked:
            controls._machine.stop()
    if warmup or (take.phase == "recording" and take.timed):
        fraction = (
            1 - take.warmup_left_s / controls._warmups[controls._warmup_index]
            if warmup
            else take.elapsed_s / take.length_s
        )
        imgui.get_window_draw_list().add_rect_filled(
            imgui.ImVec2(origin.x, origin.y + height - ui_px(2)),
            imgui.ImVec2(origin.x + width * min(1.0, max(0.0, fraction)), origin.y + height),
            imgui.get_color_u32(tone),
        )


def _render_recording_controls(ctx: Context, controls: RecordingControls) -> None:
    if controls._show_header:
        panel_header("RECORDING", fa.ICON_FA_CIRCLE_DOT)
    _gesture_tiles(ctx, controls)
    _timing_choices(controls)
    _action(ctx, controls)
    _lock_caption(controls)
