"""``ControlMapEditor`` in isolation — the control-map authoring panel.

Point a name of yours at a control the target exports, picking from a list instead of
typing an address. Add more targets to fan one output out to several, give each a weight,
and mark an output as a classifier probability so it is gated to on/off.

To run without a VHI process we hand it a **fake client** whose ``capabilities()``
returns a canned manifest, and a scratch file in the system temp directory — so the
picker, the validation, the collision refusal and Save/Reload all work offline. In a real
app the client is ``virtual_hand().control_client()`` and the path is your own TOML.

Run with:
    uv run python examples/panels/control_map_editor.py
"""

import pathlib
import tempfile

from myogestic import App
from myogestic.controls import Capability
from myogestic.widgets import ControlMapEditor

FINGERS = ("thumb", "index", "middle", "ring", "little")

#: What a VHI build reports, mirrored: one address per control, each carried on a stream
#: named after it and one channel wide. Two aliases pointing at one *address* is the
#: collision the editor refuses — there is no second spelling of a control to collapse
#: first, because a target advertises exactly one.
MANIFEST = [
    *(
        Capability(
            f"vhi.prediction.{digit}",
            "continuous",
            lo=-1.0,
            hi=1.0,
            rest=0.0,
        )
        for digit in FINGERS
    ),
    Capability(
        "vhi.prediction.thumb.abduction",
        "continuous",
        lo=-1.0,
        hi=1.0,
        rest=0.0,
    ),
    Capability(
        "vhi.control.gesture",
        "discrete",
        states=("Rest", "Fist", "Pointing", "ThumbsUp"),
        rest_state="Rest",
    ),
]

SCRATCH = pathlib.Path(tempfile.gettempdir()) / "myogestic_panel_demo_controls.toml"
SCRATCH.write_text(
    '[dofs]\nclose = [\n  { target = "vhi.prediction.index", weight = 0.6 },\n'
    '  { target = "vhi.prediction.middle" },\n]\n'
)


class _FakeTarget:
    """Stand-in for RemoteClient — no gRPC, always answers."""

    def capabilities(self):
        return MANIFEST


editor = ControlMapEditor(SCRATCH, client=_FakeTarget(), title="CONTROL MAP")

app = App("panel: ControlMapEditor")


@app.ui
def ui(ctx):
    if editor.ui():
        # "changed", not "saved": this also fires when the file is edited outside the app
        # and picked up, and when `Save as...` moves to a different file — hence
        # `editor.path` rather than the constant it started on.
        print(f"[editor] changed -> {editor.path}")
        print(editor.resolved_summary())


def main() -> None:
    print(f"editing {SCRATCH} — press Connect, then edit")
    app.run()


if __name__ == "__main__":
    main()
