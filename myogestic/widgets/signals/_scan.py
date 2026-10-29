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

from myogestic.widgets.common import (
    DANGER,
    IDLE,
    WARNING,
    CarouselItem,
    carousel,
    fit_text,
    muted,
    primary_button,
    ui_px,
)

if TYPE_CHECKING:
    from myogestic.stream import Stream

_SCAN_LABEL = f"{fa.ICON_FA_ARROWS_ROTATE}  Scan"
_SCANNING_LABEL = "Scanning…"
#: LSL types that are never a signal to view: MyoGestic's own control outlets (one per
#: Virtual Hand control) and event markers. Left out when no type can be inferred.
_NOT_SIGNALS = frozenset({"Control", "Markers"})


@dataclass
class _ScanState:
    """Per-stream scan results + selection + busy flag.

    ``selected`` indexes ``results`` for the connected retarget combo; the empty
    state's carousel keeps its own ``shown`` stream by name instead, so a rescan
    that reorders the results leaves the card on the same stream.
    """

    results: list[dict[str, str]] = field(default_factory=list)
    selected: int = 0
    busy: bool = False
    scanned: bool = False
    shown: str | None = None
    advance: bool = False


_scans: dict[str, _ScanState] = {}


def _start_scan(
    s: _ScanState, discover_fn: Callable[[], list[dict[str, str]]], *, advance: bool = False
) -> None:
    """Run ``discover_fn`` off-thread into ``s``.

    ``advance`` asks the carousel to step on to the next stream once the results
    are in, which is what pressing › past the last known stream means.
    """
    s.busy, s.advance = True, advance

    def _scan() -> None:
        try:
            s.results = discover_fn()
            s.selected = 0
        finally:
            s.scanned = True
            s.busy = False

    _threading.Thread(target=_scan, daemon=True).start()


def _scan_panel(stream_name: str, stream: object) -> None:
    """Render the scan + dropdown + Connect controls for a stream.

    The inline retarget-while-connected toggle. No "disconnected" framing.
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
        _start_scan(s, discover_fn)
    imgui.set_item_tooltip("Look for other outlets")


def _scan_results(
    stream_name: str,
    stream: Stream,
    s: _ScanState,
    *,
    centered: bool = False,
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


def _carousel(
    stream: Stream, s: _ScanState, stream_type: str | None
) -> tuple[list[dict[str, str]], str | None]:
    """The streams the empty state steps through, and this app's own stream's name.

    The app's stream comes first whether or not a scan found it, so Connect means
    what it always meant until somebody steps away. The others are the last scan's
    results of one LSL type: ``stream_type`` when given, else the type the scan
    reported for the app's stream. When neither says — the app's stream is the one
    that could not be found — every type is offered except `_NOT_SIGNALS`. A result
    that carries no type at all is always kept.
    """
    own = getattr(stream._source, "_name", None)
    by_name = {r["name"]: r for r in s.results}
    kind = stream_type or by_name.get(own, {}).get("type")

    def offered(r: dict[str, str]) -> bool:
        if "type" not in r:
            return True
        return r["type"] == kind if kind else r["type"] not in _NOT_SIGNALS

    items = [by_name.get(own, {"name": own})] if own else []
    items += [r for r in s.results if r["name"] != own and offered(r)]
    return items, own


def _connect(stream: Stream, target: str | None) -> None:
    """Attach ``target`` (the stream's own source when ``None``) off the UI thread."""
    import sys as _sys

    if _sys.platform == "emscripten":
        # No threads in Pyodide. reconnect() is fast for the browser's synthetic
        # source; doing it inline blocks one frame, which beats a RuntimeError.
        stream.reconnect(target) if target else stream.reconnect()
        return

    def _reconnect() -> None:
        stream.reconnect(target) if target else stream.reconnect()

    _threading.Thread(target=_reconnect, daemon=True).start()


def _centered_text(text: str, color: imgui.ImVec4, left: float, width: float) -> None:
    """One wrapped, centred line block inside ``[left, left + width]``."""
    size = imgui.calc_text_size(text, wrap_width=max(1.0, width))
    imgui.set_cursor_pos_x(left + max((width - size.x) * 0.5, 0.0))
    imgui.push_text_wrap_pos(imgui.get_cursor_pos_x() + width)
    imgui.push_style_color(imgui.Col_.text, color)
    imgui.text_wrapped(text)
    imgui.pop_style_color()
    imgui.pop_text_wrap_pos()


def _disconnected_ui(
    stream_name: str,
    stream: object,
    *,
    show_connect: bool = True,
    stream_type: str | None = None,
) -> None:
    """The empty state for a stream with nothing to draw: a carousel, then Connect.

    Centred in the panel rather than tucked into its top-left corner: with no
    plot to fill it, a viewer cell is mostly blank, and a message in the corner
    of all that space reads as a rendering failure rather than as a prompt.

    **A stream nobody has attached yet is `IDLE`, not `DANGER`.** Opening red
    tells a first-time user their app is broken when it is only waiting. Red is
    kept for a real ``last_error``, and amber for a connection that was working
    and dropped — a distinction worth making, because only one of the three is
    worth investigating.

    One stream at a time sits on a card between ‹ and ›, starting on the app's own,
    and the one Connect names the stream on the card — so there is never a second
    Connect, and never a doubt about what this one attaches. Nothing scans until
    somebody steps past the last known stream or presses refresh: a scan is an LSL
    network query, and this screen is the first thing every app shows.

    ``show_connect=False`` drops the carousel and the button, leaving the
    message alone. For an app where another widget owns connecting: this button
    attaches whatever source the stream already holds, which is *not* what a
    `DevicePicker`'s Connect does, and two controls with one name doing two
    things is the bug this exists to avoid.
    """
    from myogestic.stream import Stream

    if not isinstance(stream, Stream):
        imgui.text_colored(muted(), f"{stream_name}: unavailable")
        return

    discover_fn = getattr(stream._source, "discover", None) if show_connect else None
    s = _scans.setdefault(stream_name, _ScanState())
    busy = s.busy  # the worker may finish mid-frame; draw one state
    items, own = _carousel(stream, s, stream_type) if show_connect else ([], None)
    index = next((i for i, item in enumerate(items) if item["name"] == s.shown), 0)
    if s.advance and not busy:
        s.advance = False
        index = min(index + 1, max(len(items) - 1, 0))
    if items:
        s.shown = items[index]["name"]
    shown = items[index] if items else None
    target = shown["name"] if shown else None
    on_own = target is None or target == own
    can_scan = discover_fn is not None and not busy

    failed, lost = bool(stream.last_error), stream.info is not None
    if failed:
        # The first sentence: LSL appends every outlet on the network after it.
        reason = stream.last_error.split(". ")[0].rstrip(".") + "."
        tone, title, hint = DANGER, "Couldn’t connect", reason
    elif lost:
        tone, title, hint = WARNING, "Connection lost", "The source stopped sending."
    elif not show_connect:
        tone, title, hint = IDLE, "Not connected", "Choose a source and connect it."
    elif discover_fn is None:
        tone, title, hint = IDLE, "Not connected", "Connect this app’s stream."
    elif not s.scanned:
        tone, title, hint = IDLE, "Not connected", "Connect, or step on to look for others."
    elif len(items) > 1:
        tone, title, hint = IDLE, "Not connected", "Step through the streams found."
    else:
        tone, title, hint = IDLE, "Not connected", "No other streams found."
    if on_own:
        name = own or "this app’s source"
        verb = "Try again" if failed else f"Reconnect {name}" if lost else f"Connect {name}"
        icon = fa.ICON_FA_ARROWS_ROTATE if failed or lost else fa.ICON_FA_PLUG
    else:
        verb, icon = f"Connect {target}", fa.ICON_FA_PLUG

    style = imgui.get_style()
    avail = imgui.get_content_region_avail()
    width = min(avail.x, ui_px(300))
    left = imgui.get_cursor_pos_x() + (avail.x - width) * 0.5
    line = imgui.get_text_line_height()
    card_h = 2 * line + ui_px(14)
    title_h = imgui.calc_text_size(title, wrap_width=max(1.0, width)).y
    hint_h = imgui.calc_text_size(hint, wrap_width=max(1.0, width)).y
    block_h = title_h + hint_h + 2 * style.item_spacing.y
    if show_connect:
        block_h += imgui.get_frame_height() + style.item_spacing.y
        if discover_fn is not None:
            block_h += card_h + imgui.get_frame_height() + 2 * style.item_spacing.y
    imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + max((avail.y - block_h) * 0.5, 0.0))

    _centered_text(title, tone, left, width)
    _centered_text(hint, muted(), left, width)
    if failed:
        imgui.set_item_tooltip(stream.last_error)
    imgui.spacing()
    if not show_connect:
        return

    if discover_fn is not None:
        cards = []
        for i, item in enumerate(items):
            if busy and i == len(items) - 1:
                detail, color = "looking for streams…", None
            elif "info" in item:
                detail, color = item["info"], None
            elif s.scanned:
                detail, color = "not found on the network", DANGER if failed else None
            else:
                detail, color = "", None
            tag = "this app’s" if item["name"] == own else ""
            cards.append(CarouselItem(item["name"], detail, tag, color))
        imgui.set_cursor_pos_x(left)
        stepped, refresh = carousel(
            stream_name,
            cards or [CarouselItem("This app’s source")],
            index,
            can_look=can_scan,
            noun="stream",
            width=width,
        )
        if stepped >= len(items):
            _start_scan(s, discover_fn, advance=True)
        elif items:
            s.shown = items[stepped]["name"]
        if refresh:
            _start_scan(s, discover_fn)

    imgui.set_cursor_pos_x(left)
    if primary_button(
        fit_text(f"{icon}  {verb}", width - 2 * style.frame_padding.x)
        + f"##{stream_name}_reconnect",
        (width, 0),
    ):
        _connect(stream, None if on_own else target)
