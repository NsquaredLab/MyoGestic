"""In-app MyoGestic wordmark widget.

Renders the wordmark logo (``assets/myogestic_logo.png`` inside the package)
fit into the current cell, preserving the original 1.5:1 aspect and centring
it. A thin wrapper over the generic [`Image`][myogestic.widgets.Image] widget,
pinned to the shipped wordmark asset. The square OS icon
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

Falls back to a muted text label when the asset is missing, so an unusual
install layout (or an in-place edit while assets are being regenerated)
doesn't crash the UI.
"""

from __future__ import annotations

from myogestic.widgets.panels.image import Image

_LOGO_ASSET = "myogestic_logo.png"


class AppLogo:
    """Render the MyoGestic wordmark, fit-to-cell, aspect-preserving.

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
        max_size: float | None = None,
        padding: float = 12.0,
        widget_id: str | None = None,
    ) -> None:
        """Configure the wordmark widget.

        Parameters
        ----------
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
        self._image = Image(
            _LOGO_ASSET,
            max_size=max_size,
            padding=padding,
            missing_label="(myogestic logo asset missing)",
        )
        self._widget_id = widget_id

    def ui(self) -> None:
        """Render the MyoGestic wordmark, fit-to-cell, aspect-preserving."""
        self._image.ui()


__all__ = ["AppLogo"]
