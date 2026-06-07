"""In-app MyoGestic wordmark widget.

Renders the wordmark logo (``assets/myogestic_logo.png`` inside the package)
fit into a target box, preserving the original 1.5:1 aspect and centring
horizontally in the available panel width. The square OS icon
(``assets/app_settings/icon.png``) is a separate asset wired up in
``core.py`` for the dock / taskbar / title bar.

Drop into a grid cell as a branding header::

    from myogestic.widgets import app_logo

    @app.ui
    def ui(ctx):
        with grid[0, 0]:
            app_logo(size=240)
        ...

``size`` is the *target box side* — the widget computes the actual rendered
size by fitting the wordmark inside a ``size``×``size`` box (so a square grid
cell ends up with a centred wordmark and equal padding above/below).

Falls back to a muted text label when the asset is missing, so an unusual
install layout (or an in-place edit while assets are being regenerated)
doesn't crash the UI.
"""

from __future__ import annotations

from imgui_bundle import hello_imgui, imgui

_LOGO_ASSET = "myogestic_logo.png"


def app_logo(max_size: float | None = None, padding: float = 12.0) -> None:
    """Render the MyoGestic wordmark, fit-to-cell, aspect-preserving.

    The widget reads the available content area inside the current panel
    and renders the wordmark as the **largest aspect-preserving rectangle
    that fits both dimensions** (minus the requested padding), then
    centres it. So in a cell whose aspect matches the wordmark, the image
    fills edge-to-edge minus the padding margin; in a cell that's a
    different aspect, the image fills the tighter dimension and leaves
    extra balanced padding along the other.

    Parameters
    ----------
    max_size
        Optional cap on the wordmark's *width* in pixels. ``None``
        (default) lets the image grow to fill the cell — appropriate for
        "logo in a dedicated branding cell" use. Pass a value when the
        cell can be much larger than the wordmark should ever appear
        (e.g. a logo embedded in a full-screen splash).
    padding
        Margin in pixels reserved on every side. Default 12 px
        gives the wordmark breathing room against the panel border.

    Notes
    -----
    Uses ``image_and_size_from_asset`` + raw ``imgui.image`` rather than the
    higher-level ``image_from_asset(..., size=...)`` helper, which in this
    version of hello_imgui ignored the explicit size and rendered at the
    natural pixel dimensions of the PNG.
    """
    if not hello_imgui.asset_exists(_LOGO_ASSET):
        imgui.text_disabled("(myogestic logo asset missing)")
        return
    info: hello_imgui.ImageAndSize = hello_imgui.image_and_size_from_asset(_LOGO_ASSET)
    # imgui.image() wants ImTextureRef; image_and_size_from_asset returns
    # the raw int texture id, so wrap it explicitly.
    tex_ref = imgui.ImTextureRef(info.texture_id)
    natural = info.size
    aspect = natural.x / natural.y if natural.y else 1.0

    avail_w = imgui.get_content_region_avail().x
    avail_h = imgui.get_content_region_avail().y
    # Subtract padding before the fit calculation so the margin is
    # honoured even when the cell is the same aspect as the image.
    usable_w = max(0.0, avail_w - 2 * padding)
    usable_h = max(0.0, avail_h - 2 * padding)
    if usable_w <= 0 or usable_h <= 0:
        return

    # Fit-in-rect: largest aspect-preserving box that fits both dimensions.
    target_w = min(usable_w, usable_h * aspect)
    target_h = target_w / aspect

    # Optional cap so the logo doesn't blow up on a huge cell.
    if max_size is not None and target_w > max_size:
        target_w = max_size
        target_h = max_size / aspect

    # Centre horizontally via indent/unindent — `set_cursor_pos_x` would
    # extend the parent's content extent without submitting an item to
    # claim it, which trips ImGui's IM_ASSERT on the surrounding child.
    offset = max(0.0, (avail_w - target_w) * 0.5)
    # Centre vertically by reserving an empty `Dummy` item before the image
    # equal to half the leftover height. `Dummy` is the documented ImGui way
    # to claim layout space — `set_cursor_pos_y` would trip the same
    # boundary-extension assertion as the horizontal case.
    v_pad = max(0.0, (avail_h - target_h) * 0.5)
    if v_pad:
        imgui.dummy(imgui.ImVec2(1.0, v_pad))
    if offset:
        imgui.indent(offset)
    imgui.image(tex_ref, imgui.ImVec2(target_w, target_h))
    if offset:
        imgui.unindent(offset)


__all__ = ["app_logo"]
