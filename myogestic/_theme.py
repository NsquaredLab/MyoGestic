from __future__ import annotations

import math
import os
import platform
import subprocess

from imgui_bundle import hello_imgui, imgui

from myogestic import _scale
from myogestic._scale import set_ui_scale  # noqa: F401  (re-exported for App)

_FONT: imgui.ImFont | None = None
_DISPLAY_FONT: imgui.ImFont | None = None  # Instrument Serif — hero/display text
_MONO_FONT: imgui.ImFont | None = None  # IBM Plex Mono — console / logs
_IS_MAC = platform.system() == "Darwin"


def _rgba(r: int, g: int, b: int, a: int = 255) -> imgui.ImVec4:
    return imgui.ImVec4(r / 255, g / 255, b / 255, a / 255)


def _is_mac_dark() -> bool:
    if not _IS_MAC:
        return True
    # `defaults read` exits non-zero (empty stdout) in Light mode, where the
    # AppleInterfaceStyle key is absent — so absence ⇒ not dark.
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.stdout.strip() == "Dark"


def apply_theme() -> None:
    hello_imgui.imgui_default_settings.setup_default_imgui_style()
    style = imgui.get_style()

    # macOS control metrics: NSButton bezel ~5px, slightly tighter spacing.
    # Radii follow a decrease-inward rule (container >= control) and a 4/8 rhythm.
    style.window_rounding = 10.0  # forced to 0 on desktop by the viewport tweak
    style.child_rounding = 8.0
    style.frame_rounding = 6.0
    style.grab_rounding = 6.0
    style.popup_rounding = 8.0
    style.scrollbar_rounding = 6.0
    style.tab_rounding = 6.0
    # The box's inner padding, and the only thing keeping a full-width control
    # (`set_next_item_width(-1)`, a `(-1, 0)` button) off the panel border. It
    # applies to every container — the main window, a bordered `Grid` cell, a
    # popped-out panel — so a panel breathes the same wherever it is drawn.
    style.window_padding = imgui.ImVec2(18, 16)
    style.frame_padding = imgui.ImVec2(10, 6)
    style.item_spacing = imgui.ImVec2(8, 8)
    style.item_inner_spacing = imgui.ImVec2(6, 4)
    style.scrollbar_size = 12.0
    style.grab_min_size = 10.0
    style.window_border_size = 0.0
    style.frame_border_size = 0.0
    style.child_border_size = 1.0
    style.disabled_alpha = 0.45  # disabled controls recede but stay legible

    dark = _is_mac_dark()
    if dark:
        accent = _rgba(10, 132, 255)  # systemBlue (dark)
        accent_hi = _rgba(64, 156, 255)
        text = _rgba(255, 255, 255)
        text_dim = _rgba(235, 235, 245, 153)  # secondaryLabel
        # Surface ladder (depth from tone, not lines): each level a step lighter
        # as it comes forward — canvas < card < raised < control.
        window_bg = _rgba(28, 28, 30)  # canvas (systemGray6 dark)
        child_bg = _rgba(36, 36, 38)  # panels / cards, raised a step above canvas
        raised = _rgba(44, 44, 46)  # popups / menus / table headers (a further step)
        control_bg = _rgba(58, 58, 60, 235)  # systemGray5 dark — buttons / inputs
        control_hi = _rgba(72, 72, 74)  # hover, and neutral pressed
        border = _rgba(84, 84, 88, 128)  # separator
        header = _rgba(99, 99, 102, 90)
        row_alt = _rgba(255, 255, 255, 6)  # zebra row (~2.5% white)
        table_line = _rgba(255, 255, 255, 16)  # light table rule (~6% white)
        sel_text_bg = _rgba(10, 132, 255, 90)  # text selection (accent @ .35)
        link = _rgba(100, 181, 255)
        modal_dim = _rgba(0, 0, 0, 158)  # modal backdrop (~.62)
        dock_prev = _rgba(10, 132, 255, 76)  # docking drop preview (accent @ .30)
    else:
        accent = _rgba(0, 122, 255)
        accent_hi = _rgba(64, 156, 255)
        text = _rgba(0, 0, 0)
        text_dim = _rgba(60, 60, 67, 199)
        window_bg = _rgba(243, 244, 246)  # canvas
        child_bg = _rgba(255, 255, 255)  # cards sit above the canvas
        raised = _rgba(255, 255, 255)
        control_bg = _rgba(235, 235, 240)
        control_hi = _rgba(220, 220, 225)
        border = _rgba(198, 198, 200)
        header = _rgba(210, 210, 215)
        row_alt = _rgba(0, 0, 0, 6)
        table_line = _rgba(0, 0, 0, 16)
        sel_text_bg = _rgba(0, 122, 255, 80)
        link = _rgba(0, 100, 210)
        modal_dim = _rgba(0, 0, 0, 90)
        dock_prev = _rgba(0, 122, 255, 76)

    colors = {
        imgui.Col_.text: text,
        imgui.Col_.text_disabled: text_dim,
        imgui.Col_.window_bg: window_bg,
        imgui.Col_.child_bg: child_bg,
        imgui.Col_.popup_bg: raised,
        imgui.Col_.border: border,
        imgui.Col_.frame_bg: control_bg,
        imgui.Col_.frame_bg_hovered: control_hi,
        imgui.Col_.frame_bg_active: control_hi,
        imgui.Col_.title_bg: window_bg,
        imgui.Col_.title_bg_active: child_bg,
        imgui.Col_.title_bg_collapsed: window_bg,
        imgui.Col_.menu_bar_bg: window_bg,
        imgui.Col_.scrollbar_bg: window_bg,
        imgui.Col_.scrollbar_grab: control_bg,
        imgui.Col_.scrollbar_grab_hovered: control_hi,
        imgui.Col_.scrollbar_grab_active: accent,
        imgui.Col_.check_mark: accent,
        imgui.Col_.slider_grab: accent,
        imgui.Col_.slider_grab_active: accent_hi,
        imgui.Col_.button: control_bg,
        imgui.Col_.button_hovered: control_hi,
        # Neutral pressed: accent is reserved for selection / primary action / focus.
        imgui.Col_.button_active: control_hi,
        imgui.Col_.header: header,
        imgui.Col_.header_hovered: control_hi,
        imgui.Col_.header_active: accent,
        imgui.Col_.separator: border,
        imgui.Col_.separator_hovered: accent,
        imgui.Col_.separator_active: accent,
        imgui.Col_.resize_grip: border,
        imgui.Col_.resize_grip_hovered: accent,
        imgui.Col_.resize_grip_active: accent_hi,
        imgui.Col_.tab: control_bg,
        imgui.Col_.tab_hovered: control_hi,
        imgui.Col_.plot_lines: accent,
        imgui.Col_.plot_histogram: accent,
        # Slots HelloImGui otherwise leaves at stock defaults, which leak a foreign
        # blue-gray into tables, tabs, text selection, nav focus and docking.
        imgui.Col_.tab_selected: control_hi,
        imgui.Col_.tab_selected_overline: accent,
        imgui.Col_.tab_dimmed: control_bg,
        imgui.Col_.tab_dimmed_selected: control_hi,
        imgui.Col_.table_header_bg: raised,
        imgui.Col_.table_row_bg: window_bg,
        imgui.Col_.table_row_bg_alt: row_alt,
        imgui.Col_.table_border_strong: border,
        imgui.Col_.table_border_light: table_line,
        imgui.Col_.text_selected_bg: sel_text_bg,
        imgui.Col_.nav_cursor: accent_hi,
        imgui.Col_.modal_window_dim_bg: modal_dim,
        imgui.Col_.docking_preview: dock_prev,
        imgui.Col_.docking_empty_bg: window_bg,
        imgui.Col_.text_link: link,
    }
    for key, value in colors.items():
        style.set_color_(key, value)

    # Unscaled on purpose: `apply_live_scale` scales metrics and fonts every time
    # the scale changes, after the whole style chain has run.


_SYS_FONTS = {
    "Darwin": "/System/Library/Fonts/SFNS.ttf",
    "Windows": "C:/Windows/Fonts/segoeui.ttf",
    "Linux": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
}


def _unscaled_params() -> hello_imgui.FontLoadingParams:
    params = hello_imgui.FontLoadingParams()
    params.adjust_size_to_dpi = False
    return params


def load_fonts() -> None:
    global _FONT, _DISPLAY_FONT, _MONO_FONT
    if _FONT is not None:
        return

    sys_font = _SYS_FONTS.get(platform.system())
    # Unscaled sizes, and no DPI adjustment from hello_imgui: `apply_live_scale`
    # sets `style.font_scale_main`, which already carries the OS display scale.
    # ImGui 1.92 rasterises glyphs at the size they are drawn, so this stays crisp.
    size = 14.0

    params = _unscaled_params()
    if sys_font and os.path.exists(sys_font):
        params.inside_assets = False
        _FONT = hello_imgui.load_font(sys_font, size, params)
    else:
        _FONT = hello_imgui.load_font("fonts/Roboto/Roboto-Regular.ttf", size, params)
    # Merge Font Awesome 6 glyphs onto the body font
    fa_params = _unscaled_params()
    fa_params.merge_to_last_font = True
    hello_imgui.load_font("fonts/Font_Awesome_6_Free-Solid-900.otf", size, fa_params)

    # Instrument Serif (OFL) — display face for hero text. Best-effort: a missing
    # asset just falls back to the body font.
    try:
        _DISPLAY_FONT = hello_imgui.load_font(
            "fonts/InstrumentSerif-Regular.ttf", 28.0, _unscaled_params()
        )
    except Exception:  # noqa: BLE001
        _DISPLAY_FONT = None

    # IBM Plex Mono (OFL) — console face for log views. Same best-effort load.
    try:
        _MONO_FONT = hello_imgui.load_font(
            "fonts/IBMPlexMono-Regular.ttf", 13.0, _unscaled_params()
        )
    except Exception:  # noqa: BLE001
        _MONO_FONT = None

    imgui.get_io().font_default = _FONT


def display_font() -> imgui.ImFont | None:
    """Instrument Serif display face for hero text (``None`` if unavailable)."""
    return _DISPLAY_FONT


def mono_font() -> imgui.ImFont | None:
    """IBM Plex Mono face for console / log text (``None`` if unavailable)."""
    return _MONO_FONT


#: The scale the style was last built at, so a frame with an unchanged scale does
#: nothing. `None` until the first frame.
_styled_at: float | None = None


_BORDER_SIZES = tuple(
    name for name in dir(imgui.Style) if name.endswith("border_size") and not name.startswith("_")
)


def _os_scale() -> float:
    """The display scale picked in the OS, as a multiple of 96 DPI.

    The main viewport's `dpi_scale`: 1.5 for Windows at 150 %, where ImGui works in
    physical pixels. On a Retina Mac it is 1.0 — ImGui works in points there and
    the 2x lives only in the framebuffer, so it must not be counted again (measured:
    dpi_scale 1.0, framebuffer_scale 2.0 on macOS 26).
    """
    return imgui.get_main_viewport().dpi_scale


def apply_live_scale(setup_style) -> None:
    """Recompute the UI scale and restyle if it moved. Runs before every frame.

    Parameters
    ----------
    setup_style
        The app's full style chain (theme, viewport and docking tweaks). Re-run
        from scratch on a change because `scale_all_sizes` multiplies — applying
        it twice to the same style would compound.
    """
    global _styled_at
    os_scale = _os_scale()
    size = imgui.get_io().display_size
    # A sleeping/locked display can temporarily lose its DPI or dimensions.
    # Keep both the current scale and style until the display can be measured.
    if any(not math.isfinite(value) or value < 0.0 for value in (os_scale, size.x, size.y)):
        return
    if size.x == 0.0 or size.y == 0.0:
        return
    if os_scale == 0.0:
        # 0 means "unknown": keep the last scale, but a backend that never reports one
        # (headless, some browsers) still gets styled once at 1x.
        if _styled_at is not None:
            return
        os_scale = 1.0
    os_scale = max(0.5, os_scale)
    scale = _scale.update(os_scale, size.x / os_scale, size.y / os_scale)
    if scale == _styled_at:
        return
    _styled_at = scale
    # Theme setup only overwrites some metrics. Reset the entire style to ImGui's
    # unscaled defaults so every size (including ones added by ImGui) starts fresh.
    imgui.get_current_context().style = imgui.Style()
    setup_style()
    style = imgui.get_style()
    if scale != 1.0:
        # Borders are hairlines, not sizes: `scale_all_sizes` truncates them, so a
        # 1 px border at 0.85 becomes 0 — and a bordered child without its border
        # also loses its padding, leaving content flush against the cell edge.
        borders = {name: getattr(style, name) for name in _BORDER_SIZES}
        style.scale_all_sizes(scale)
        for name, value in borders.items():
            setattr(style, name, value)
    style.font_scale_main = scale


def reset_live_scale() -> None:
    """Forget the styled-at scale — a second `App` in the same process restyles."""
    global _styled_at
    _styled_at = None
    _scale.reset()
