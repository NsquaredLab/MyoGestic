from __future__ import annotations

import os
import platform
import subprocess

from imgui_bundle import hello_imgui, imgui

_FONT: imgui.ImFont | None = None
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

    # macOS control metrics: NSButton bezel ~5px, slightly tighter spacing
    style.window_rounding = 10.0
    style.child_rounding = 6.0
    style.frame_rounding = 5.0
    style.grab_rounding = 5.0
    style.popup_rounding = 6.0
    style.scrollbar_rounding = 8.0
    style.tab_rounding = 5.0
    style.window_padding = imgui.ImVec2(12, 10)
    style.frame_padding = imgui.ImVec2(10, 5)
    style.item_spacing = imgui.ImVec2(8, 6)
    style.item_inner_spacing = imgui.ImVec2(6, 5)
    style.scrollbar_size = 12.0
    style.grab_min_size = 10.0
    style.window_border_size = 0.0
    style.frame_border_size = 0.0
    style.child_border_size = 1.0

    dark = _is_mac_dark()
    if dark:
        accent = _rgba(10, 132, 255)  # systemBlue (dark)
        accent_hi = _rgba(64, 156, 255)
        text = _rgba(255, 255, 255)
        text_dim = _rgba(235, 235, 245, 153)  # secondaryLabel
        window_bg = _rgba(30, 30, 30)  # NSVisualEffectView.dark
        child_bg = _rgba(30, 30, 30)  # match window_bg — borders delineate cells
        control_bg = _rgba(58, 58, 60, 230)  # systemGray5 dark
        control_hi = _rgba(72, 72, 74)
        border = _rgba(84, 84, 88, 100)  # separator
        header = _rgba(99, 99, 102, 90)
    else:
        accent = _rgba(0, 122, 255)
        accent_hi = _rgba(64, 156, 255)
        text = _rgba(0, 0, 0)
        text_dim = _rgba(60, 60, 67, 153)
        window_bg = _rgba(246, 246, 246)
        child_bg = _rgba(255, 255, 255)
        control_bg = _rgba(235, 235, 240)
        control_hi = _rgba(220, 220, 225)
        border = _rgba(198, 198, 200)
        header = _rgba(210, 210, 215)

    colors = {
        imgui.Col_.text: text,
        imgui.Col_.text_disabled: text_dim,
        imgui.Col_.window_bg: window_bg,
        imgui.Col_.child_bg: child_bg,
        imgui.Col_.popup_bg: child_bg,
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
        imgui.Col_.button_active: accent,
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
    global _FONT
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

    imgui.get_io().font_default = _FONT
