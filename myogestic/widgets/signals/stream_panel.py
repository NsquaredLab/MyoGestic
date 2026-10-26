"""Compact stream status rows with outlet discovery and cancellable connections."""

from __future__ import annotations

import re
import threading as _threading
import time as _time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic._theme import mono_font
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    SUCCESS,
    WARNING,
    format_age,
    mono_text,
    muted,
    panel_header,
    tinted_row,
    ui_px,
)
from myogestic.widgets.signals._scan import _scans, _ScanState

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import Stream


@dataclass
class _Attempt:
    """One widget's connection attempt, retained until its worker finishes."""

    started: float = field(default_factory=_time.monotonic)
    busy: bool = True
    aborted: bool = False


class StreamPanel:
    """One-line stream states with reconnect, abort, retry, and outlet picks.

    Connected rows show a mono name, sample rate, channels and sample age.
    Detached streams are idle with Connect; failures show the error with Retry.
    Connecting rows show elapsed time and Abort. The header dot summarises the
    worst state and its rescan action refreshes discovered outlets.

    Parameters
    ----------
    selectable
        Connect opens a popover of discovered outlets when the source supports
        ``discover()``. Otherwise it reconnects the configured source directly.
    show_header
        Render the standard Streams header, state dot and rescan action.
    widget_id
        ImGui identity, defaulting to this instance. Give a stable unique ID
        when rendering multiple panels. Connection state belongs to each
        instance; only outlet discovery is deliberately shared with viewers.

    Examples
    --------
    >>> from myogestic.widgets import StreamPanel
    >>> panel = StreamPanel()
    >>> panel.ui(ctx)
    """

    def __init__(
        self, *, selectable: bool = True, show_header: bool = True,
        widget_id: str | None = None,
    ) -> None:
        self._selectable = selectable
        self._show_header = show_header
        self._widget_id = widget_id or f"streams:{id(self)}"
        self._attempts: dict[str, _Attempt] = {}

    def ui(self, ctx: Context) -> None:
        """Render one compact row per registered stream, once per frame."""
        imgui.push_id(self._widget_id)
        try:
            if self._show_header:
                self._header(ctx)
            if not ctx.streams:
                imgui.text_wrapped("No streams registered. Add a stream to connect its source.")
            for name, stream in ctx.streams.items():
                self._row(name, stream, ctx)
        finally:
            imgui.pop_id()

    def _header(self, ctx: Context) -> None:
        streams = list(ctx.streams.values())
        attached = [s.status == "connected" and s.info is not None for s in streams]
        problem = any(s.last_error for s in streams) or any(a.busy for a in self._attempts.values())
        tone = (WARNING if problem or (any(attached) and not all(attached)) else
                SUCCESS if attached and all(attached) else IDLE)
        style = imgui.get_style()
        width = imgui.calc_text_size(fa.ICON_FA_ARROWS_ROTATE).x + 2 * style.frame_padding.x
        panel_header("Streams", fa.ICON_FA_PLUG, reserve=width + style.item_spacing.x, status=tone)
        imgui.same_line()
        imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(0, imgui.get_content_region_avail().x - width))
        if imgui.small_button(f"{fa.ICON_FA_ARROWS_ROTATE}##sp_rescan"):
            for name, stream in ctx.streams.items():
                _kickoff_scan(name, stream)
        imgui.set_item_tooltip("Rescan available sources")

    def _row(self, name: str, stream: Stream, ctx: Context) -> None:
        attempt = self._attempts.get(name)
        busy = attempt is not None and attempt.busy
        connected = stream.status == "connected" and stream.info is not None
        if busy:
            elapsed = max(0, _time.monotonic() - attempt.started)
            detail = f"connecting… {elapsed:.0f} s" if not attempt.aborted else "aborting…"
            tone, label = IDLE, "Abort"
        elif stream.last_error:
            detail, tone, label = stream.last_error, DANGER, "Retry"
        elif connected:
            detail = f"{stream.info.fs:.0f} Hz · {stream.info.n_channels} ch · {format_age(_last_ts_age(stream))}"
            tone, label = SUCCESS, fa.ICON_FA_ARROWS_ROTATE
        else:
            detail, tone, label = "not connected", IDLE, "Connect"
        recording = bool(getattr(ctx, "recording", False))
        disabled = recording or bool(busy and attempt.aborted)
        popup_width = imgui.get_content_region_avail().x
        with tinted_row(
            tone if tone in (DANGER, SUCCESS) else None,
            height=max(ui_px(26), imgui.get_frame_height() + ui_px(8)),
        ) as width:
            style = imgui.get_style()
            left = imgui.get_cursor_pos_x()
            action_w = imgui.calc_text_size(label).x + 2 * style.frame_padding.x
            imgui.align_text_to_frame_padding()
            imgui.text_colored(tone, fa.ICON_FA_CIRCLE)
            imgui.same_line()
            text_w = max(0, width - (imgui.get_cursor_pos_x() - left) - action_w - 2 * style.item_spacing.x)
            name_w = min(_mono_width(name), text_w * 0.35)
            mono_text(_fit_mono(name, name_w))
            imgui.set_item_tooltip(name)
            imgui.same_line()
            detail_w = max(0, left + width - action_w - style.item_spacing.x - imgui.get_cursor_pos_x())
            shown = _fit_mono(detail, detail_w)
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(0, detail_w - _mono_width(shown)))
            mono_text(shown, muted())
            imgui.set_item_tooltip(detail)
            imgui.same_line()
            imgui.set_cursor_pos_x(left + width - action_w)
            imgui.begin_disabled(disabled)
            clicked = imgui.button(f"{label}##sp_conn_{name}")
            imgui.end_disabled()
            if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
                imgui.set_tooltip("Stop the recording before changing connections." if recording else
                                  "Abort this connection attempt" if busy else
                                  "Reconnect this stream" if connected else "Connect this stream")
            if clicked and not disabled:
                if busy:
                    self._abort(name, stream, ctx)
                elif label == "Connect" and self._selectable and hasattr(stream._source, "discover"):
                    imgui.open_popup(f"outlets##{name}")
                    _kickoff_scan(name, stream)
                else:
                    self._connect(name, stream, ctx)
        self._outlets(name, stream, ctx, popup_width)

    def _outlets(self, name: str, stream: Stream, ctx: Context, width: float) -> None:
        popup = f"outlets##{name}"
        if not imgui.is_popup_open(popup):
            return
        imgui.set_next_window_size(imgui.ImVec2(width, 0))
        if not imgui.begin_popup(popup):
            return
        try:
            scan = _scans.setdefault(name, _ScanState())
            busy = scan.busy
            imgui.begin_disabled(busy)
            if imgui.small_button(f"{fa.ICON_FA_ARROWS_ROTATE}##sp_scan_{name}"):
                _kickoff_scan(name, stream)
            imgui.end_disabled()
            imgui.set_item_tooltip("Rescan available outlets")
            if busy:
                imgui.text_wrapped("Scanning for outlets…")
            elif not scan.results:
                imgui.text_wrapped("No outlets found. Start the source, then rescan.")
            recording = bool(getattr(ctx, "recording", False))
            imgui.begin_disabled(busy or recording)
            for index, result in enumerate(scan.results):
                target = result.get("name", "")
                if not target:
                    continue
                detail = _outlet_detail(result)
                full = f"{target} · {detail}" if detail else target
                font = mono_font()
                if font is not None:
                    imgui.push_font(font, imgui.get_style().font_size_base)
                shown = _fit_mono(full, imgui.get_content_region_avail().x)
                clicked, _ = imgui.selectable(f"{shown}##sp_outlet_{index}", False)
                if font is not None:
                    imgui.pop_font()
                imgui.set_item_tooltip(full)
                if clicked and not busy and not recording:
                    self._connect(name, stream, ctx, target)
                    imgui.close_current_popup()
            imgui.end_disabled()
        finally:
            imgui.end_popup()

    def _connect(self, name: str, stream: Stream, ctx: Context, target: str | None = None) -> None:
        """Connect off-thread; keep an aborted attempt busy until it settles."""
        if (name in self._attempts and self._attempts[name].busy) or bool(getattr(ctx, "recording", False)):
            return
        attempt = _Attempt()
        self._attempts[name] = attempt
        stream.last_error = ""
        ctx.log(f"{name}: connecting…")

        def run() -> None:
            try:
                ok = stream.reconnect(target)
                if not attempt.aborted:
                    if ok:
                        stream.last_error = ""
                        ctx.log(f"{name}: connected")
                    else:
                        stream.last_error = stream.last_error or "Connection failed. Check the source and retry."
                        ctx.log(f"{name}: connect failed — {stream.last_error}")
            except Exception as exc:
                if not attempt.aborted:
                    stream.last_error = str(exc) or type(exc).__name__
                    ctx.log(f"{name}: connect failed — {stream.last_error}")
            finally:
                if attempt.aborted:
                    stream.disconnect()
                attempt.busy = False

        _threading.Thread(target=run, daemon=True).start()

    def _abort(self, name: str, stream: Stream, ctx: Context) -> None:
        """Close the source to interrupt connection and reject any late result."""
        attempt = self._attempts.get(name)
        if attempt is not None and attempt.busy:
            attempt.aborted = True
            stream.disconnect()
            ctx.log(f"{name}: connect aborted")


def _mono_width(text: str) -> float:
    font = mono_font()
    if font is not None:
        imgui.push_font(font, imgui.get_style().font_size_base)
    width = imgui.calc_text_size(text).x
    if font is not None:
        imgui.pop_font()
    return width


def _fit_mono(text: str, width: float) -> str:
    text = " ".join(text.split())
    if _mono_width(text) <= width:
        return text
    if _mono_width("…") > width:
        return ""
    while text and _mono_width(text + "…") > width:
        text = text[:-1]
    return text + "…"


def _outlet_detail(result: dict[str, str]) -> str:
    """Normalise LSL discovery's compact units; preserve serial descriptions."""
    detail = result.get("info", "")
    channels = re.search(r"(\d+)\s*ch\b", detail)
    rate = re.search(r"([\d.]+)\s*Hz\b", detail)
    if channels and rate:
        return f"{channels[1]} ch · {rate[1]} Hz"
    return detail


def _kickoff_scan(name: str, stream: Stream) -> None:
    """Refresh the shared discovery cache off-thread."""
    scan = _scans.setdefault(name, _ScanState())
    discover = getattr(stream._source, "discover", None)
    if scan.busy or discover is None:
        return
    scan.busy = True

    def run() -> None:
        try:
            scan.results = discover()
            scan.selected = 0
        except Exception:
            scan.results = []
        finally:
            scan.busy = False

    _threading.Thread(target=run, daemon=True).start()


def _last_ts_age(stream: object) -> float | None:
    """Seconds since the most recent sample reached the ring buffer.

    Must go through ``Stream.last_timestamp()``, which takes the per-stream lock:
    ``reconnect()`` zeroes ``_display_n`` and reallocates ``_display_t``, so a
    lock-free read can index a torn buffer.
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
