"""``VhiMovementPanel`` in isolation — the Virtual Hand movement grid.

A button grid of the VHI control hand's movements: it auto-refreshes state
in the background, highlights the current movement, and dispatches clicks
to the client. Normally that client is a live gRPC ``VhiControlClient``; to
run without a VHI process we hand it a **fake client** whose ``get_state``
returns a canned movement list and whose ``set_movement`` just logs — so
refresh, highlighting, and click dispatch all work offline.

Run with:
    uv run python examples/panels/vhi_movements.py
"""

from types import SimpleNamespace

from myogestic import App
from myogestic.widgets import VhiMovementPanel

MOVEMENTS = (
    "Rest",
    "Fist",
    "Open",
    "Pinch",
    "ThumbsUp",
    "PointIndex",
    "ThreeFingerPinch",
    "WristFlex",
    "WristExtend",
    "WristPronate",
    "WristSupinate",
    "KeyGrip",
)


class _FakeVhiClient:
    """Stand-in for VhiControlClient — no gRPC, never raises."""

    def __init__(self) -> None:
        self.current = "Fist"

    def get_state(self, timeout: float | None = None):
        return SimpleNamespace(
            available_movements=MOVEMENTS,
            current_movement=self.current,
            current_state="idle",
            mode="MOVEMENT",
        )

    def set_movement(self, name: str) -> None:
        self.current = name
        print(f"[vhi] set_movement({name!r})")


panel = VhiMovementPanel(_FakeVhiClient())

app = App("panel: VhiMovementPanel")


@app.ui
def ui(ctx):
    panel.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
