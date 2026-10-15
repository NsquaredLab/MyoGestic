"""The live UI scale: one number that fonts, style metrics and `Px` tracks follow.

Resolved in this order:

1. ``$MYOGESTIC_UI_SCALE`` — a fixed scale, for whoever is at the keyboard.
2. ``App(ui_scale=...)`` — a fixed scale, for whoever wrote the app.
3. Automatic — the OS display scale times how big the window is, recomputed every
   frame, so the same app is comfortable on a 14" laptop and a 27" 4K monitor and
   follows the window when it is resized or dragged to another screen.

Pure Python and imgui-free, so `grid.py` and `_theme.py` can both read it and the
arithmetic is testable without a GUI.
"""

from __future__ import annotations

import os

#: The window size, in logical pixels, at which the automatic scale is exactly the
#: OS display scale. Bigger windows draw a little larger, smaller ones a little
#: smaller — within `FIT_RANGE`.
REFERENCE_SIZE: tuple[float, float] = (1280.0, 800.0)

#: How far the window size may move the scale away from the OS display scale. The
#: floor is deliberately shallow: below it text stops being readable, and the fix
#: for a small window is a different arrangement (`Layout`), not smaller text.
FIT_RANGE: tuple[float, float] = (0.85, 1.3)

#: The automatic scale moves in steps this size, so dragging a window edge restyles
#: a handful of times rather than on every frame.
STEP: float = 0.05

_override: float | None = None  # App(ui_scale=...)
_current: float | None = None  # last automatic value, set once per frame


def clamp_scale(scale: float) -> float:
    """Keep a scale in ``[0.5, 2.0]`` so a typo cannot make the UI unusable."""
    return min(2.0, max(0.5, scale))


def set_ui_scale(scale: float | None) -> None:
    """Fix the scale from code — what ``App(ui_scale=...)`` calls. ``None`` = automatic."""
    global _override
    _override = scale


def override_scale() -> float | None:
    """The fixed scale if one is set (env var first, then ``App``), else ``None``."""
    raw = os.environ.get("MYOGESTIC_UI_SCALE", "").strip()
    if raw:
        try:
            return clamp_scale(float(raw))
        except ValueError:
            pass
    if _override is not None:
        return clamp_scale(_override)
    return None


def auto_scale(os_scale: float, width: float, height: float) -> float:
    """The automatic scale for a window of ``width`` × ``height`` logical pixels.

    ``os_scale`` is the display scale the user picked in the OS (1.5 for Windows at
    150 %); the window size nudges it by at most `FIT_RANGE`, and the result is
    quantised to `STEP`.
    """
    lo, hi = FIT_RANGE
    fit = min(width / REFERENCE_SIZE[0], height / REFERENCE_SIZE[1])
    fit = min(hi, max(lo, fit))
    return clamp_scale(round(os_scale * fit / STEP) * STEP)


def update(os_scale: float, width: float, height: float) -> float:
    """Recompute the scale for this frame and return it. Called before each frame."""
    global _current
    fixed = override_scale()
    _current = fixed if fixed is not None else auto_scale(os_scale, width, height)
    return _current


def current_scale() -> float:
    """The scale in effect now. Before the first frame (and headless): the override or 1.0."""
    if _current is not None:
        return _current
    fixed = override_scale()
    return fixed if fixed is not None else 1.0


def reset() -> None:
    """Forget the last automatic value — between `App` runs, and in tests."""
    global _current
    _current = None
