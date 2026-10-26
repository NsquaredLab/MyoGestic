"""In-app MyoGestic wordmark widget.

Renders the stacked or one-line wordmark, preserving the asset's aspect ratio.
By default the generic [`Image`][myogestic.widgets.Image] widget fits and centres
the logo in the current cell. Pass ``variant="line", height=ui_px(26)`` to draw
an inline header logo at the cursor instead. The square OS icon
(``assets/app_settings/icon.png``) is a separate asset wired up in
``core.py`` for the dock / taskbar / title bar.

Drop into a grid cell as a branding header::

    from myogestic.widgets import AppLogo

    logo = AppLogo(max_size=240)

    @app.ui
    def ui(ctx):
        with grid[0, 0]:
            logo.ui()
        ...

Falls back to the Instrument Serif text wordmark when the asset is missing, so an unusual
install layout (or an in-place edit while assets are being regenerated)
doesn't crash the UI.
"""

from __future__ import annotations

from typing import Literal

from imgui_bundle import hello_imgui, imgui

from myogestic._theme import display_font
from myogestic.widgets.common import ui_px
from myogestic.widgets.panels.image import Image

_LOGO_ASSETS = {"stacked": "myogestic_logo.png", "line": "myogestic_logo_line.png"}


class AppLogo:
    """Render the MyoGestic wordmark in a cell or inline at a fixed height.

    Thin wrapper over [`Image`][myogestic.widgets.Image] pinned to the shipped
    wordmark. See that widget for the fit/centre behaviour.

    Examples
    --------
    >>> from myogestic.widgets import AppLogo
    >>> logo = AppLogo(max_size=240)
    >>> logo.ui()
    """

    def __init__(
        self,
        *,
        variant: Literal["stacked", "line"] = "stacked",
        height: float | None = None,
        max_size: float | None = None,
        padding: float = 12.0,
        widget_id: str | None = None,
    ) -> None:
        """Configure the wordmark widget.

        Parameters
        ----------
        variant
            ``"stacked"`` (default) for the full logo, or ``"line"`` for the
            one-line wordmark.
        height
            Optional fixed height in pixels, with width derived from the asset's
            aspect ratio. Draws at the cursor without cell centring or padding;
            takes precedence over ``max_size`` and ``padding``. Pass
            ``ui_px(26)`` from ``myogestic.widgets.common`` for a scaled header.
            ``None`` (default) keeps the fit-to-cell behaviour.
        max_size
            Optional cap on the wordmark's *width* in pixels. ``None`` (default)
            lets it grow to fill the cell — appropriate for a dedicated branding
            cell. Pass a value when the cell can be much larger than the wordmark
            should ever appear (e.g. a full-screen splash).
        padding
            Margin in pixels reserved on every side. Default 12 px gives the
            wordmark breathing room against the panel border.
        widget_id
            Optional per-instance ImGui id scope.
        """
        if variant not in _LOGO_ASSETS:
            raise ValueError('Pass variant="stacked" or variant="line".')
        if height is not None and height <= 0:
            raise ValueError("Pass a positive height in pixels, or None to fit the cell.")
        self._asset = _LOGO_ASSETS[variant]
        self._height = height
        self._image = Image(
            self._asset,
            max_size=max_size,
            padding=padding,
            widget_id=widget_id,
        )
        self._widget_id = widget_id

    def ui(self) -> None:
        """Draw the chosen logo, or the display text wordmark if it is missing."""
        imgui.push_id(self._widget_id or self._asset)
        try:
            if not hello_imgui.asset_exists(self._asset):
                # PushFont takes an unscaled size; height is already in pixels.
                font_size = (self._height or ui_px(22)) / imgui.get_style().font_scale_main
                imgui.push_font(display_font(), font_size)
                imgui.text_unformatted("MyoGestic")
                imgui.pop_font()
            elif self._height is None:
                self._image.ui()
            else:
                info = hello_imgui.image_and_size_from_asset(self._asset)
                aspect = info.size.x / info.size.y if info.size.y else 1.0
                imgui.image(
                    imgui.ImTextureRef(info.texture_id),
                    imgui.ImVec2(self._height * aspect, self._height),
                )
        finally:
            imgui.pop_id()


__all__ = ["AppLogo"]
