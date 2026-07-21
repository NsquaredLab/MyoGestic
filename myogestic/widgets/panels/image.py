"""Generic fit-to-cell image widget.

Renders an image asset into the current panel/grid cell as the largest
aspect-preserving rectangle that fits, centred both ways, with a muted text
fallback when the asset is missing. :class:`~myogestic.widgets.AppLogo` is a
thin wrapper over this pinned to the shipped wordmark.

The asset is resolved through HelloImGui's asset system (the folder
MyoGestic registers on ``App.run()``), so ``asset`` is a path relative to
``myogestic/assets/`` — e.g. ``"myogestic_logo.png"`` or
``"app_settings/icon.png"``.
"""

from __future__ import annotations

from imgui_bundle import hello_imgui, imgui


class Image:
    """Generic fit-to-cell image widget.

    Reads the available content area inside the current panel and renders
    the image as the **largest aspect-preserving rectangle that fits both
    dimensions** (minus ``padding``), then centres it. In a cell whose
    aspect matches the image, it fills edge-to-edge minus the padding
    margin; in a different aspect, it fills the tighter dimension and leaves
    balanced padding along the other.

    Notes
    -----
    Uses ``image_and_size_from_asset`` + raw ``imgui.image`` rather than the
    higher-level ``image_from_asset(..., size=...)`` helper, which in this
    version of hello_imgui ignored the explicit size and rendered at the
    natural pixel dimensions of the image.
    """

    def __init__(
        self,
        asset: str,
        *,
        max_size: float | None = None,
        padding: float = 12.0,
        missing_label: str | None = None,
        widget_id: str | None = None,
    ) -> None:
        """Configure the image widget.

        Parameters
        ----------
        asset
            Path to the image, relative to MyoGestic's registered assets folder
            (resolved via HelloImGui's asset system).
        max_size
            Optional cap on the rendered *width* in pixels. ``None`` (default)
            lets the image grow to fill the cell.
        padding
            Margin in pixels reserved on every side. Default 12 px.
        missing_label
            Text shown (muted) when the asset can't be found. Defaults to
            ``"(image asset missing: <asset>)"``.
        widget_id
            Optional per-instance ImGui id scope. Defaults to ``asset``.
        """
        self._asset = asset
        self._max_size = max_size
        self._padding = padding
        self._missing_label = missing_label
        self._widget_id = widget_id

    def ui(self) -> None:
        """Render the image asset fit-to-cell, aspect-preserving, centred."""
        imgui.push_id(self._widget_id or self._asset)
        try:
            if not hello_imgui.asset_exists(self._asset):
                imgui.text_disabled(self._missing_label or f"(image asset missing: {self._asset})")
                return
            info: hello_imgui.ImageAndSize = hello_imgui.image_and_size_from_asset(self._asset)
            # imgui.image() wants ImTextureRef; image_and_size_from_asset returns
            # the raw int texture id, so wrap it explicitly.
            tex_ref = imgui.ImTextureRef(info.texture_id)
            natural = info.size
            aspect = natural.x / natural.y if natural.y else 1.0

            avail_w = imgui.get_content_region_avail().x
            avail_h = imgui.get_content_region_avail().y
            # Subtract padding before the fit calculation so the margin is
            # honoured even when the cell is the same aspect as the image.
            usable_w = max(0.0, avail_w - 2 * self._padding)
            usable_h = max(0.0, avail_h - 2 * self._padding)
            if usable_w <= 0 or usable_h <= 0:
                return

            # Fit-in-rect: largest aspect-preserving box that fits both dims.
            target_w = min(usable_w, usable_h * aspect)
            target_h = target_w / aspect

            # Optional cap so the image doesn't blow up on a huge cell.
            if self._max_size is not None and target_w > self._max_size:
                target_w = self._max_size
                target_h = self._max_size / aspect

            # Centre horizontally via indent/unindent — `set_cursor_pos_x`
            # would extend the parent's content extent without submitting an
            # item to claim it, which trips ImGui's IM_ASSERT on the
            # surrounding child.
            offset = max(0.0, (avail_w - target_w) * 0.5)
            # Centre vertically by reserving an empty `Dummy` item before the
            # image equal to half the leftover height. `Dummy` is the
            # documented ImGui way to claim layout space — `set_cursor_pos_y`
            # would trip the same boundary-extension assertion as the
            # horizontal case.
            v_pad = max(0.0, (avail_h - target_h) * 0.5)
            if v_pad:
                imgui.dummy(imgui.ImVec2(1.0, v_pad))
            if offset:
                imgui.indent(offset)
            imgui.image(tex_ref, imgui.ImVec2(target_w, target_h))
            if offset:
                imgui.unindent(offset)
        finally:
            imgui.pop_id()


__all__ = ["Image"]
