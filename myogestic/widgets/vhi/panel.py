"""Compact VHI movement palette — auto-refreshed state + click dispatch in one call.

Wraps the three-piece pattern most examples use verbatim:

  1. Own a [`VhiStateCache`][myogestic.widgets.vhi.palette.VhiStateCache].
  2. Call [`request_vhi_state_refresh`][myogestic.widgets.vhi.palette.request_vhi_state_refresh]
     each frame (throttled, single-flight, off the render thread).
  3. Render [`vhi_movement_palette`][myogestic.widgets.vhi.palette.vhi_movement_palette]
     with the cached snapshot, dispatching clicks to the gRPC client.

For custom workflows (e.g. snapping session labels on palette clicks, or
sharing a single cache across multiple panels), the lower-level building
blocks remain available — this panel is just the common case.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from myogestic.widgets.vhi.palette import (
    VhiStateCache,
    request_vhi_state_refresh,
    vhi_movement_palette,
)

if TYPE_CHECKING:
    from myogestic.vhi._client import VhiControlClient


class VhiMovementPanel:
    """Stateful widget — instantiate once at module level, call ``.ui()`` per frame.

    Example::

        panel = VhiMovementPanel(vhi_client)

        @app.ui
        def ui(ctx):
            with grid[8, 0]:
                panel.ui()

    Parameters
    ----------
    client
        The `VhiControlClient` used to fetch state and dispatch
        ``SetMovement`` commands.
    on_movement
        Click handler for a movement button. Defaults to
        ``client.set_movement``; pass a wrapper to layer side-effects
        (e.g. snap a session label, fire an edge-trigger).
    min_interval_s
        Minimum seconds between background state
        refreshes. Default 1 s.
    title
        Panel header text rendered above the button grid.
    """

    __slots__ = ("_cache", "_client", "_on_movement", "_min_interval_s", "_title")

    def __init__(
        self,
        client: VhiControlClient,
        *,
        on_movement: Callable[[str], None] | None = None,
        min_interval_s: float = 1.0,
        title: str = "VHI Movements",
    ) -> None:
        self._client = client
        self._cache = VhiStateCache()
        self._on_movement = on_movement or client.set_movement
        self._min_interval_s = min_interval_s
        self._title = title

    def ui(self) -> None:
        """Render the panel — call once per frame inside ``@app.ui``."""
        request_vhi_state_refresh(self._client, self._cache, min_interval_s=self._min_interval_s)
        snap = self._cache.snapshot()
        vhi_movement_palette(
            snap.movements,
            connected=snap.connected,
            current_movement=snap.current_movement,
            status=snap.message,
            on_movement=self._on_movement,
            on_refresh=lambda: request_vhi_state_refresh(self._client, self._cache, force=True),
            title=self._title,
        )


__all__ = ["VhiMovementPanel"]
