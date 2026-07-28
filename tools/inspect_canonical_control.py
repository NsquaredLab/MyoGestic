"""A narrated walk through the canonical control standard, end to end.

Run it to *see* the system work rather than read about it:

    uv run --extra grpc python tools/inspect_canonical_control.py

Safe anywhere. It needs no Virtual Hand: with none running it still walks steps 1-3 and
then shows you exactly how a target behaves when its renderer is absent. Launch a VHI
first and the same script negotiates with it and reads back what was rendered — against
a v2 build *or* a v1 build, which is step 4's whole point.

It creates one transient LSL outlet and, if a VHI is up, moves its hand. It writes no
files, changes no configuration, and leaves the hand at rest.
"""

from __future__ import annotations

import time
import tomllib

import numpy as np

from myogestic.controls import ControlBus, load_dofs
from myogestic.outputs.filters import OneEuroFilter
from myogestic.vhi import VhiTarget, virtual_hand
from myogestic.vhi.legacy import LEGACY_POSE_DOFS, decode_pose

# --- 1. The declaration -------------------------------------------------------
#
# Mapping-first: the *shape* of each value says what kind of DOF it is. A string is a
# continuous DOF at its defaults, an array is a discrete DOF's states, and a table is the
# explicit form for when you need to say more.

DECLARATION = """
[dofs]
"index.flexion" = "continuous"
"hand.gesture"  = ["rest", "fist"]
"""

# The same declaration, with the two things this walkthrough wants to show: a one-way
# range, and a stability gate on the discrete DOF.
DECLARATION_FULL = """
[dofs]
"index.flexion" = "continuous"
"grip.force"    = { kind = "continuous", range = [0.0, 1.0] }
"hand.gesture"  = { kind = "discrete", states = ["rest", "fist"], rest = "rest", debounce_s = 0.1 }
"""

RULE = "─" * 78


def heading(n: int, text: str) -> None:
    """Print a numbered section rule."""
    print(f"\n{RULE}\n{n}. {text}\n{RULE}")


def step_1_declare():
    """Parse TOML and load it. The library never reads the file itself."""
    heading(1, "The declaration — mapping-first TOML")
    print(DECLARATION.strip())
    print("\n  The value's shape is the discriminator: a string is continuous, an array")
    print("  is a discrete DOF's states. That is the smallest form that works.\n")
    print("  With the details spelled out:")
    print("\n".join("   " + line for line in DECLARATION_FULL.strip().splitlines()))

    # tomllib lives in the application, not the library: `load_dofs` takes a Mapping, so
    # MyoGestic reads no config files. Use JSON, a dict literal, or a database if you like.
    controls = load_dofs(tomllib.loads(DECLARATION_FULL))

    print("\n  load_dofs(tomllib.loads(...)) ->")
    for dof in controls.dofs.values():
        if dof.name in {d.name for d in controls.continuous}:
            print(
                f"    {dof.name:16s} continuous  range=[{dof.lo:+.1f}, {dof.hi:+.1f}]  "
                f"rest={dof.rest:+.1f}"
            )
        else:
            print(
                f"    {dof.name:16s} discrete    states={list(dof.states)}  "
                f"rest={dof.rest!r}  debounce={dof.debounce_s}s"
            )
    print(f"\n  wire order (continuous only): {list(controls.channel_labels())}")
    print("  +1 always means the direction the DOF's name denotes. No channel numbers.")
    return controls


class Watch:
    """A `Target` that records only the discrete edges it was handed."""

    def __init__(self) -> None:
        self.edges: list[dict] = []

    def bind(self, controls) -> None:
        """Accept anything — this target renders nothing."""

    def send(self, values, changed) -> None:
        """Note an edge, ignore the continuous values."""
        if changed:
            self.edges.append(dict(changed))

    def stop(self) -> None:
        """Nothing to release."""


class Wire:
    """A stand-in for an LSL outlet that records what it was handed."""

    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []

    def push(self, data: np.ndarray) -> None:
        """Record a frame instead of sending it."""
        self.frames.append(np.asarray(data).copy())

    def flush(self) -> None:
        """Nothing to flush — there is no send thread here."""


def step_2_kinds(controls):
    """Continuous values are filtered; discrete states are gated. Never the reverse."""
    heading(2, "Two kinds of control, two kinds of protection")

    seen_widths: list[int] = []
    smoother = OneEuroFilter()

    def spy(vec):
        seen_widths.append(len(vec))
        return smoother(vec)

    bus = ControlBus(controls, targets=[Watch()], smoothing=spy, hz=50)

    print("  a) A continuous step arrives as a ramp (layer 1: ControlBus smoothing)")
    for _ in range(4):
        bus.push({"index.flexion": 0.0, "hand.gesture": "rest"})
    ramp = []
    for _ in range(6):
        ramp.append(round(float(bus.push({"index.flexion": 1.0})["index.flexion"]), 3))
    print(f"     commanded 1.0 six times -> {ramp}")
    print("     Smoothing runs BEFORE any target sees the frame, so every target agrees")
    print("     on what was commanded.")

    print("\n  b) A chattering classifier produces no transition (layer 2: debounce)")
    watcher = Watch()
    gated = ControlBus(controls, targets=[watcher], hz=50)
    edges = watcher.edges
    for i in range(10):
        gated.push({"hand.gesture": "fist" if i % 2 else "rest"})
    print(f"     10 alternating ticks -> edges delivered: {edges}")
    for _ in range(8):
        gated.push({"hand.gesture": "fist"})
    print(f"     then 8 ticks holding 'fist' -> edges delivered: {edges}")
    print("     A discrete DOF is a HELD STATE. It is never numerically filtered:")
    print("     averaging 'rest' and 'fist' would interpolate through a state nobody")
    print(f"     selected. The filter only ever saw {seen_widths[0]}-wide vectors — the")
    print("     continuous channels — so the discrete one is excluded by construction.")


def step_3_wire():
    """What a legacy-encoding target puts on the wire."""
    heading(3, "What reaches the wire")
    # A pose-only configuration, because an un-negotiated target renders the legacy
    # 9-float pose and that wire carries no discrete state at all — it says so rather
    # than dropping one.
    pose = load_dofs(
        {"dofs": dict.fromkeys(["index.flexion", "middle.flexion"], "continuous")}
    )
    wire = Wire()
    bus = ControlBus(pose, targets=[VhiTarget(wire)], hz=50)
    bus.push({"index.flexion": 1.0, "middle.flexion": 0.5})
    frame = wire.frames[-1]
    print(f"  last frame: {np.array2string(frame, precision=2)}")
    print("\n  Nine floats, because that is what the transport carries. Note:")
    print("   - channels 6-8 are always 0 — no consumer reads them, there is no wrist;")
    print("   - the sign is the *renderer's*, not the standard's. This target has not")
    print("     negotiated, so it used the legacy encoding where -1 means flexion.")
    print("\n  decode_pose reads such a frame back as canonical values:")
    decoded = decode_pose(frame.astype(np.float32))
    for name in LEGACY_POSE_DOFS[:3]:
        print(f"    {name:16s} -> {float(decoded[name]):+.3f}")
    print("\n  That is also how archived recordings are read, permanently: VHI's outlets")
    print("  stay in renderer units so old sessions keep their meaning.")


def step_4_live():
    """Negotiate with whatever VHI is actually there — v2, v1, or none."""
    heading(4, "Against a real Virtual Hand")

    # Deliberately a configuration BOTH a v1 and a v2 build can render, so the same
    # declaration demonstrates the negotiated path and the fallback.
    controls = load_dofs(
        {
            "dofs": {
                "index.flexion": "continuous",
                "middle.flexion": "continuous",
                "hand.gesture": {
                    "kind": "discrete",
                    "states": ["rest", "fist"],
                    "rest": "rest",
                    "debounce_s": 0.1,
                },
            }
        }
    )
    print(f"  declaring {list(controls.dofs)}\n")
    vhi = virtual_hand()
    canonical = vhi.canonical_client()
    legacy = vhi.control_client()
    outlet = vhi.outlet()
    target = VhiTarget(outlet, client=canonical, legacy_client=legacy)
    bus = ControlBus(controls, targets=[target], hz=32)

    reply = canonical.declare(controls)
    settled = target.negotiate()

    if reply is None and not settled:
        print("  No VHI is reachable.")
        print("   - Declare returned None, which means 'this build does not speak v2'")
        print("     OR 'nothing is listening'. Those are indistinguishable, so bind()")
        print("     DEFERS instead of deciding — an application that launches VHI from")
        print("     its own UI necessarily binds before VHI exists.")
        print("   - negotiate() returned False and will settle it once VHI appears.")
        print("   - A discrete edge in the meantime is dropped with a warning, never")
        print("     silently, and never by raising on the predict thread.")
        print("\n  Launch a VHI and run this again to see steps 4b/4c.")
    elif reply is None:
        print("  A v1-only VHI is running — the COMPATIBILITY FALLBACK.")
        print("   - Declare returned None, so the target fell back on its own.")
        print(f"   - negotiated={target.negotiated} (False = legacy path)")
        print("   - Continuous DOFs go out as the legacy pose; the discrete DOF is")
        print("     rendered through v1 SetMovement, resolved case-insensitively")
        print("     against the movement names VHI reports it has.")
        bus.push({"index.flexion": 1.0})
        bus.select("hand.gesture", "fist")
        time.sleep(2.0)
        state = legacy.get_state(timeout=3.0)
        if state is not None:
            print(f"   - VHI's current movement is now {state.current_movement!r}")
        print("\n  Nothing in the application changed to make this work. That is the")
        print("  point of the fallback, and it stays until a VHI 2.0 release ships.")
    else:
        names = {0: "UNSPECIFIED", 1: "CANONICAL", 2: "LEGACY_NEGATED"}
        print("  A v2 VHI is running — NEGOTIATED.")
        print(f"   - accepted={reply.accepted}  standard={reply.standard_version!r}")
        print(f"   - continuous stream : {reply.continuous_stream_name!r}")
        print(f"   - channel order     : {list(reply.continuous_channel_order)}")
        print(f"   - encoding          : {names.get(reply.continuous_encoding, '?')}")
        for verdict in reply.verdicts:
            mark = "renders as" if verdict.renderable else "REFUSED:"
            detail = verdict.renders_as if verdict.renderable else verdict.message
            print(f"   - {verdict.name:16s} {mark} {detail}")
        print("\n   VHI answered which DOFs it can render, on which channels, and in")
        print("   which convention. A reply that would not state the encoding is")
        print("   treated as 'cannot negotiate' — guessing a sign inverts a limb.")

        rendered = _observe(bus, target)
        if rendered is not None:
            print(f"\n   commanded index.flexion=+1  ->  VHI rendered {rendered:+.2f}")
            print("   (rig units, where -1 is flexion: the hand flexed)")

        print("\n   And a stable discrete state:")
        for _ in range(10):
            bus.push({"hand.gesture": "fist"})
            time.sleep(0.02)
        time.sleep(1.5)
        aid = vhi.training_client()
        state = aid.state()
        if state is not None:
            print(f"   held 'fist' for 10 ticks -> VHI movement {state.current_movement!r}")
        aid.stop()

    bus.stop()
    print("\n  bus.stop() delivered rest and flushed it, so the hand released rather")
    print("  than freezing in its last pose.")
    outlet.stop()
    canonical.stop()
    legacy.stop()


def _observe(bus, target) -> float | None:
    """Command a flexion and read back what VHI rendered, or None if unreadable."""
    from mne_lsl.lsl import StreamInlet, resolve_streams

    inlet = None
    for stream in resolve_streams(timeout=4):
        if stream.name == "VHI_Predict":
            inlet = StreamInlet(stream)
            inlet.open_stream(timeout=5)
    if inlet is None:
        return None

    # Channel 2 is where the negotiation put index.flexion. Watch *that* channel
    # specifically: waiting for "any channel moved" would report whatever pose the hand
    # happened to be holding.
    channel = LEGACY_POSE_DOFS.index("index.flexion")
    bus.push({"index.flexion": 1.0})
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        inlet.flush()
        time.sleep(0.4)
        data, stamps = inlet.pull_chunk(timeout=0.5)
        if len(stamps):
            frame = np.asarray(data)[-1]
            if abs(frame[channel]) > 0.8:
                return float(frame[channel])
    return None


def step_5_commands():
    """Print the commands a reader can run themselves."""
    heading(5, "Commands you can run")
    print("""  This walkthrough, with no Virtual Hand (safe anywhere):
      uv run --extra grpc python tools/inspect_canonical_control.py

  Then launch a Virtual Hand and run it again to see the negotiation:
      python -m myogestic.tools.install_vhi        # if you have not installed it
      # start VHI from any example's Launch button, or run the binary directly
      uv run --extra grpc python tools/inspect_canonical_control.py

  Confirm what the hand actually renders, per DOF, in signed degrees:
      uv run python tools/check_vhi_bridge.py

  A full application using all of this:
      uv run --extra examples --extra grpc python examples/synthetic/emg_regression.py

  The contracts themselves:
      myogestic/controls.py                      the standard
      myogestic/vhi/target.py                    negotiation + fallback
      myogestic/vhi/_proto/myogestic_vhi_v2.proto  the wire contract""")


def main() -> None:
    """Walk all five steps."""
    print(RULE)
    print("The canonical control standard, end to end")
    print(RULE)
    controls = step_1_declare()
    step_2_kinds(controls)
    step_3_wire()
    step_4_live()
    step_5_commands()
    print()


if __name__ == "__main__":
    main()
