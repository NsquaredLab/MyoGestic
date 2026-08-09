"""Shared constants and small visual helpers for widgets."""

from __future__ import annotations

import time
from collections.abc import Sequence

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui, implot

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
        imgui.ImVec2(p0.x + 3.0, y), imgui.ImVec2(p1.x - 3.0, p1.y), imgui.get_color_u32(_ACCENT), 1.0
    )


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
        imgui.push_font(font, imgui.get_font_size())
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


def panel_header_button(title: str, icon: str | None, button_icon: str, *, tooltip: str = "") -> bool:
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
