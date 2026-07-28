"""``VhiMovementPanel`` in isolation — the Virtual Hand control-hand aid.

A button grid of the VHI control hand's movements: it auto-refreshes state in the
background, highlights the current movement, and dispatches clicks to a handler you
supply. Normally the state comes from a live ``VhiTrainingAidClient`` and the handler
commands a canonical discrete DOF (``bus.select("hand.gesture", state)``); to run
without a VHI process we hand it a **fake aid** whose ``state()`` returns a canned
movement list, and a handler that just logs — so refresh, highlighting, and click
dispatch all work offline.

Note the panel takes the handler explicitly rather than defaulting to "command the
renderer". Dispatching straight at a renderer would bypass the DOF's debounce, which
is the only thing protecting a classifier-driven session from state chatter.

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


class _FakeTrainingAid:
    """Stand-in for VhiTrainingAidClient — no gRPC, never raises."""

    def __init__(self) -> None:
        self.current = "Fist"

    def state(self):
        return SimpleNamespace(
            available_movements=MOVEMENTS,
            current_movement=self.current,
            animation_state="waiting",
            program_running=False,
            program_movement="",
        )


aid = _FakeTrainingAid()


def _on_movement(state: str) -> None:
    """Stands in for `bus.select("hand.gesture", state)` in a real app."""
    aid.current = state
    print(f"[vhi] canonical discrete state -> {state!r}")


panel = VhiMovementPanel(aid, _on_movement)

app = App("panel: VhiMovementPanel")


@app.ui
def ui(ctx):
    panel.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
