"""VHI movement palette — wrapping movement chips for the VHI control hand's movements.

The Virtual Hand Interface reports its valid movement names over the gRPC
control plane (``RecordingClient.state().available_movements`` — 17 in AI
mode, 15 in Classifier mode). This module renders them as wrapping chips;
clicking one commands that movement on VHI's control hand.

Two pieces, deliberately separate:

* ``vhi_movement_palette(...)`` — a **pure ImGui widget**. No RPC, no client,
  no ML coupling. It draws a cached movement list and fires callbacks.
* ``VhiStateCache`` + ``request_vhi_state_refresh(...)`` — a throttled,
  single-flight background refresher. ``get_state()`` is a blocking ~2 s call,
  so it must never run in the 60 fps frame loop; this runs it on a daemon
  thread and lands the result in the cache.

The example owns the cache and the client; the widget stays generic::

    from myogestic.widgets import (
        VhiStateCache, request_vhi_state_refresh, vhi_movement_palette,
    )

    vhi_state = VhiStateCache()          # module level

    @app.ui
    def ui(ctx):
        request_vhi_state_refresh(vhi_client, vhi_state)   # safe every frame
        snap = vhi_state.snapshot()
        vhi_movement_palette(
            snap.movements,
            connected=snap.connected,
            current_movement=snap.current_movement,
            status=snap.message,
            on_movement=vhi_client.set_movement,
            on_refresh=lambda: request_vhi_state_refresh(
                vhi_client, vhi_state, force=True
            ),
        )
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import (
    IDLE,
    SUCCESS,
    _truncate_to_width,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    push_selected,
    ui_px,
)

if TYPE_CHECKING:
    from myogestic.remote._recording import RecordingClient


@dataclass(frozen=True)
class VhiStateSnapshot:
    """An immutable, lock-free view of ``VhiStateCache`` for one UI frame.

    Examples
    --------
    >>> from myogestic.widgets import VhiStateCache, VhiStateSnapshot
    >>> snapshot: VhiStateSnapshot = VhiStateCache(movements=["Rest"]).snapshot()
    >>> snapshot.movements
    ('Rest',)
    """

    movements: tuple[str, ...]
    current_movement: str
    current_state: str
    mode: str
    connected: bool
    message: str
    trajectory_running: bool = False
    trajectory_movement: str = ""


@dataclass
class VhiStateCache:
    """Last-known VHI state, refreshed off-thread. Use ``snapshot()`` to read.

    Examples
    --------
    >>> from myogestic.widgets import VhiStateCache
    >>> state = VhiStateCache()
    >>> snapshot = state.snapshot()
    """

    movements: list[str] = field(default_factory=list)
    current_movement: str = ""
    current_state: str = ""
    mode: str = ""
    trajectory_running: bool = False
    trajectory_movement: str = ""
    connected: bool = False
    refreshing: bool = False
    message: str = "Launch VHI, then refresh."
    last_attempt_s: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> VhiStateSnapshot:
        """Return a consistent, immutable view — safe to read all frame."""
        with self.lock:
            return VhiStateSnapshot(
                movements=tuple(self.movements),
                current_movement=self.current_movement,
                current_state=self.current_state,
                mode=self.mode,
                connected=self.connected,
                message=self.message,
                trajectory_running=self.trajectory_running,
                trajectory_movement=self.trajectory_movement,
            )


def request_vhi_state_refresh(
    client: RecordingClient,
    cache: VhiStateCache,
    *,
    force: bool = False,
    min_interval_s: float = 1.0,
    disconnected_interval_s: float = 5.0,
    probe_timeout_s: float = 0.5,  # noqa: ARG001 - kept for API compatibility
) -> None:
    """Start at most one throttled background ``GetRecordingSessionState`` refresh.

    Safe to call every frame from ``@app.ui``: it returns immediately unless a
    refresh is due and none is already in flight. The blocking ``state()``
    runs on a daemon thread; the result lands in ``cache`` under its lock.

    While VHI is **unreachable** the poll backs off to ``disconnected_interval_s``
    and (historically) used a short ``probe_timeout_s`` deadline — so a down server is probed
    only occasionally with a fast-failing call, never a 2 s blocking RPC that is
    ~always in flight. (A continuously in-flight failing call keeps the
    gRPC channel in connect/reconnect churn, which stutters the 60 fps render
    loop.) Once connected it polls every ``min_interval_s`` again. An explicit
    ``force`` refresh ignores the interval and uses the client's full deadline
    (a cold connect can be slower than ``probe_timeout_s``).

    Examples
    --------
    >>> from myogestic.widgets import VhiStateCache, request_vhi_state_refresh
    >>> state = VhiStateCache()
    >>> request_vhi_state_refresh(vhi_client, state)
    """
    now = time.monotonic()
    with cache.lock:
        interval = (
            min_interval_s if cache.connected else max(min_interval_s, disconnected_interval_s)
        )
        if cache.refreshing or (not force and now - cache.last_attempt_s < interval):
            return
        cache.refreshing = True
        cache.last_attempt_s = now

    def _worker() -> None:
        # Reads the recording aid: this palette is a control-hand *aid*, so its state
        # comes from the aid that owns that hand.
        reply = client.state()
        with cache.lock:
            cache.refreshing = False
            if reply is None:
                cache.connected = False
                cache.message = "VHI not reachable — launch it, then refresh."
                return
            try:
                cache.movements = list(reply.available_movements)
                cache.current_movement = reply.current_movement
                cache.current_state = reply.animation_state
                cache.trajectory_running = reply.trajectory_running
                cache.trajectory_movement = reply.trajectory_movement
                cache.mode = "recording" if reply.trajectory_running else "movement"
            except AttributeError as e:
                # A malformed reply (e.g. an incomplete stub) must not take down
                # this daemon thread — surface it instead.
                cache.connected = False
                cache.message = f"VHI reply malformed: {e}"
                return
            cache.connected = True
            if reply.trajectory_running:
                cache.message = f"recording trajectory: {reply.trajectory_movement}"
            else:
                cache.message = f"{len(cache.movements)} movements"

    threading.Thread(target=_worker, daemon=True, name="vhi-state-refresh").start()


def vhi_movement_palette(
    movements: Sequence[str],
    *,
    on_movement: Callable[[str], None],
    on_refresh: Callable[[], None] | None = None,
    current_movement: str = "",
    connected: bool = False,
    status: str = "",
    title: str = "Hand movements",
    widget_id: str = "vhi_movements",
) -> None:
    """Render wrapping movement chips with the current movement selected.

    Pure ImGui: performs no RPC and owns no client. ``on_movement(name)`` fires
    on click; wire it to a discrete DOF such as ``bus.select("gesture", name)``.
    While disconnected, launch instructions and an optional Refresh action replace
    the cached list. ``widget_id`` isolates multiple palettes in the same window.

    Examples
    --------
    >>> from myogestic.widgets import vhi_movement_palette
    >>> vhi_movement_palette(
    ...     ["Rest", "Fist"], connected=True, on_movement=vhi_client.set_movement
    ... )
    """
    imgui.push_id(widget_id)
    try:
        style = imgui.get_style()
        refresh_w = imgui.calc_text_size(fa.ICON_FA_ARROWS_ROTATE).x + 2 * style.frame_padding.x
        panel_header(
            title,
            fa.ICON_FA_HAND,
            status=SUCCESS if connected else IDLE,
            reserve=refresh_w + style.item_spacing.x if on_refresh else 0.0,
        )
        if connected:
            imgui.set_item_tooltip(status or "The hand is reachable")
        if on_refresh is not None:
            imgui.same_line()
            avail = imgui.get_content_region_avail().x
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(0.0, avail - refresh_w))
            if imgui.small_button(f"{fa.ICON_FA_ARROWS_ROTATE}##refresh"):
                on_refresh()
            imgui.set_item_tooltip("Refresh movements")

        if not connected or not movements:
            lines = (
                ("The hand is not running", "Launch it, then refresh to load its movements.")
                if not connected
                else ("No movements available", "Refresh to load the hand's movements.")
            )
            available = imgui.get_content_region_avail()
            imgui.set_cursor_pos_y(
                imgui.get_cursor_pos_y() + max(0.0, (available.y - ui_px(140)) / 2)
            )
            for line in lines:
                left = imgui.get_cursor_pos_x()
                width = imgui.get_content_region_avail().x
                imgui.set_cursor_pos_x(left + max(0.0, (width - imgui.calc_text_size(line).x) / 2))
                imgui.push_style_color(imgui.Col_.text, muted())
                imgui.text_wrapped(line)
                imgui.pop_style_color()
            if on_refresh is not None:
                width = imgui.calc_text_size("Refresh").x + 2 * style.frame_padding.x
                imgui.set_cursor_pos_x(
                    imgui.get_cursor_pos_x()
                    + max(0.0, (imgui.get_content_region_avail().x - width) / 2)
                )
                if imgui.button("Refresh"):
                    on_refresh()
            return

        left = imgui.get_cursor_pos_x()
        available = imgui.get_content_region_avail().x
        used = 0.0
        for index, name in enumerate(movements):
            width = min(available, imgui.calc_text_size(name).x + 2 * style.frame_padding.x)
            if used and used + style.item_spacing.x + width <= available:
                imgui.same_line()
                used += style.item_spacing.x
            else:
                used = 0.0
                imgui.set_cursor_pos_x(left)
            label = name
            budget = width - 2 * style.frame_padding.x
            if imgui.calc_text_size(label).x > budget:
                label = _truncate_to_width(name, budget - imgui.calc_text_size("…").x) + "…"
            selected = name == current_movement
            if selected:
                push_selected()
            clicked = imgui.button(f"{label}##vhi_mv_{index}", imgui.ImVec2(width, ui_px(26)))
            if selected:
                pop_selected()
            imgui.set_item_tooltip(name)
            if clicked:
                on_movement(name)
            used += width
        mono_text(f"{len(movements)} movements", muted())
    finally:
        imgui.pop_id()


__all__ = ["VhiStateCache", "VhiStateSnapshot", "request_vhi_state_refresh", "vhi_movement_palette"]
