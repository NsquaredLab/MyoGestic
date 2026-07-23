"""Per-stream status panel for @app.ui.

A compact replacement for the MyoGestic "device setup" tab that only shows
what's actually true at runtime: source class, connection status, sample
rate, channel count, last-sample age, plus inline connect buttons for any
target the source's ``discover()`` reports. Rendering is one-shot per
frame — no hidden state beyond the discovery cache (shared with the signal
viewers).
"""

from __future__ import annotations

import threading as _threading
import time as _time
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import DANGER, SUCCESS, panel_header
from myogestic.widgets.signals._scan import _scans, _ScanState

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import Stream

_OK = SUCCESS
_BAD = DANGER
_MUTED = imgui.ImVec4(0.65, 0.65, 0.65, 1.0)

# Streams we've already auto-discovered once. Forces the auto-scan to fire
# only on the first frame each stream is observed disconnected — the user's
# scan button can refresh later.
_auto_scanned: set[str] = set()


class StreamPanel:
    """Per-stream status panel — one row per stream with status + reconnect.

    Construct once (optionally toggling ``selectable`` / ``show_header``),
    then call [`ui`][] with the live ``ctx`` each frame.

    Parameters
    ----------
    selectable
        When True and the stream's source supports ``discover()``,
        auto-populate available targets as inline connect buttons.
    show_header
        Render a uniform ``panel_header`` above the rows.

    Examples
    --------
    >>> from myogestic.widgets import StreamPanel
    >>> panel = StreamPanel()
    >>> panel.ui(ctx)
    """

    def __init__(self, *, selectable: bool = True, show_header: bool = True) -> None:
        self._selectable = selectable
        self._show_header = show_header

    def ui(self, ctx: Context) -> None:
        """Render one row per registered stream. Call once per frame."""
        if self._show_header:
            panel_header("Streams", fa.ICON_FA_PLUG)

        if not ctx.streams:
            imgui.text_colored(_MUTED, "(no streams registered)")
            return

        for name, stream in ctx.streams.items():
            _stream_row(name, stream, selectable=self._selectable)


def _stream_row(name: str, stream: object, *, selectable: bool) -> None:
    from myogestic.stream import Stream

    if not isinstance(stream, Stream):
        imgui.text(f"{name}: (unknown stream type)")
        return

    src_label = type(stream._source).__name__
    connected = stream.status == "connected" and stream.info is not None
    has_discover = hasattr(stream._source, "discover")
    scan = _scans.setdefault(name, _ScanState())

    # --- Top line: dot + name + source + right-aligned icon actions --------
    imgui.text_colored(_OK if connected else _BAD, fa.ICON_FA_CIRCLE)
    imgui.same_line()
    imgui.text(name)
    imgui.same_line()
    imgui.text_colored(_MUTED, f"({src_label})")

    # Push the action buttons to the right edge of the available content.
    btns_w = 60.0 if has_discover and selectable else 28.0
    avail = imgui.get_content_region_avail().x
    if avail > btns_w + 12:
        imgui.same_line(0, avail - btns_w)
    else:
        imgui.same_line()

    if scan.busy:
        imgui.begin_disabled()
    if imgui.small_button(f"{fa.ICON_FA_ARROWS_ROTATE}##sp_rec_{name}"):
        _threading.Thread(target=stream.reconnect, daemon=True).start()
    if scan.busy:
        imgui.end_disabled()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Reconnect to current target")

    if has_discover and selectable:
        imgui.same_line()
        if scan.busy:
            imgui.begin_disabled()
        if imgui.small_button(f"{fa.ICON_FA_MAGNIFYING_GLASS}##sp_scan_{name}"):
            _kickoff_scan(name, stream)
        if scan.busy:
            imgui.end_disabled()
        if imgui.is_item_hovered():
            imgui.set_tooltip("Rescan available sources")

    # --- Detail line: indented under the dot --------------------------------
    imgui.indent(22)
    info = stream.info
    if connected and info is not None:
        last_ts_age = _last_ts_age(stream)
        age_text = f"last {last_ts_age * 1000:.0f} ms" if last_ts_age is not None else "—"
        imgui.text_colored(
            _MUTED,
            f"{info.fs:.0f} Hz · {info.n_channels} ch · window {stream._window:.2f}s · {age_text}",
        )
    else:
        if stream.last_error:
            imgui.text_colored(_MUTED, stream.last_error)
        else:
            imgui.text_colored(_MUTED, "disconnected — waiting for source")

        # Auto-kick a scan on first disconnect so buttons appear without a click.
        if has_discover and selectable and name not in _auto_scanned:
            _auto_scanned.add(name)
            _kickoff_scan(name, stream)

        if has_discover and selectable:
            _connect_buttons(name, stream, scan)

    imgui.unindent(22)
    imgui.spacing()


def _kickoff_scan(name: str, stream: object) -> None:
    """Run `source.discover()` on a daemon thread; mutate `_scans[name]`."""
    scan = _scans.setdefault(name, _ScanState())
    if scan.busy:
        return
    discover_fn = getattr(stream._source, "discover", None)  # type: ignore
    if discover_fn is None:
        return
    scan.busy = True

    def _run() -> None:
        try:
            scan.results = discover_fn()
            scan.selected = 0
        except Exception:
            scan.results = []
        finally:
            scan.busy = False

    _threading.Thread(target=_run, daemon=True).start()


def _connect_buttons(name: str, stream: Stream, scan: _ScanState) -> None:
    """Render available discover() results as inline connect buttons.

    Skips the button whose name matches the stream's *current* (failed) target,
    since clicking it would retry the same thing the Reconnect button does.
    Wraps when the next button would overflow the available width.
    """
    if scan.busy:
        imgui.text_colored(_MUTED, "scanning…")
        return
    if not scan.results:
        return

    current_target = _current_target(stream)
    avail_x0 = imgui.get_cursor_pos_x()
    avail_w = imgui.get_content_region_avail().x

    for r in scan.results:
        target = r.get("name", "")
        if not target or target == current_target:
            continue
        label = f"{target}##sp_button_{name}_{target}"
        # Wrap when the next button would overflow the row.
        text_w = imgui.calc_text_size(target).x + 16
        cursor_x = imgui.get_cursor_pos_x()
        if cursor_x + text_w > avail_x0 + avail_w and cursor_x > avail_x0:
            imgui.new_line()
        if imgui.small_button(label):
            _threading.Thread(
                target=stream.reconnect,
                args=(target,),
                daemon=True,  # type: ignore[attr-defined]
            ).start()
        imgui.same_line()
    imgui.new_line()


def _current_target(stream: object) -> str | None:
    """Best-effort read of the stream name the source is currently targeting.

    Used to suppress the redundant button for the failing target.
    """
    src = stream._source  # type: ignore
    for attr in ("stream_name", "_stream_name", "name", "_name"):
        val = getattr(src, attr, None)
        if isinstance(val, str) and val:
            return val
    return None


def _last_ts_age(stream: object) -> float | None:
    """Seconds since the most recent sample reached the ring buffer.

    Defers to ``Stream.last_timestamp()`` which takes the per-stream lock —
    necessary because ``reconnect()`` zeroes ``_display_n`` and reallocates
    ``_display_t``, so a lock-free read can index a torn buffer.
    """
    last_fn = getattr(stream, "last_timestamp", None)
    if last_fn is None:
        return None
    last = last_fn()
    if last is None:
        return None
    # Streams stamp with pylsl.local_clock() on arrival.
    try:
        from mne_lsl.lsl import local_clock

        now = float(local_clock())
    except Exception:
        now = _time.time()
    age = now - last
    return age if age >= 0.0 else None


__all__ = ["StreamPanel"]
