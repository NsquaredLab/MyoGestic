"""Add and remove a stream while the app is running."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import (
    DANGER,
    IDLE,
    SUCCESS,
    muted,
    panel_header,
    stream_chip,
)

if TYPE_CHECKING:
    from myogestic.core import Context

#: A stream name becomes a Zarr array name inside the session and a key in
#: ``ctx.streams``. Whitelisted rather than blacklisted, the way session names are.
_NAME_MAX = 32


def _clean_name(typed: str) -> str:
    """A stream name safe to use as a dict key and a Zarr array name, or ``""``.

    Whitelist, not blacklist: anything outside ASCII alphanumerics, ``-`` and
    ``_`` is dropped. The name reaches disk as ``<name>.zarr`` inside the
    session, so a separator or a ``..`` in it would escape the session folder.
    """
    kept = "".join(c for c in typed.strip().lower() if c.isascii() and (c.isalnum() or c in "-_"))
    return kept[:_NAME_MAX]


class StreamManager:
    """Stream chips with status dots, selection, and inline add or remove actions.

    For an app whose sources are not known when it is written — a second
    amplifier, a force transducer on its own device — rather than one that
    declares every stream up front with ``app.streams(...)``. Pair it with a
    `DevicePicker` per stream to choose what each one is attached to.

    Select a chip to reveal its remove action; the last stream is kept. The
    trailing plus opens a name field, Add, and cancel. Chips are dimmed while
    recording and a caption explains the lock: a session sizes one Zarr array
    per stream when recording starts, so
    a stream appearing afterwards has nowhere to write, and one vanishing
    mid-take is never finalised.

    Parameters
    ----------
    on_add
        Called with a cleaned stream name when Add is pressed. Build the
        `Stream` and hand it to `App.add_stream` — the app owns the geometry
        (window and buffer length), not this panel.
    on_remove
        Called with the stream's name when its Remove is pressed. Pass
        `App.remove_stream`.
    show_header
        Render the standard ``panel_header``.
    widget_id
        ImGui id scope. Defaults to ``"streams"``; give each instance its own if
        an app renders more than one.

    Examples
    --------
    >>> from myogestic.widgets import StreamManager
    >>> manager = StreamManager(
    ...     on_add=lambda name: app.add_stream(Stream(name, source=..., window_ms=200)),
    ...     on_remove=app.remove_stream,
    ... )
    >>> manager.ui(ctx)
    """

    def __init__(
        self,
        *,
        on_add: Callable[[str], object],
        on_remove: Callable[[str], object],
        show_header: bool = True,
        widget_id: str | None = None,
    ) -> None:
        self._on_add = on_add
        self._on_remove = on_remove
        self._show_header = show_header
        self._widget_id = widget_id or "streams"
        self._typed = ""
        self._adding = False
        self._selected = ""

    def ui(self, ctx: Context) -> None:
        """Render the manager. Call once per frame."""
        imgui.push_id(self._widget_id)
        try:
            self._body(ctx)
        finally:
            imgui.pop_id()

    def _body(self, ctx: Context) -> None:
        recording = bool(getattr(ctx, "recording", False))
        if self._show_header:
            panel_header("Streams", fa.ICON_FA_LAYER_GROUP)
        names = sorted(ctx.streams)
        if self._selected not in names:
            self._selected = names[0] if names else ""
        style = imgui.get_style()
        left = imgui.get_cursor_pos_x()
        right = left + imgui.get_content_region_avail().x
        remove = None
        for index, name in enumerate(names):
            stream = ctx.streams[name]
            tone = (
                SUCCESS
                if stream.status == "connected" and stream.info is not None
                else DANGER
                if stream.last_error
                else IDLE
            )
            selected = name == self._selected
            clicked, removed = stream_chip(
                name,
                tone,
                selected=selected,
                prefix="sm",
                left=left,
                right=right,
                first=index == 0,
                removable=selected and len(names) > 1,
                recording=recording,
                locked=recording,
                detail=stream.last_error or stream.status,
            )
            if clicked:
                self._selected = name
            if removed:
                remove = name
        if remove is not None:
            self._on_remove(remove)
            if self._selected not in ctx.streams:
                self._selected = next(iter(sorted(ctx.streams)), "")
        if names:
            imgui.same_line()
            plus_w = imgui.calc_text_size(fa.ICON_FA_PLUS).x + 2 * style.frame_padding.x
            if imgui.get_cursor_pos_x() + plus_w > right:
                imgui.new_line()
        imgui.begin_disabled(recording)
        if imgui.button(f"{fa.ICON_FA_PLUS}##sm_add_open") and not recording:
            self._adding = True
        imgui.end_disabled()
        imgui.set_item_tooltip("Add a stream.")
        if self._adding:
            self._add_row(ctx, recording=recording)
        if recording:
            imgui.push_style_color(imgui.Col_.text, muted())
            imgui.text_wrapped("Stop the recording to add or remove streams.")
            imgui.pop_style_color()
        elif not names and not self._adding:
            imgui.text_wrapped("Use + to add your first stream, then connect its source.")

    def _add_row(self, ctx: Context, *, recording: bool) -> None:
        """Inline name, Add and cancel, using the existing safe-name contract."""
        style = imgui.get_style()
        reserve = (
            imgui.calc_text_size("Add").x
            + imgui.calc_text_size(fa.ICON_FA_XMARK).x
            + 4 * style.frame_padding.x
            + 2 * style.item_spacing.x
        )
        imgui.set_next_item_width(max(1.0, imgui.get_content_region_avail().x - reserve))
        imgui.begin_disabled(recording)
        changed, typed = imgui.input_text_with_hint("##sm_new", "e.g. force", self._typed)
        if changed:
            self._typed = typed[:_NAME_MAX]
        cleaned = _clean_name(self._typed)
        reason = (
            "Stop the recording before adding a stream."
            if recording
            else "Type a name first."
            if not cleaned
            else f"A stream named {cleaned!r} already exists."
            if cleaned in ctx.streams
            else ""
        )
        imgui.same_line()
        imgui.begin_disabled(bool(reason))
        if imgui.button("Add##sm_add") and not reason:
            self._on_add(cleaned)
            self._typed = ""
            self._adding = False
            if cleaned in ctx.streams:
                self._selected = cleaned
        imgui.end_disabled()
        if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
            imgui.set_tooltip(reason or f"Add a stream named {cleaned!r}.")
        imgui.same_line()
        if imgui.button(f"{fa.ICON_FA_XMARK}##sm_add_cancel"):
            self._adding = False
            self._typed = ""
        imgui.set_item_tooltip("Cancel adding a stream.")
        imgui.end_disabled()


__all__ = ["StreamManager"]
