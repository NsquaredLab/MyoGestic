from __future__ import annotations

import os
import platform
import subprocess

from imgui_bundle import hello_imgui, imgui

_FONT: imgui.ImFont | None = None
_DISPLAY_FONT: imgui.ImFont | None = None  # Instrument Serif — hero/display text
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


# Programmatic UI-scale override, set by App(ui_scale=...). The
# $MYOGESTIC_UI_SCALE env var still wins over it — a per-machine display
# override should beat an example's hardcoded value.
_UI_SCALE_OVERRIDE: float | None = None


def set_ui_scale(scale: float | None) -> None:
    """Set the global UI scale programmatically — used by ``App(ui_scale=...)``.

    Call before the GUI loop starts. ``None`` clears the override (falls back
    to ``$MYOGESTIC_UI_SCALE`` then ``1.0``). The env var, when set, still
    takes precedence — a per-machine display override beats an example default.
    """
    global _UI_SCALE_OVERRIDE
    _UI_SCALE_OVERRIDE = scale


def _clamp_scale(scale: float) -> float:
    """Keep the UI scale in a sane range so a typo can't make the UI unusable."""
    return min(2.0, max(0.5, scale))


def _ui_scale() -> float:
    """Resolve the global UI scale: ``$MYOGESTIC_UI_SCALE`` > ``App(ui_scale=)`` > ``1.0``.

    Scales both the font size (``load_fonts``) and imgui's style metrics —
    padding, spacing, rounding (``apply_theme`` → ``scale_all_sizes``) — for
    displays where the default sizing is too large or small (e.g. a 14" MacBook).
    """
    raw = os.environ.get("MYOGESTIC_UI_SCALE", "").strip()
    if raw:
        try:
            return _clamp_scale(float(raw))
        except ValueError:
            pass
    if _UI_SCALE_OVERRIDE is not None:
        return _clamp_scale(_UI_SCALE_OVERRIDE)
    return 1.0


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
    style.window_padding = imgui.ImVec2(12, 12)
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
        text_dim = _rgba(60, 60, 67, 153)
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
        # Neutral pressed state — accent is reserved for selection / primary
        # action / focus, not a flash on every button press.
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
        # Fill the slots HelloImGui otherwise leaves at stock defaults, so
        # tables, tabs, text selection, nav focus and docking match the theme
        # instead of leaking a foreign blue-gray.
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

    # Global UI scale (opt-in via $MYOGESTIC_UI_SCALE). Applied last so it
    # scales the custom metrics set above; the font is scaled in load_fonts().
    scale = _ui_scale()
    if scale != 1.0:
        style.scale_all_sizes(scale)


_SYS_FONTS = {
    "Darwin": "/System/Library/Fonts/SFNS.ttf",
    "Windows": "C:/Windows/Fonts/segoeui.ttf",
    "Linux": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
}


def load_fonts() -> None:
    global _FONT, _DISPLAY_FONT
    if _FONT is not None:
        return

    sys_font = _SYS_FONTS.get(platform.system())
    size = 14.0 * _ui_scale()

    if sys_font and os.path.exists(sys_font):
        params = hello_imgui.FontLoadingParams()
        params.inside_assets = False
        _FONT = hello_imgui.load_font(sys_font, size, params)
        # Merge Font Awesome 6 glyphs onto the system font
        fa_params = hello_imgui.FontLoadingParams()
        fa_params.merge_to_last_font = True
        hello_imgui.load_font("fonts/Font_Awesome_6_Free-Solid-900.otf", size, fa_params)
    else:
        _FONT = hello_imgui.load_font_ttf_with_font_awesome_icons(
            "fonts/Roboto/Roboto-Regular.ttf", size
        )

    # Instrument Serif (OFL) — a display face for hero text (the prediction
    # readout). Found in myogestic/assets/fonts via the asset search path;
    # best-effort, so a missing asset just falls back to the body font.
    try:
        _DISPLAY_FONT = hello_imgui.load_font(
            "fonts/InstrumentSerif-Regular.ttf", 28.0 * _ui_scale(), hello_imgui.FontLoadingParams()
        )
    except Exception:  # noqa: BLE001
        _DISPLAY_FONT = None

    imgui.get_io().font_default = _FONT


def display_font() -> imgui.ImFont | None:
    """Instrument Serif display face for hero text (``None`` if unavailable)."""
    return _DISPLAY_FONT
