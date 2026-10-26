"""``VhiMovementPanel`` in isolation — the Virtual Hand control-hand aid.

A button grid of the VHI control hand's movements: it auto-refreshes state in the
background, highlights the current movement, and dispatches clicks to a handler you
supply. Normally the state comes from a live ``RecordingClient`` and the handler
commands a discrete DOF (``bus.select("gesture", state)``); to run
without a VHI process we hand it a **fake aid** whose ``state()`` returns a canned
movement list, and a handler that just logs — so refresh, highlighting, and click
dispatch all work offline.

Note the panel takes the handler explicitly rather than defaulting to "command the
target". Dispatching straight at the target would bypass the DOF's debounce, which
is the only thing protecting a classifier-driven session from state chatter.

Run with:
    uv run python examples/panels/vhi_movements.py
"""

from types import SimpleNamespace

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, VhiMovementPanel

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


class _FakeRecordingAid:
    """Stand-in for RecordingClient — no gRPC, never raises."""

    def __init__(self) -> None:
        self.current = "Fist"

    def state(self):
        return SimpleNamespace(
            available_movements=MOVEMENTS,
            current_movement=self.current,
            animation_state="waiting",
            trajectory_running=False,
            trajectory_movement="",
        )


aid = _FakeRecordingAid()


def _on_movement(state: str) -> None:
    """Stands in for `bus.select("gesture", state)` in a real app."""
    aid.current = state
    print(f"[vhi] discrete state -> {state!r}")


panel = VhiMovementPanel(aid, _on_movement)

app = App("panel: VhiMovementPanel")
header = AppHeader("VhiMovementPanel", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        panel.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
