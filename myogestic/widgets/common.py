"""Shared constants and small visual helpers for widgets."""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui, implot

from myogestic._scale import current_scale
from myogestic._theme import mono_font

# 10 distinct colors for class labels (Category10-like)
PALETTE = np.array(
    [
        [0.12, 0.47, 0.71],  # blue
        [1.00, 0.50, 0.05],  # orange
        [0.17, 0.63, 0.17],  # green
        [0.84, 0.15, 0.16],  # red
        [0.58, 0.40, 0.74],  # purple
        [0.55, 0.34, 0.29],  # brown
        [0.89, 0.47, 0.76],  # pink
        [0.50, 0.50, 0.50],  # gray
        [0.74, 0.74, 0.13],  # olive
        [0.09, 0.75, 0.81],  # cyan
    ],
    dtype=np.float32,
)


# Semantic status colours — the single source for good / warn / bad / info /
# idle, so the same status reads as the same colour across every widget
# (Apple system palette). Separate from the accent hue used for chrome.
SUCCESS = imgui.ImVec4(48 / 255, 209 / 255, 88 / 255, 1.0)  # systemGreen
WARNING = imgui.ImVec4(255 / 255, 159 / 255, 10 / 255, 1.0)  # systemOrange
DANGER = imgui.ImVec4(255 / 255, 69 / 255, 58 / 255, 1.0)  # systemRed
INFO = imgui.ImVec4(10 / 255, 132 / 255, 255 / 255, 1.0)  # systemBlue
IDLE = imgui.ImVec4(142 / 255, 142 / 255, 147 / 255, 1.0)  # systemGray


# Surfaces that keep ONE look in both themes, because they imitate a physical
# thing rather than the app's own chrome: a terminal stays dark on a light
# desktop, a status pill reads as a badge printed on the panel. Everything else
# must come from the theme (see `muted` / `primary`).
CONSOLE_BG = imgui.ImVec4(0.075, 0.078, 0.086, 1.0)
CONSOLE_TEXT = imgui.ImVec4(0.88, 0.89, 0.91, 1.0)
PILL_BG = imgui.ImVec4(0.14, 0.17, 0.21, 1.0)
ON_PILL_TEXT = imgui.ImVec4(0.93, 0.95, 0.98, 1.0)

# Forward actions keep readable white text on the same blue in both themes.
PRIMARY_FILL = imgui.ImVec4(0 / 255, 98 / 255, 204 / 255, 1.0)
ON_PRIMARY_TEXT = imgui.ImVec4(1.0, 1.0, 1.0, 1.0)
# Record and its Stop: simpetru-figstyle's bright red (`REDS[2]`, #d80032), which keeps
# white text at 5.3:1; `DANGER` itself manages only 3.4:1 under white.
RECORD_FILL = imgui.ImVec4(216 / 255, 0 / 255, 50 / 255, 1.0)
# The warm-up count on the light theme, where `WARNING` is 1.6:1 on its own tint:
# simpetru-figstyle's darkest orange (`LIBRARY["emg_manifolds"]`, #d06708), 2.9:1.
COUNT_WARMUP_ON_LIGHT = imgui.ImVec4(208 / 255, 103 / 255, 8 / 255, 1.0)


def ui_px(n: float) -> float:
    """Convert a fixed pixel size at UI scale 1.0 to the current scale.

    Use for fixed widget geometry so it scales with the text.
    """
    return n * current_scale()


def status_pill(label: str, color: imgui.ImVec4) -> None:
    """Draw a labelled status badge with a semantic colour indicator.

    Padding, indicator geometry and label offsets follow the live UI scale.

    Parameters
    ----------
    label : str
        Visible state label, such as ``"IDLE"`` or ``"CONNECTED"``.
    color : imgui.ImVec4
        Indicator colour, normally a semantic token such as ``SUCCESS`` or
        ``IDLE``. The badge background and text use the shared pill tokens.
    """
    pad_x, pad_y = ui_px(10), ui_px(4)
    text = imgui.calc_text_size(label)
    size = imgui.ImVec2(text.x + pad_x * 2 + ui_px(12), text.y + pad_y * 2)
    imgui.dummy(size)
    p0, p1 = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    draw = imgui.get_window_draw_list()
    draw.add_rect_filled(p0, p1, imgui.get_color_u32(PILL_BG), size.y * 0.5)
    y = (p0.y + p1.y) * 0.5
    draw.add_rect_filled(
        imgui.ImVec2(p0.x + pad_x - ui_px(1), y - ui_px(3)),
        imgui.ImVec2(p0.x + pad_x + ui_px(5), y + ui_px(3)),
        imgui.get_color_u32(color),
        ui_px(3),
    )
    draw.add_text(
        imgui.ImVec2(p0.x + pad_x + ui_px(10), p0.y + pad_y),
        imgui.get_color_u32(ON_PILL_TEXT),
        label,
    )


def edge_rule(*, bottom: bool) -> None:
    """Separate a bare header or footer from the body with a theme hairline."""
    origin, size = imgui.get_window_pos(), imgui.get_window_size()
    y = origin.y + size.y - ui_px(1) if bottom else origin.y
    imgui.get_window_draw_list().add_line(
        imgui.ImVec2(origin.x, y),
        imgui.ImVec2(origin.x + size.x, y),
        imgui.get_color_u32(hairline()),
        thickness=ui_px(1),
    )


def primary() -> imgui.ImVec4:
    """The theme's main text colour — resolved per call, so it follows light/dark.

    Never hardcode a colour in a widget: a literal that looks right on the dark
    theme disappears on the light one.
    """
    return imgui.get_style().color_(imgui.Col_.text)


def muted() -> imgui.ImVec4:
    """The theme's secondary-text colour — labels, units, footers, separators.

    See [`primary`][] for why this is a call and not a constant.
    """
    return imgui.get_style().color_(imgui.Col_.text_disabled)


def hairline(alpha: float = 1.0) -> imgui.ImVec4:
    """The theme's separator/border colour, optionally faded to ``alpha``.

    For draw-list outlines (grid cells, overlays) that must stay visible on
    both themes.
    """
    c = imgui.get_style().color_(imgui.Col_.border)
    return imgui.ImVec4(c.x, c.y, c.z, c.w * alpha)


_flash_state: dict[str, tuple[object, float]] = {}


def flash_color(
    key: str,
    value: object,
    base: imgui.ImVec4,
    accent: imgui.ImVec4,
    duration: float = 0.18,
) -> imgui.ImVec4:
    """A colour that flashes on change, then decays back to ``base``.

    Flashes toward ``accent`` when ``value`` changes for ``key``, then decays
    over ``duration`` seconds — the "this just updated" cue for a live readout.
    """
    now = time.perf_counter()
    prev = _flash_state.get(key)
    if prev is None or prev[0] != value:
        _flash_state[key] = (value, now)
        f = 1.0
    else:
        f = max(0.0, 1.0 - (now - prev[1]) / duration)
    if f <= 0.0:
        return base
    return imgui.ImVec4(
        base.x + (accent.x - base.x) * f,
        base.y + (accent.y - base.y) * f,
        base.z + (accent.z - base.z) * f,
        base.w,
    )


_IMPLOT_STYLED = False


def ensure_implot_style() -> None:
    """Apply the app's plot styling to ImPlot once, lazily.

    Call at the top of any plot widget — ImPlot's global style needs a live
    context, so it is set on the first render. Without it the plot renders as
    stock ImPlot rather than as part of the app.
    """
    global _IMPLOT_STYLED
    if _IMPLOT_STYLED:
        return
    _IMPLOT_STYLED = True
    st = implot.get_style()
    st.plot_border_size = 0.0
    st.set_color_(implot.Col_.plot_bg, imgui.ImVec4(0.0, 0.0, 0.0, 0.0))
    st.set_color_(implot.Col_.frame_bg, imgui.ImVec4(0.0, 0.0, 0.0, 0.0))
    st.set_color_(implot.Col_.axis_grid, imgui.ImVec4(1.0, 1.0, 1.0, 0.05))
    st.set_color_(implot.Col_.legend_bg, imgui.ImVec4(0.17, 0.17, 0.18, 0.95))


_ELLIPSIS = "…"

# The one definition of the "this control is the active choice" cue, used for
# *persistent selection* (a momentary press stays neutral gray). Wrap the active
# button:  push_selected(); imgui.button(...); pop_selected().
_ACCENT = imgui.ImVec4(0.31, 0.61, 0.98, 1.0)
_SELECTED_FILL = imgui.ImVec4(0.31, 0.61, 0.98, 0.28)  # translucent accent tint (rest)
_SELECTED_HOVER = imgui.ImVec4(0.31, 0.61, 0.98, 0.40)


def push_selected() -> None:
    """Tint the next button as the selected / active choice (pair with [`pop_selected`][]).

    The selected control gets a translucent accent *tint* plus a 2px accent
    underline, which [`pop_selected`][] draws — so it must always be called.
    """
    imgui.push_style_color(imgui.Col_.button, _SELECTED_FILL)
    imgui.push_style_color(imgui.Col_.button_hovered, _SELECTED_HOVER)
    imgui.push_style_color(imgui.Col_.button_active, _SELECTED_HOVER)


def pop_selected() -> None:
    """Undo the tint pushed by [`push_selected`][] and draw the accent underline."""
    imgui.pop_style_color(3)
    p0 = imgui.get_item_rect_min()
    p1 = imgui.get_item_rect_max()
    y = p1.y - 2.0
    imgui.get_window_draw_list().add_rect_filled(
        imgui.ImVec2(p0.x + 3.0, y),
        imgui.ImVec2(p1.x - 3.0, p1.y),
        imgui.get_color_u32(_ACCENT),
        1.0,
    )


@contextmanager
def tinted_row(tone: imgui.ImVec4 | None = None, *, height: float | None = None) -> Iterator[float]:
    """Frame one compact row with a theme-derived surface and optional status tint.

    Parameters
    ----------
    tone
        Semantic colour mixed into the current surface; ``None`` uses the
        theme's raised surface alone.
    height
        Optional row height in scaled pixels, for a two-line status and action.

    Yields
    ------
    float
        Inner width available for text and right-aligned controls. The row is
        one frame high, with scaled padding and rounded corners.
    """
    style = imgui.get_style()
    surface = style.color_(imgui.Col_.frame_bg) if tone is None else _tinted(tone)
    origin = imgui.get_cursor_screen_pos()
    cursor = imgui.get_cursor_pos()
    width = imgui.get_content_region_avail().x
    pad = ui_px(4)
    height = imgui.get_frame_height() + 2 * pad if height is None else height
    imgui.get_window_draw_list().add_rect_filled(
        origin,
        imgui.ImVec2(origin.x + width, origin.y + height),
        imgui.get_color_u32(surface),
        style.frame_rounding,
    )
    imgui.begin_group()
    imgui.indent(pad)
    imgui.set_cursor_pos_y(cursor.y + pad)
    try:
        yield max(1.0, width - 2 * pad)
    finally:
        imgui.unindent(pad)
        imgui.set_cursor_pos(imgui.ImVec2(cursor.x, cursor.y + height))
        imgui.dummy(imgui.ImVec2(width, 0))
        imgui.end_group()


def _tinted(tone: imgui.ImVec4) -> imgui.ImVec4:
    """The theme's control surface with 12 % of ``tone`` mixed in, opaque."""
    surface = imgui.get_style().color_(imgui.Col_.frame_bg)
    return imgui.ImVec4(
        surface.x * 0.88 + tone.x * 0.12,
        surface.y * 0.88 + tone.y * 0.12,
        surface.z * 0.88 + tone.z * 0.12,
        1.0,
    )


def _lighten(color: imgui.ImVec4, amount: float) -> imgui.ImVec4:
    """Move ``color`` toward white by ``amount``, keeping its alpha."""
    return imgui.ImVec4(
        color.x + (1.0 - color.x) * amount,
        color.y + (1.0 - color.y) * amount,
        color.z + (1.0 - color.z) * amount,
        color.w,
    )


@contextmanager
def action_row(label: str, tone: imgui.ImVec4, *, height: float) -> Iterator[tuple[bool, float]]:
    """A `tinted_row` that is itself the button: the whole row is the click target.

    For a state whose one action ends that state — Stop while recording, Cancel during
    a warm-up — drawn where the control that started it was, so the second click lands
    where the first one did. The row keeps `tinted_row`'s surface and gains a ``tone``
    border plus the usual hover and press steps. Draw only text inside it, the action's
    name included: the row already owns the click.

    Parameters
    ----------
    label
        ImGui label for the row's button, normally ID-only (``"##stop"``).
    tone
        Semantic colour of the state, for the tint and the border.
    height
        Row height in scaled pixels.

    Yields
    ------
    tuple[bool, float]
        Whether the row was clicked this frame, and the inner width for its text.
    """
    cursor = imgui.get_cursor_pos()
    width = imgui.get_content_region_avail().x
    surface = _tinted(tone)
    imgui.push_style_color(imgui.Col_.button, surface)
    imgui.push_style_color(imgui.Col_.button_hovered, _lighten(surface, 0.06))
    imgui.push_style_color(imgui.Col_.button_active, _lighten(surface, 0.10))
    imgui.push_style_color(imgui.Col_.border, tone)
    imgui.push_style_var(imgui.StyleVar_.frame_border_size, ui_px(2))
    try:
        clicked = imgui.button(label, imgui.ImVec2(width, height))
    finally:
        imgui.pop_style_var()
        imgui.pop_style_color(4)
    pad = ui_px(4)
    imgui.set_cursor_pos(cursor)
    imgui.begin_group()
    imgui.indent(pad)
    imgui.set_cursor_pos_y(cursor.y + pad)
    try:
        yield clicked, max(1.0, width - 2 * pad)
    finally:
        imgui.unindent(pad)
        imgui.set_cursor_pos(imgui.ImVec2(cursor.x, cursor.y + height))
        imgui.dummy(imgui.ImVec2(width, 0))
        imgui.end_group()


@contextmanager
def solid_fill(fill: imgui.ImVec4) -> Iterator[None]:
    """Give the buttons drawn inside one solid ``fill`` with white text.

    Hover and press lighten the fill by 6 % and 10 %, the same steps for every
    filled action, so they all answer the pointer alike.
    """
    imgui.push_style_color(imgui.Col_.text, ON_PRIMARY_TEXT)
    imgui.push_style_color(imgui.Col_.button, fill)
    imgui.push_style_color(imgui.Col_.button_hovered, _lighten(fill, 0.06))
    imgui.push_style_color(imgui.Col_.button_active, _lighten(fill, 0.10))
    try:
        yield
    finally:
        imgui.pop_style_color(4)


def primary_button(label: str, size: tuple[float, float] = (0, 0)) -> bool:
    """Draw the primary forward action with white text on a blue fill.

    Parameters
    ----------
    label : str
        Button text, optionally including an ImGui ID suffix.
    size : tuple[float, float], optional
        ImGui button size, by default ``(0, 0)`` to fit the label. Pass fixed
        pixel dimensions through ``ui_px`` before calling.

    Returns
    -------
    bool
        Whether the button was clicked this frame.
    """
    with solid_fill(PRIMARY_FILL):
        return imgui.button(label, imgui.ImVec2(*size))


def destructive_button(label: str, *, tooltip: str = "") -> bool:
    """A button that destroys something, red only while the pointer is on it.

    A grey button beside `Add` gives a delete the same weight; a permanently red one in
    every row of a list turns the list into an alarm. So `DANGER` arrives on hover only.

    Parameters
    ----------
    label
        Button text. Icon-plus-label is `f"{icon}  Label"`; a bare glyph is fine for a
        row-level remove, where the tooltip carries the meaning.
    tooltip
        Shown on hover, saying *what* is about to be destroyed. Required in practice
        whenever the label is a bare glyph.
    """
    imgui.push_style_color(imgui.Col_.button_hovered, DANGER)
    imgui.push_style_color(imgui.Col_.button_active, DANGER)
    clicked = imgui.button(label)
    imgui.pop_style_color(2)
    if tooltip and not clicked and imgui.is_item_hovered():
        imgui.set_tooltip(tooltip)
    return clicked


def label_column(
    label: str,
    among: Sequence[str],
    *,
    reserve: float = 0.0,
    max_width: float = 0.0,
    min_item_width: float = 90.0,
) -> float:
    """Draw `label` to the left of the next widget, and return the width to give it.

    ImGui draws a widget's own label *after* the widget, and that label is not covered by
    `set_next_item_width` — so a row of default-width widgets is wider than its window, and
    widening the window makes it worse. Hide the native label (`"##id"`) and draw a real one
    first, which also gives the reading order ``Name [ ]`` rather than ``[ ] Name``.

    Aligned into a column while a usable field still fits, otherwise the label goes on its
    own line above a full-width one.

    The width is set on the next item *and* returned, for the callers that need the number
    rather than the side effect (a combo that takes its own ``width=``).

    Parameters
    ----------
    label
        The text to draw.
    among
        Every label in the group, so one column width serves all of them and their fields
        line up. Pass ``(label,)`` when it stands alone.
    reserve
        Pixels to keep free at the right, for a value drawn *after* the field.
    max_width
        Cap on the field, ``0`` for none. A field does not need to grow to 1600 px.
    min_item_width
        Below this the row stacks rather than shrinking further.

    Notes
    -----
    The gap after the label is spacing passed to `imgui.same_line`, never the absolute
    ``offset_from_start_x`` form: that form measures from the window edge and ignores
    `imgui.indent`, so inside an indented block it lands the field on top of the label.
    """
    style = imgui.get_style()
    gap = style.item_spacing.x * 3.0
    column = max(imgui.calc_text_size(text).x for text in among) + gap
    avail = imgui.get_content_region_avail().x
    room = avail - column - reserve
    if room < min_item_width:
        imgui.text(label)  # label above, full-width field below
        width = avail - reserve
    else:
        imgui.align_text_to_frame_padding()  # or the label sits above the field's baseline
        imgui.text(label)
        imgui.same_line(0.0, max(column - imgui.calc_text_size(label).x, style.item_spacing.x))
        width = room
    if max_width > 0.0:
        width = min(width, max_width)
    imgui.set_next_item_width(width)
    return width


def segmented(widget_id: str, options: list[str], selected: int) -> int:
    """Render a macOS-style segmented control; return the selected index.

    A tight row of segments where the active one is a raised chip and the rest
    are flat with secondary-coloured text — use it in place of a cycle button so
    every option is visible at once. ``selected`` is the current index; the
    return value is the new index (changed on click).
    """
    style = imgui.get_style()
    chip = style.color_(imgui.Col_.button_hovered)
    prim = style.color_(imgui.Col_.text)
    dim = style.color_(imgui.Col_.text_disabled)
    clear = imgui.ImVec4(0.0, 0.0, 0.0, 0.0)
    result = selected
    imgui.push_style_var(imgui.StyleVar_.item_spacing, imgui.ImVec2(2.0, style.item_spacing.y))
    for i, opt in enumerate(options):
        if i > 0:
            imgui.same_line()
        on = i == selected
        imgui.push_style_color(imgui.Col_.button, chip if on else clear)
        imgui.push_style_color(imgui.Col_.button_hovered, chip)
        imgui.push_style_color(imgui.Col_.button_active, chip)
        imgui.push_style_color(imgui.Col_.text, prim if on else dim)
        if imgui.button(f"{opt}##{widget_id}_seg{i}"):
            result = i
        imgui.pop_style_color(4)
    imgui.pop_style_var()
    return result


@dataclass(frozen=True)
class CarouselItem:
    """One card of a [`carousel`][]: a title over a one-line mono detail.

    ``tag`` is a muted note after the title, such as "this app's"; ``tone``
    colours the detail, which is muted by default.
    """

    title: str
    detail: str = ""
    tag: str = ""
    tone: imgui.ImVec4 | None = None


def carousel(
    widget_id: str,
    items: Sequence[CarouselItem],
    index: int,
    *,
    can_look: bool = False,
    noun: str = "item",
    width: float | None = None,
) -> tuple[int, bool]:
    """Pick one of a few found things, a card at a time: ‹ card ›, then dots and refresh.

    For a choice whose card is what the action beneath it uses — a stream, a
    bracelet — so that action can name it: **Connect Galvani**, never a bare
    Connect beside a list. Stepping past the last card asks to look for more, and
    so does the refresh icon; nothing looks on its own. Dots and ``n / N`` appear
    once there is more than one card.

    Parameters
    ----------
    widget_id
        ImGui identity: the arrows are ``##<id>_prev`` / ``##<id>_next`` and the
        refresh ``##<id>_rescan``.
    items
        The cards. Pass a placeholder card for "nothing found yet".
    index
        The card shown this frame.
    can_look
        Whether looking for more is possible now — false while a scan runs.
    noun
        What the cards are, for the tooltips ("Next bracelet").
    width
        Width in pixels from the cursor; the available width by default.

    Returns
    -------
    tuple[int, bool]
        The card to show next, and whether the refresh icon was pressed. An index
        one past the last card means › was pressed there: look for more, and show
        the next card once it arrives.
    """
    items = list(items) or [CarouselItem("—")]
    index = min(max(index, 0), len(items) - 1)
    style = imgui.get_style()
    width = imgui.get_content_region_avail().x if width is None else width
    left = imgui.get_cursor_pos_x()
    card_h = 2 * imgui.get_text_line_height() + ui_px(14)
    gap = style.item_spacing.x * 0.5
    arrow_w = ui_px(28)
    card_w = max(1.0, width - 2 * (arrow_w + gap))

    imgui.begin_disabled(index == 0)
    if imgui.button(f"{fa.ICON_FA_CHEVRON_LEFT}##{widget_id}_prev", imgui.ImVec2(arrow_w, card_h)):
        index -= 1
    imgui.end_disabled()
    imgui.set_item_tooltip(f"Previous {noun}")
    imgui.same_line(0, gap)
    origin = imgui.get_cursor_screen_pos()
    imgui.dummy(imgui.ImVec2(card_w, card_h))
    _carousel_card(items[index], origin, card_w, card_h)
    imgui.same_line(0, gap)
    more = index < len(items) - 1
    imgui.begin_disabled(not more and not can_look)
    if imgui.button(f"{fa.ICON_FA_CHEVRON_RIGHT}##{widget_id}_next", imgui.ImVec2(arrow_w, card_h)):
        index += 1
    imgui.end_disabled()
    imgui.set_item_tooltip(f"Next {noun}" if more else f"Look for another {noun}")

    # Dots, n / N, and refresh, centred under the card.
    count = len(items)
    dot, spacing = ui_px(3), ui_px(10)
    position = f"{min(index, count - 1) + 1} / {count}" if count > 1 else ""
    refresh_w = imgui.calc_text_size(fa.ICON_FA_ARROWS_ROTATE).x + 2 * style.frame_padding.x
    dots_w = (count - 1) * spacing + 2 * dot if count > 1 else 0.0
    text_w = imgui.calc_text_size(position).x if position else 0.0
    row_w = dots_w + (spacing + text_w if position else 0.0) + spacing + refresh_w
    imgui.set_cursor_pos_x(left + max((width - row_w) * 0.5, 0.0))
    row = imgui.get_cursor_screen_pos()
    middle = row.y + imgui.get_frame_height() * 0.5
    draw = imgui.get_window_draw_list()
    for i in range(count if count > 1 else 0):
        # The current dot in full text colour, the rest at a third of the muted one.
        color = (
            imgui.get_color_u32(imgui.Col_.text)
            if i == index
            else imgui.get_color_u32(imgui.Col_.text_disabled, 0.35)
        )
        draw.add_circle_filled(imgui.ImVec2(row.x + dot + i * spacing, middle), dot, color)
    imgui.dummy(imgui.ImVec2(dots_w, imgui.get_frame_height()))
    if position:
        imgui.same_line(0, spacing)
        imgui.align_text_to_frame_padding()
        imgui.text_colored(muted(), position)
    imgui.same_line(0, spacing)
    imgui.begin_disabled(not can_look)
    refresh = imgui.button(f"{fa.ICON_FA_ARROWS_ROTATE}##{widget_id}_rescan")
    imgui.end_disabled()
    imgui.set_item_tooltip("Look again")
    return index, refresh


def _carousel_card(item: CarouselItem, origin: imgui.ImVec2, width: float, height: float) -> None:
    """The card on show: its title and tag over its mono detail, raised and outlined."""
    style = imgui.get_style()
    draw = imgui.get_window_draw_list()
    lo, hi = origin, imgui.ImVec2(origin.x + width, origin.y + height)
    draw.add_rect_filled(lo, hi, imgui.get_color_u32(imgui.Col_.frame_bg), style.frame_rounding)
    draw.add_rect(lo, hi, imgui.get_color_u32(hairline()), style.frame_rounding)
    room = width - 2 * style.frame_padding.x
    tag = f"  {item.tag}" if item.tag else ""
    title = fit_text(item.title, max(1.0, room - imgui.calc_text_size(tag).x))
    line = imgui.get_text_line_height()
    top = lo.y + (height - (2 * line + ui_px(3) if item.detail else line)) * 0.5
    title_w, tag_w = imgui.calc_text_size(title).x, imgui.calc_text_size(tag).x
    x = lo.x + (width - title_w - tag_w) * 0.5
    draw.add_text(imgui.ImVec2(x, top), imgui.get_color_u32(imgui.Col_.text), title)
    if tag:
        draw.add_text(imgui.ImVec2(x + title_w, top), imgui.get_color_u32(muted()), tag)
    if item.detail:
        font = mono_font() or imgui.get_font()
        imgui.push_font(font, style.font_size_base)
        detail = fit_text(item.detail, room)
        detail_w = imgui.calc_text_size(detail).x
        imgui.pop_font()
        draw.add_text(
            font,
            imgui.get_font_size(),
            imgui.ImVec2(lo.x + (width - detail_w) * 0.5, top + line + ui_px(3)),
            imgui.get_color_u32(item.tone if item.tone is not None else muted()),
            detail,
        )


#: Every band of `format_age` is this many characters, so the read-out holds a
#: constant width in the mono face and stops shuffling while you watch it.
_AGE_WIDTH = 11


def format_age(seconds: float | None) -> str:
    """Age of a stream's newest sample, at a fixed width.

    ``last   9 ms`` / ``last 999 ms`` / ``last  1.4 s`` / ``last  >99 s`` — all
    11 characters, so paired with `mono_text` the value can update every frame
    without the text around it moving.

    Padding to a fixed *digit count* is not enough on its own. The UI face is
    proportional and its digits are not tabular: on macOS, SF Pro renders ``1``
    at 6 px and ``9`` at 9 px, so ``last 111 ms`` and ``last 999 ms`` differ by
    9 px however they are padded. Only a monospaced face holds still.
    """
    if seconds is None:
        return "last   — ms"
    ms = seconds * 1000.0
    if ms < 999.5:
        return f"last {ms:3.0f} ms"
    if seconds < 99.95:
        return f"last {seconds:4.1f} s"
    return "last  >99 s"


def mono_text(text: str, color: imgui.ImVec4 | None = None) -> None:
    """Draw ``text`` in the mono face — for a value that changes as you watch it.

    Falls back to the UI face when the mono one could not be loaded, which costs
    only the alignment.
    """
    font = mono_font()
    if font is not None:
        imgui.push_font(font, imgui.get_style().font_size_base)
    if color is None:
        imgui.text_unformatted(text)
    else:
        imgui.text_colored(color, text)
    if font is not None:
        imgui.pop_font()


def panel_header(
    title: str,
    icon: str | None = None,
    *,
    reserve: float = 0.0,
    status: imgui.ImVec4 | None = None,
) -> None:
    """Render a uniform panel-header line: muted, all-caps, optional FA icon.

    Pairs with the button + slider styling used by the other widgets in this
    package. Use it at the top of any custom panel to match the look::

        panel_header("MODEL", icons_fontawesome_6.ICON_FA_BRAIN)
        train_button(pipeline)
        ...

    When the panel is too narrow for the full title, the title is truncated
    with a ``…`` ellipsis; when there is no room for any label, only the icon
    is shown. Pass ``reserve`` to leave that many pixels for controls placed
    after the header on the same row (e.g. a right-aligned button), so the
    *title* collapses instead of pushing those controls off the panel.

    Pass ``status`` — one of `SUCCESS`, `IDLE`, `DANGER`, `WARNING` — to put a filled
    circle in that colour at the **right** end of the header row. Right-aligned so the
    titles of stacked panels line up on their first glyph: a dot before the title would
    indent the ones that have state and leave the ones that don't hanging. Colour is the
    *only* thing the dot carries, so it must not be the only place the state is
    available: give the header a tooltip with the detail (a PID, an exit code) for
    anyone who cannot read the hue.

    It sits inside ``reserve``, so a right-aligned control placed after the header —
    `panel_header_button` does this — still gets its space, with the dot to its left.

    Examples
    --------
    >>> from myogestic.widgets import panel_header
    >>> panel_header("MODEL")
    """
    style = imgui.get_style()
    dot_w = imgui.calc_text_size(fa.ICON_FA_CIRCLE).x if status is not None else 0.0
    # The header sits in its own band, inset from the panel's content box on
    # every side rather than starting in its corner. Text sits high in its line
    # box, so `window_padding` alone leaves the glyphs looking closer to the
    # border than the number suggests. Deliberately *not* flush with the
    # controls below: the title is a label for the panel, not the first row of
    # it. Not paired with a trailing `spacing()` either — `panel_header_button`
    # does `same_line()` straight after this and would land beside the spacer
    # instead of beside the title.
    inset = style.item_spacing.x
    imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + style.item_spacing.y)
    imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + inset)
    # Grouped so the dot and the title are one item for hit-testing: a following
    # `set_item_tooltip` would otherwise attach to the title text alone, leaving the dot
    # — the part whose colour needs explaining — unhoverable.
    imgui.begin_group()
    muted = style.color_(imgui.Col_.text_disabled)
    imgui.push_style_color(imgui.Col_.text, muted)
    # The title truncates against the dot's space as well as the caller's `reserve`,
    # so a long title yields to the state rather than pushing it off the row.
    gap = style.item_spacing.x if status is not None else 0.0
    imgui.text(_fit_header(title.upper(), icon, reserve + dot_w + gap + inset))
    imgui.pop_style_color()
    if status is not None:
        imgui.same_line()
        shift = imgui.get_content_region_avail().x - reserve - dot_w - inset
        if shift > 0:
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + shift)
        imgui.text_colored(status, fa.ICON_FA_CIRCLE)
    imgui.end_group()


def _fit_header(label: str, icon: str | None, reserve: float) -> str:
    """Fit ``icon + label`` into the available width.

    Returns the full string if it fits; otherwise the label truncated with an
    ellipsis; otherwise (too narrow for any label) just the icon.
    """
    avail = imgui.get_content_region_avail().x - reserve
    prefix = f"{icon}  " if icon else ""
    if imgui.calc_text_size(prefix + label).x <= avail:
        return prefix + label
    if icon is not None and imgui.calc_text_size(f"{icon}  {label[:1]}{_ELLIPSIS}").x > avail:
        return icon
    budget = avail - imgui.calc_text_size(prefix + _ELLIPSIS).x
    return prefix + _truncate_to_width(label, budget) + _ELLIPSIS


def _truncate_to_width(s: str, budget: float) -> str:
    """Longest prefix of ``s`` whose rendered width fits ``budget`` pixels."""
    if budget <= 0:
        return ""
    while s and imgui.calc_text_size(s).x > budget:
        s = s[:-1]
    return s


def panel_header_button(
    title: str, icon: str | None, button_icon: str, *, tooltip: str = ""
) -> bool:
    """Render a [`panel_header`][] with a right-aligned icon-only button.

    Returns ``True`` on the frame the button is clicked. The button is
    prioritized: when the row can't fit the header icon + button side by side
    it drops to its own line below the (icon-only) header.
    """
    style = imgui.get_style()
    sp = style.item_spacing.x
    btn_w = imgui.calc_text_size(button_icon).x + style.frame_padding.x * 2
    icon_w = imgui.calc_text_size(icon).x if icon else 0.0
    inline = imgui.get_content_region_avail().x >= icon_w + sp + btn_w
    panel_header(title, icon, reserve=(btn_w + sp) if inline else 0.0)
    if inline:
        imgui.same_line()
        avail = imgui.get_content_region_avail().x
        if avail > btn_w:
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + (avail - btn_w))
    # else: the button renders on the next line (no same_line), left-aligned.
    clicked = imgui.small_button(f"{button_icon}##_panel_hdr_btn")
    if tooltip and imgui.is_item_hovered():
        imgui.set_tooltip(tooltip)
    return clicked


# Trial-region overlay: translucent blue keeps traces legible in both themes.
TRIAL_BAND = imgui.ImVec4(INFO.x, INFO.y, INFO.z, 0.18)


def stream_chip(
    name: str,
    tone: imgui.ImVec4,
    *,
    selected: bool,
    prefix: str,
    left: float,
    right: float,
    first: bool = False,
    removable: bool = False,
    recording: bool = False,
    locked: bool = False,
    detail: str = "",
) -> tuple[bool, bool]:
    """Draw a wrapping stream chip shared by DevicePicker and StreamManager.

    Parameters
    ----------
    name, tone
        Mono stream name and semantic state dot.
    selected
        Whether to draw the persistent selection cue.
    prefix
        ID prefix within the calling widget's ImGui scope.
    left, right
        Available row bounds in local window coordinates.
    first
        Start a row instead of trying to follow the previous chip.
    removable
        Offer a destructive remove action beside this chip.
    recording
        Disable removal and explain why on hover.
    locked
        Dim and disable selection as well as removal.
    detail
        Full state text for the chip's tooltip.

    Returns
    -------
    tuple[bool, bool]
        Whether selection or removal was requested. Apply removal after the
        caller finishes iterating its streams.
    """
    style = imgui.get_style()
    remove_w = (
        (
            imgui.calc_text_size(fa.ICON_FA_XMARK).x
            + 2 * style.frame_padding.x
            + style.item_spacing.x
        )
        if removable
        else 0.0
    )
    font = mono_font()
    if font is not None:
        imgui.push_font(font, style.font_size_base)
    shown = name
    dot_w = imgui.get_font_size() + style.item_spacing.x
    limit = max(1.0, right - left - remove_w)
    while shown and imgui.calc_text_size(shown + "…").x + dot_w + 2 * style.frame_padding.x > limit:
        shown = shown[:-1]
    if shown != name:
        shown += "…"
    width = min(limit, imgui.calc_text_size(shown).x + dot_w + 2 * style.frame_padding.x)
    if not first:
        imgui.same_line()
        if imgui.get_cursor_pos_x() + width + remove_w > right:
            imgui.new_line()
    imgui.push_style_var(imgui.StyleVar_.frame_rounding, imgui.get_frame_height() * 0.5)
    imgui.begin_disabled(locked)
    if selected:
        push_selected()
    clicked = imgui.button(f"##{prefix}_stream_{name}", imgui.ImVec2(width, 0))
    if selected:
        pop_selected()
    origin = imgui.get_item_rect_min()
    draw = imgui.get_window_draw_list()
    draw.add_text(
        imgui.ImVec2(origin.x + style.frame_padding.x + dot_w, origin.y + style.frame_padding.y),
        imgui.get_color_u32(imgui.Col_.text),
        shown,
    )
    if font is not None:
        imgui.pop_font()
    draw.add_text(
        imgui.ImVec2(origin.x + style.frame_padding.x, origin.y + style.frame_padding.y),
        imgui.get_color_u32(tone),
        fa.ICON_FA_CIRCLE,
    )
    imgui.set_item_tooltip(f"{name}: {detail}")
    remove = False
    if removable:
        imgui.same_line()
        imgui.begin_disabled(recording)
        remove = destructive_button(f"{fa.ICON_FA_XMARK}##{prefix}_remove_{name}")
        imgui.end_disabled()
        if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
            imgui.set_tooltip(
                "Stop the recording before removing a stream."
                if recording
                else f"Remove stream {name!r}."
            )
    imgui.end_disabled()
    imgui.pop_style_var()
    return clicked and not locked, remove and not recording and not locked


def ensure_implot3d_style() -> None:
    """Apply theme-aware plot surfaces and a faint grid to the current 3D context.

    Resolve colours each frame so changing theme or recreating the plotting
    context cannot leave a stale dark background behind.
    """
    from imgui_bundle import implot3d

    style = implot3d.get_style()
    clear = imgui.ImVec4(0.0, 0.0, 0.0, 0.0)
    for slot in (implot3d.Col_.frame_bg, implot3d.Col_.plot_bg, implot3d.Col_.plot_border):
        style.set_color(slot, clear)
    style.set_color(implot3d.Col_.axis_grid, hairline(0.5))
    style.set_color(implot3d.Col_.axis_text, muted())
    style.set_color(implot3d.Col_.axis_tick, hairline())
    style.set_color(implot3d.Col_.inlay_text, primary())


def plot_size(size: tuple[float, float], *, footer: float = 0.0) -> imgui.ImVec2:
    """Scale explicit plot pixels, preserving fill width and reserving a fill footer.

    Positive heights describe the plot alone. Nonpositive heights fill the
    available space after the legend or footer, with negative values retaining
    their ImGui-style bottom inset.
    """
    width, height = size
    return imgui.ImVec2(
        ui_px(width) if width > 0 else width,
        ui_px(height)
        if height > 0
        else max(ui_px(40), imgui.get_content_region_avail().y + height - footer),
    )


def fit_text(text: str, width: float) -> str:
    """Ellipsize a single line to ``width`` in the current font."""
    if imgui.calc_text_size(text).x <= width:
        return text
    return _truncate_to_width(text, width - imgui.calc_text_size(_ELLIPSIS).x) + _ELLIPSIS


def plot_empty(title: str, hint: str, size: tuple[float, float]) -> None:
    """Centre an actionable empty state in the plot's allotted space."""
    height = plot_size(size).y
    left, top = imgui.get_cursor_pos_x(), imgui.get_cursor_pos_y()
    width = imgui.get_content_region_avail().x
    row = imgui.get_text_line_height_with_spacing()
    imgui.set_cursor_pos_y(top + max(0.0, (height - 2 * row) * 0.5))
    for text in (title, hint):
        clipped = fit_text(text, width)
        imgui.set_cursor_pos_x(left + max(0.0, (width - imgui.calc_text_size(clipped).x) * 0.5))
        imgui.text_colored(muted(), clipped)
        if clipped != text:
            imgui.set_item_tooltip(text)
    imgui.set_cursor_pos_y(max(imgui.get_cursor_pos_y(), top + height))
    imgui.set_cursor_pos_x(left)
    imgui.dummy(imgui.ImVec2(0, 0))


def plot_legend(
    series: Sequence[tuple[int, str]],
    *,
    selected: set[int] | None = None,
    measure_only: bool = False,
) -> float:
    """Draw wrapping PALETTE-dot chips, or measure their height before a fill plot.

    Parameters
    ----------
    series
        Stable categorical indices and their visible names. Long names are
        ellipsized with the complete value available in a tooltip.
    selected
        If supplied, turn the chips into channel toggles and update this set
        on clicks. The selected cue is a theme tint, never a PALETTE fill.
    measure_only
        Measure using the same font and row layout without drawing any items.

    Returns
    -------
    float
        Occupied height, including the trailing item spacing.
    """
    if not series:
        return 0.0
    font = mono_font()
    if font is not None:
        imgui.push_font(font, imgui.get_style().font_size_base)
    try:
        style = imgui.get_style()
        width = max(1.0, imgui.get_content_region_avail().x)
        dot = ui_px(6)
        inset = style.frame_padding.x
        prefix = dot + ui_px(6)
        height = imgui.get_frame_height()
        used, rows = 0.0, 1
        for index, name in series:
            chip_width = min(width, imgui.calc_text_size(name).x + prefix + 2 * inset)
            wrap = used > 0 and used + style.item_spacing.x + chip_width > width
            if wrap:
                rows += 1
                used = 0.0
            if not measure_only:
                if used > 0:
                    imgui.same_line()
                on = selected is not None and index in selected
                if on:
                    push_selected()
                clicked = imgui.button(f"##series{index}", imgui.ImVec2(chip_width, height))
                if on:
                    pop_selected()
                if clicked and selected is not None:
                    if on:
                        selected.discard(index)
                    else:
                        selected.add(index)
                p = imgui.get_item_rect_min()
                draw = imgui.get_window_draw_list()
                color = PALETTE[index % len(PALETTE)]
                draw.add_circle_filled(
                    imgui.ImVec2(p.x + inset + dot * 0.5, p.y + height * 0.5),
                    dot * 0.5,
                    imgui.get_color_u32(imgui.ImVec4(*map(float, color), 1.0)),
                )
                label = fit_text(name, max(0.0, chip_width - prefix - 2 * inset))
                draw.add_text(
                    imgui.ImVec2(p.x + inset + prefix, p.y + style.frame_padding.y),
                    imgui.get_color_u32(primary()),
                    label,
                )
                imgui.set_item_tooltip(name)
            used += (style.item_spacing.x if used > 0 else 0.0) + chip_width
        return rows * (height + style.item_spacing.y)
    finally:
        if font is not None:
            imgui.pop_font()
