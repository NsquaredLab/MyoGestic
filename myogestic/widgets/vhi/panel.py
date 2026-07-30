"""Compact VHI control-hand aid — auto-refreshed state + click dispatch in one call.

This is a **VHI recording / control-hand aid**, not a control surface for an
application's own DOFs. It reads the v2 recording aid for state and dispatches clicks
through a caller-supplied handler, which is expected to command a *discrete
DOF* — normally ``bus.select("gesture", state)``, under whatever alias your
mapping file gave that control. The movement names it shows are the renderer's own
vocabulary.

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
    from myogestic.vhi._recording import VhiRecordingClient


class VhiMovementPanel:
    """Stateful widget — instantiate once at module level, call ``.ui()`` per frame.

    Parameters
    ----------
    client
        The `myogestic.vhi.VhiRecordingClient` used to fetch control-hand state
        (available movements, the current one, whether a recording trajectory is running).
    on_movement
        Click handler for a movement button — **required**. Wire it to a
        discrete DOF, e.g. ``lambda s: bus.select("gesture", s)`` — the states come
        from the target's manifest, so pass one of those names through. There
        is deliberately no default: dispatching straight to a renderer would bypass
        the DOF's debounce, which is the only thing protecting a classifier-driven
        session from state chatter.
    min_interval_s
        Minimum seconds between background state
        refreshes. Default 1 s.
    title
        Panel header text rendered above the button grid.

    Examples
    --------
    >>> from myogestic.widgets import VhiMovementPanel
    >>> panel = VhiMovementPanel(
    ...     vhi.recording_client(),
    ...     lambda state: bus.select("gesture", state),
    ... )
    >>> panel.ui()
    """

    __slots__ = ("_cache", "_client", "_on_movement", "_min_interval_s", "_title")

    def __init__(
        self,
        client: VhiRecordingClient,
        on_movement: Callable[[str], None],
        *,
        min_interval_s: float = 1.0,
        title: str = "VHI Control Hand",
    ) -> None:
        self._client = client
        self._cache = VhiStateCache()
        self._on_movement = on_movement
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
