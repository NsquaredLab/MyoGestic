"""Stream scan + reconnect panels (shared by signal_viewer & raw_signal_viewer).

Internal — exported for the viewer modules only.
"""

from __future__ import annotations

import threading as _threading
from dataclasses import dataclass, field

from imgui_bundle import imgui


@dataclass
class _ScanState:
    """Per-stream scan results + selection + busy flag."""
    results: list[dict[str, str]] = field(default_factory=list)
    selected: int = 0
    busy: bool = False


_scans: dict[str, _ScanState] = {}


def _scan_panel(stream_name: str, stream: object) -> None:
    """Scan + dropdown + Connect — shared by the disconnected fallback and
    the inline retarget-while-connected toggle. No "disconnected" framing.
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


def _disconnected_ui(stream_name: str, stream: object) -> None:
    """Show reconnect + scan UI when a stream is disconnected."""
    from myogestic.stream import Stream

    if not isinstance(stream, Stream):
        imgui.text(f"{stream_name}: disconnected")
        return

    imgui.text_colored(
        imgui.ImVec4(1.0, 0.4, 0.4, 1.0),
        f"{stream_name}: disconnected",
    )
    if stream.last_error:
        imgui.same_line()
        imgui.text_colored(imgui.ImVec4(0.6, 0.6, 0.6, 1.0), f"({stream.last_error})")

    if imgui.button(f"Reconnect##{stream_name}"):
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
        imgui.same_line()
        _scan_panel(stream_name, stream)
