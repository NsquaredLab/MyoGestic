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
    destructive_button,
    format_age,
    label_column,
    mono_text,
    muted,
    panel_header,
)
from myogestic.widgets.signals.stream_panel import _last_ts_age

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import Stream

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
    """The streams this app is running: add one, remove one, see their state.

    For an app whose sources are not known when it is written — a second
    amplifier, a force transducer on its own device — rather than one that
    declares every stream up front with ``app.streams(...)``. Pair it with a
    `DevicePicker` per stream to choose what each one is attached to.

    Adding and removing are refused while a recording is running, and the panel
    says so: a session sizes one Zarr array per stream when recording starts, so
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

    def ui(self, ctx: Context) -> None:
        """Render the manager. Call once per frame."""
        imgui.push_id(self._widget_id)
        try:
            self._body(ctx)
        finally:
            imgui.pop_id()

    def _body(self, ctx: Context) -> None:
        recording = getattr(ctx, "state", "") == "recording"
        if self._show_header:
            panel_header("Streams", fa.ICON_FA_LAYER_GROUP)

        # The remove is *deferred* out of the loop below. `ctx.streams` is being
        # iterated to draw the rows, and popping from a dict mid-iteration raises
        # RuntimeError — the click has to be remembered and acted on afterwards.
        remove: str | None = None
        for index, (name, stream) in enumerate(ctx.streams.items()):
            # Between rows, not inside them. A stream's name and its read-out are one
            # thing and every gap here was the same size, which put the read-out nearer
            # the next stream's name than its own — so it read as a caption for the
            # wrong row.
            if index:
                imgui.spacing()
            if self._row(name, stream, recording=recording):
                remove = name
        if remove is not None:
            self._on_remove(remove)

        imgui.spacing()
        self._add_row(ctx, recording=recording)

    def _row(self, name: str, stream: Stream, *, recording: bool) -> bool:
        """One stream: dot, name, live geometry, Remove. True if Remove was pressed."""
        info = stream.info
        attached = stream.status == "connected" and info is not None
        if attached:
            tone = SUCCESS
        elif stream.last_error:
            tone = DANGER
        else:
            tone = IDLE

        style = imgui.get_style()
        # Closes the gap between this row and the read-out under it. ImGui charges
        # `ItemSpacing.y` when it places the *next* item, so the value has to be pushed
        # around the name row — pushed around the read-out it shortens the gap *below*
        # it instead, which separates the name from its own numbers and pulls the next
        # stream up against them: the exact fault, inverted.
        imgui.push_style_var(imgui.StyleVar_.item_spacing, imgui.ImVec2(style.item_spacing.x, 0.0))
        # The Remove button makes this row a frame high, and plain text sits at the top
        # of the line box it is given — leaving the name floating above a band of empty
        # row, and its read-out further from it than the number suggests.
        imgui.align_text_to_frame_padding()
        imgui.text_colored(tone, fa.ICON_FA_CIRCLE)
        imgui.same_line()
        imgui.text(name)

        button_w = imgui.calc_text_size(fa.ICON_FA_TRASH).x + style.frame_padding.x * 2.0
        # `same_line` first, *then* measure: taken before it, the cursor has
        # already wrapped to the next line and the width read is the whole row,
        # so the offset overshoots by the length of the name and puts the button
        # off the right edge.
        imgui.same_line()
        avail = imgui.get_content_region_avail().x
        if avail > button_w:
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + avail - button_w)
        if recording:
            imgui.begin_disabled()
        clicked = destructive_button(
            f"{fa.ICON_FA_TRASH}##rm_{name}",
            tooltip="" if recording else f"Stop {name!r} and remove it",
        )
        if recording:
            imgui.end_disabled()
            if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
                imgui.set_tooltip("Stop the recording first.")
        # The button is the row's last item, so the pop has to come after it — that is
        # the item whose spacing decides where the read-out lands.
        imgui.pop_style_var()

        imgui.indent(22)
        if attached and info is not None:
            mono_text(
                f"{info.fs:.0f} Hz · {info.n_channels} ch · {format_age(_last_ts_age(stream))}",
                muted(),
            )
        else:
            imgui.text_colored(muted(), stream.last_error or "not connected")
        imgui.unindent(22)
        return clicked

    def _add_row(self, ctx: Context, *, recording: bool) -> None:
        """Name field plus Add, with the reason it is unavailable in the tooltip."""
        cleaned = _clean_name(self._typed)
        if recording:
            reason = "Stop the recording before adding a stream."
        elif not cleaned:
            reason = "Type a name first."
        elif cleaned in ctx.streams:
            reason = f"A stream named {cleaned!r} already exists."
        else:
            reason = ""

        style = imgui.get_style()
        add_w = imgui.calc_text_size(f"{fa.ICON_FA_PLUS}  Add").x + style.frame_padding.x * 2.0
        label_column("New", ("New",), reserve=add_w + style.item_spacing.x)
        changed, typed = imgui.input_text_with_hint("##new", "e.g. force", self._typed)
        if changed:
            self._typed = typed[:_NAME_MAX]

        imgui.same_line()
        blocked = bool(reason)
        if blocked:
            imgui.begin_disabled()
        if imgui.button(f"{fa.ICON_FA_PLUS}  Add"):
            self._on_add(cleaned)
            self._typed = ""
        if blocked:
            imgui.end_disabled()
        if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
            imgui.set_tooltip(reason or f"Add a stream named {cleaned!r}")


__all__ = ["StreamManager"]
