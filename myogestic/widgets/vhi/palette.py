"""VHI movement palette — a button grid for the VHI control hand's movements.

The Virtual Hand Interface reports its valid movement names over the gRPC
control plane (``VhiControlClient.get_state().available_movements`` — 17 in AI
mode, 15 in Classifier mode). This module renders them as a grid of buttons;
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

from myogestic.widgets.common import DANGER, SUCCESS, panel_header, pop_selected, push_selected

if TYPE_CHECKING:
    from myogestic.vhi._client import VhiControlClient

# Movement button size. Columns are computed from the panel width, so the grid
# reflows as the panel is resized. Width fits VHI's longest name ("ThreeFingerPinch").
_BTN_W = 132.0
_BTN_H = 28.0

_DOT_OK = SUCCESS
_DOT_BAD = DANGER


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
            )


def request_vhi_state_refresh(
    client: VhiControlClient,
    cache: VhiStateCache,
    *,
    force: bool = False,
    min_interval_s: float = 1.0,
    disconnected_interval_s: float = 5.0,
    probe_timeout_s: float = 0.5,
) -> None:
    """Start at most one throttled background ``GetState`` refresh.

    Safe to call every frame from ``@app.ui``: it returns immediately unless a
    refresh is due and none is already in flight. The blocking ``get_state()``
    runs on a daemon thread; the result lands in ``cache`` under its lock.

    While VHI is **unreachable** the poll backs off to ``disconnected_interval_s``
    and uses a short ``probe_timeout_s`` deadline — so a down server is probed
    only occasionally with a fast-failing call, never a 2 s blocking RPC that is
    ~always in flight. (A continuously in-flight failing ``GetState`` keeps the
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

    # Auto-poll: short deadline so a down server fails fast. Explicit refresh:
    # full deadline (None -> client default) since a cold connect may need it.
    timeout = None if force else probe_timeout_s

    def _worker() -> None:
        reply = client.get_state(timeout=timeout)
        with cache.lock:
            cache.refreshing = False
            if reply is None:
                cache.connected = False
                cache.message = "VHI not reachable — launch it, then refresh."
                return
            try:
                cache.movements = list(reply.available_movements)
                cache.current_movement = reply.current_movement
                cache.current_state = reply.current_state
                cache.mode = reply.mode
            except AttributeError as e:
                # A malformed reply (e.g. an incomplete stub) must not take down
                # this daemon thread — surface it instead.
                cache.connected = False
                cache.message = f"VHI reply malformed: {e}"
                return
            cache.connected = True
            cache.message = f"{reply.mode} mode · {len(cache.movements)} movements"

    threading.Thread(target=_worker, daemon=True, name="vhi-state-refresh").start()


def vhi_movement_palette(
    movements: Sequence[str],
    *,
    on_movement: Callable[[str], None],
    on_refresh: Callable[[], None] | None = None,
    current_movement: str = "",
    connected: bool = False,
    status: str = "",
    title: str = "VHI Movements",
) -> None:
    """Render VHI's movement names as a grid of command buttons.

    Pure ImGui: performs no RPC and owns no client. ``movements`` is the cached
    list from the last successful ``GetState``; ``on_movement(name)`` fires on
    click (wire it to ``VhiControlClient.set_movement``). If ``on_refresh`` is
    given, a refresh button is drawn. Movement buttons are disabled while
    ``connected`` is False, but a stale list stays visible.

    The grid uses as many columns as fit the panel width, so it reflows when
    the panel is resized; the button matching ``current_movement`` is highlighted.

    Examples
    --------
    >>> from myogestic.widgets import vhi_movement_palette
    >>> vhi_movement_palette(
    ...     ["Rest", "Fist"], connected=True, on_movement=vhi_client.set_movement
    ... )
    """
    panel_header(title, fa.ICON_FA_HAND)

    if on_refresh is not None:
        if imgui.button(f"{fa.ICON_FA_ARROWS_ROTATE}  Refresh from VHI"):
            on_refresh()
        imgui.same_line()
    imgui.text_colored(_DOT_OK if connected else _DOT_BAD, fa.ICON_FA_CIRCLE)
    imgui.same_line()
    imgui.text_disabled(status or ("connected" if connected else "not connected"))

    if not movements:
        imgui.spacing()
        imgui.text_disabled("No movements yet — launch VHI, then refresh.")
        return

    imgui.spacing()
    # As many columns as fit the current panel width (at least one).
    avail = imgui.get_content_region_avail().x
    spacing = imgui.get_style().item_spacing.x
    n_cols = max(1, int((avail + spacing) // (_BTN_W + spacing)))

    imgui.begin_disabled(not connected)
    for i, name in enumerate(movements):
        if i % n_cols != 0:
            imgui.same_line()
        is_current = name == current_movement
        if is_current:
            push_selected()
        if imgui.button(f"{name}##vhi_mv_{i}", imgui.ImVec2(_BTN_W, _BTN_H)):
            on_movement(name)
        if is_current:
            pop_selected()
    imgui.end_disabled()


__all__ = ["VhiStateCache", "VhiStateSnapshot", "request_vhi_state_refresh", "vhi_movement_palette"]
