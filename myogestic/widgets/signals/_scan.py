"""Stream scan + reconnect panels (shared by signal_viewer & raw_signal_viewer).

Internal — exported for the viewer modules only.
"""

from __future__ import annotations

import threading as _threading
from dataclasses import dataclass, field

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import DANGER, IDLE, WARNING, muted


@dataclass
class _ScanState:
    """Per-stream scan results + selection + busy flag."""

    results: list[dict[str, str]] = field(default_factory=list)
    selected: int = 0
    busy: bool = False


_scans: dict[str, _ScanState] = {}


def _scan_panel(stream_name: str, stream: object) -> None:
    """Render the scan + dropdown + Connect controls for a stream.

    Shared by the disconnected fallback and the inline
    retarget-while-connected toggle. No "disconnected" framing.
    """
    from myogestic.stream import Stream

    if not isinstance(stream, Stream):
        return
    discover_fn = getattr(stream._source, "discover", None)
    if discover_fn is None:
        return

    s = _scans.setdefault(stream_name, _ScanState())

    # Snapshot busy at top so begin/end_disabled and the "Scanning..." label
    # are decided consistently within this frame. Without this snapshot, the
    # button click below sets s.busy=True synchronously, so the bottom check
    # would call end_disabled() without a matching begin_disabled().
    was_busy = s.busy
    if was_busy:
        imgui.begin_disabled()
    if imgui.button(f"Scan##{stream_name}"):
        s.busy = True

        def _scan() -> None:
            try:
                s.results = discover_fn()
                s.selected = 0
            finally:
                s.busy = False

        _threading.Thread(target=_scan, daemon=True).start()
    if was_busy:
        imgui.end_disabled()
        imgui.same_line()
        imgui.text("Scanning...")

    if s.results:
        names = [f"{r['name']} ({r['info']})" for r in s.results]
        imgui.push_item_width(300)
        changed, idx = imgui.combo(f"##scan_{stream_name}", s.selected, names)
        if changed:
            s.selected = idx
        imgui.pop_item_width()
        imgui.same_line()
        if imgui.button(f"Connect##{stream_name}"):
            target = s.results[s.selected]["name"]

            def _connect_target() -> None:
                stream.reconnect(target)

            _threading.Thread(target=_connect_target, daemon=True).start()
            s.results = []


def _centered(width: float, item_w: float) -> None:
    """Put the next item in the middle of a ``width``-wide row."""
    imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max((width - item_w) * 0.5, 0.0))


def _disconnected_ui(stream_name: str, stream: object, *, show_connect: bool = True) -> None:
    """The empty state for a stream with nothing to draw.

    Centred in the panel rather than tucked into its top-left corner: with no
    plot to fill it, a viewer cell is mostly blank, and a message in the corner
    of all that space reads as a rendering failure rather than as a prompt.

    **A stream nobody has attached yet is `IDLE`, not `DANGER`.** Opening red
    tells a first-time user their app is broken when it is only waiting. Red is
    kept for a real ``last_error``, and amber for a connection that was working
    and dropped — a distinction worth making, because only one of the three is
    worth investigating.

    ``show_connect=False`` drops the button and the scan list, leaving the
    message alone. For an app where another widget owns connecting: this button
    attaches whatever source the stream already holds, which is *not* what a
    `DevicePicker`'s Connect does, and two controls with one name doing two
    things is the bug this exists to avoid.
    """
    from myogestic.stream import Stream

    if not isinstance(stream, Stream):
        imgui.text_colored(muted(), f"{stream_name}: unavailable")
        return

    if stream.last_error:
        tone, title, hint = DANGER, stream.last_error, "Check the device, then try again."
    elif stream.info is not None:
        tone, title, hint = WARNING, "Connection lost", "The source stopped sending."
    else:
        tone, title, hint = IDLE, "Not connected", "Choose a source and connect it."
    retry = stream.info is not None or bool(stream.last_error)
    label = (
        f"{fa.ICON_FA_ARROWS_ROTATE}  Try again" if retry else f"{fa.ICON_FA_PLUG}  Connect"
    )

    style = imgui.get_style()
    avail = imgui.get_content_region_avail()
    row = imgui.get_text_line_height_with_spacing()
    block_h = row * 2 + (imgui.get_frame_height() + style.item_spacing.y * 2 if show_connect else 0.0)
    imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + max((avail.y - block_h) * 0.5, 0.0))

    _centered(avail.x, imgui.calc_text_size(title).x)
    imgui.text_colored(tone, title)
    _centered(avail.x, imgui.calc_text_size(hint).x)
    imgui.text_colored(muted(), hint)
    imgui.spacing()

    if not show_connect:
        return

    button_w = imgui.calc_text_size(label).x + style.frame_padding.x * 2
    _centered(avail.x, button_w)
    if imgui.button(f"{label}##{stream_name}_reconnect"):
        import sys as _sys

        if _sys.platform == "emscripten":
            # No threads in Pyodide. reconnect() is fast for the
            # browser's synthetic source; doing it inline blocks one
            # frame, which is preferable to a RuntimeError.
            stream.reconnect()
        else:

            def _reconnect() -> None:
                stream.reconnect()

            _threading.Thread(target=_reconnect, daemon=True).start()

    discover_fn = getattr(stream._source, "discover", None)
    if discover_fn is not None:
        imgui.spacing()
        _scan_panel(stream_name, stream)
