"""Stream scan + reconnect panels (shared by signal_viewer & raw_signal_viewer).

Internal — exported for the viewer modules only.
"""

from __future__ import annotations

import threading as _threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import DANGER, IDLE, WARNING, muted, primary_button, ui_px

if TYPE_CHECKING:
    from myogestic.stream import Stream

_SCAN_LABEL = f"{fa.ICON_FA_ARROWS_ROTATE}  Scan"
_SCANNING_LABEL = "Scanning…"


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
    _scan_action(stream_name, discover_fn, s, busy=s.busy)
    _scan_results(stream_name, stream, s)


def _scan_action(
    stream_name: str,
    discover_fn: Callable[[], list[dict[str, str]]],
    s: _ScanState,
    *,
    busy: bool,
) -> None:
    """Draw discovery or its muted status using the frame's busy snapshot."""
    if busy:
        imgui.align_text_to_frame_padding()
        imgui.text_colored(muted(), _SCANNING_LABEL)
        return
    if imgui.button(f"{_SCAN_LABEL}##{stream_name}"):
        s.busy = True

        def _scan() -> None:
            try:
                s.results = discover_fn()
                s.selected = 0
            finally:
                s.busy = False

        _threading.Thread(target=_scan, daemon=True).start()
    imgui.set_item_tooltip("Look for other outlets")


def _scan_results(
    stream_name: str, stream: Stream, s: _ScanState, *, centered: bool = False,
) -> None:
    """Keep the outlet selector and its Connect inside the available row."""
    if not s.results:
        return
    style = imgui.get_style()
    avail = imgui.get_content_region_avail().x
    connect_w = imgui.calc_text_size("Connect").x + style.frame_padding.x * 2
    combo_w = min(ui_px(300), max(1.0, avail - connect_w - style.item_spacing.x))
    if centered:
        _centered(avail, combo_w + style.item_spacing.x + connect_w)
    names = [f"{r['name']} ({r['info']})" for r in s.results]
    imgui.set_next_item_width(combo_w)
    changed, idx = imgui.combo(f"##scan_{stream_name}", s.selected, names)
    if changed:
        s.selected = idx
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
    discover_fn = getattr(stream._source, "discover", None) if show_connect else None
    scan = _scans.setdefault(stream_name, _ScanState()) if discover_fn is not None else None
    # The worker may finish during this frame; measure and draw the same state.
    busy = scan.busy if scan is not None else False
    button_w = imgui.calc_text_size(label).x + style.frame_padding.x * 2
    scan_w = imgui.calc_text_size(_SCANNING_LABEL if busy else _SCAN_LABEL).x
    if not busy:
        scan_w += style.frame_padding.x * 2
    row_w = button_w + style.item_spacing.x + scan_w if scan is not None else button_w
    wrap_actions = scan is not None and row_w > avail.x
    title_size = imgui.calc_text_size(title, wrap_width=max(1.0, avail.x))
    hint_size = imgui.calc_text_size(hint, wrap_width=max(1.0, avail.x))
    block_h = title_size.y + hint_size.y + 2 * style.item_spacing.y
    if show_connect:
        block_h += imgui.get_frame_height() + style.item_spacing.y * 2
        if wrap_actions:
            block_h += imgui.get_frame_height() + style.item_spacing.y
        if scan is not None and scan.results:
            block_h += imgui.get_frame_height() + style.item_spacing.y
    imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + max((avail.y - block_h) * 0.5, 0.0))

    _centered(avail.x, title_size.x)
    imgui.push_style_color(imgui.Col_.text, tone)
    imgui.text_wrapped(title)
    imgui.pop_style_color()
    _centered(avail.x, hint_size.x)
    imgui.push_style_color(imgui.Col_.text, muted())
    imgui.text_wrapped(hint)
    imgui.pop_style_color()
    imgui.spacing()

    if not show_connect:
        return

    _centered(avail.x, button_w if wrap_actions else row_w)
    if primary_button(f"{label}##{stream_name}_reconnect"):
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

    if scan is not None:
        if wrap_actions:
            _centered(avail.x, scan_w)
        else:
            imgui.same_line()
        _scan_action(stream_name, discover_fn, scan, busy=busy)
        _scan_results(stream_name, stream, scan, centered=True)
