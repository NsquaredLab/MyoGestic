"""Prove that a canonical +1 always moves the predicted hand the same documented way.

    uv run --extra grpc python tools/verify_canonical_direction.py
    uv run --extra grpc python tools/verify_canonical_direction.py --runs 5 --restart

Needs a live VHI 2. Exits 0 when every check holds, 1 when any of them does not, and 2
when VHI never answered — so it is usable as a gate, not only as something to read.

Why this exists as a tool and not only as a test: VHI's own contract suite proves
*direction* from its rig — a sweep reports bone degrees, checked against the movement
library's `Fist` pose — but it cannot drive the LSL inlet, because liblsl is only
vendored into the packaged build. The inlet is the path every real client uses, so the
claim that mattered most here, "the same +1 renders the same way whatever the client
declared", has to be checked from this side.

Four things are checked per run:

1. **Direction.** A sweep of the index must bend the rig the way a closing hand bends:
   negative degrees. This is the anchor — everything below is self-consistency.
2. **Round-trip.** Canonical +1 pushed on `MyoGestic_Output` must read back as +1 on
   `VHI_Predict`, so the renderer is the identity rather than a sign flip.
3. **Declaration independence.** The same input under three declarations — none,
   predicted-only, and predicted-plus-control-pose — must render identically. A
   conversion gated behind the handshake fails here.
4. **Frame stability.** Every frame of the hold reads the same, not only the last.

The undeclared scenario runs first and is only meaningful on a VHI that has not been
declared to yet: the renderer keeps a declaration for the life of its process. So it
proves its point on the first run, and on every run under `--restart`.

Two ordering rules, both learned the hard way and both properties of the renderer rather
than of this tool:

- **The sweep runs before any outlet exists.** `Output` repeats its last pushed vector at
  `hz`, and the renderer overwrites the whole pose from the inlet every frame — so a
  still-streaming outlet beats `SweepControl`'s own commands and the sweep reports the
  stream's value instead of its own. Held at -0.5, an index sweep reports `+42.5°` and
  looks like a direction bug.
- **One outlet is shared by all three scenarios.** A fresh outlet per scenario made VHI
  read zeros: it re-resolves by name only while it has no inlet at all, so a replaced
  producer is recovered through the outlet's stable `source_id`, not immediately.

Together those are why a canonical +1 could appear to render either way earlier: a stale
outlet left streaming by a previous process still wins the single `MyoGestic_Output`
inlet, and which producer VHI binds depends on resolution order.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

import numpy as np
from mne_lsl.lsl import StreamInlet, resolve_streams

from myogestic.controls import ControlBus, load_control_map, resolve
from myogestic.vhi import VhiTarget, virtual_hand

#: The DOF driven throughout: the predicted hand's index, whose bare name denotes
#: flexion. Its direction is therefore decidable against the rig's own movement library
#: rather than being a matter of taste — a closing hand is what `Movements.Fist` is.
DOF = "vhi.prediction.index"

#: The control hand's counterpart, declared alongside `DOF` in the third scenario.
POSE_DOF = "vhi.control.pose.index"

#: Where the index sits on the pose streams. This is the *rig's* layout, not the
#: declaration's: `VHI_Predict` publishes the same nine channels in the same order
#: whatever a client declared, which is why the undeclared scenario can read it too.
INDEX_CHANNEL = 2

#: The value under test. +1 is the direction the DOF's name denotes.
CANONICAL = 1.0

#: Frames to hold, and the tolerance on a read-back. The rig rounds through degrees, so
#: exact equality is the wrong test; a sign flip is nowhere near this loose.
FRAMES = 12
TOL = 0.05

RULE = "─" * 78


class Failure(Exception):
    """A check did not hold. Carries the message the tool exits with."""


def _read_back(inlet: StreamInlet, frames: int = FRAMES) -> list[float]:
    """Collect up to `frames` samples of the index channel from `VHI_Predict`."""
    seen: list[float] = []
    deadline = time.monotonic() + 6.0
    while len(seen) < frames and time.monotonic() < deadline:
        chunk, _ = inlet.pull_chunk(timeout=0.2, max_samples=32)
        if chunk is not None and len(chunk):
            seen.extend(float(row[INDEX_CHANNEL]) for row in chunk)
    return seen


def _predict_inlet() -> StreamInlet:
    """Open the readback stream, refusing to guess if VHI is not publishing it."""
    for info in resolve_streams(timeout=8.0):
        if info.name == "VHI_Predict":
            inlet = StreamInlet(info)
            inlet.open_stream(timeout=5.0)
            return inlet
    raise Failure("VHI_Predict is not being published — is a VHI 2 running?")


def _hold(
    outlet, inlet: StreamInlet, value: float = CANONICAL, seconds: float = 1.2
) -> list[float]:
    """Hold one canonical value on the pose stream, then read what the rig made of it."""
    sample = np.zeros(9, np.float32)
    sample[INDEX_CHANNEL] = value
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        outlet.push(sample)
        time.sleep(0.02)
    inlet.flush()
    outlet.push(sample)
    time.sleep(0.2)
    return _read_back(inlet)


def _follows(outlet, inlet: StreamInlet) -> bool:
    """Report whether the read-back tracks two different commanded values.

    Not "is it non-zero": the rig *holds* its last pose, so a non-zero read-back can be
    what a previous run left there while the inlet is no longer being read at all. An
    early version accepted exactly that and then measured a dead inlet, reporting a
    zero as though the direction were wrong.
    """
    for probe in (0.0, -0.5):
        seen = _hold(outlet, inlet, value=probe, seconds=0.5)
        if not seen or abs(seen[-1] - probe) > TOL:
            return False
    return True


def _await_binding(outlet, inlet: StreamInlet) -> None:
    """Wait until VHI's inlet is reading this outlet and the read-back follows it.

    Not an assertion: a replaced outlet takes a moment to be recovered — VHI re-resolves
    by name only while it has no inlet at all, so recovery rides on the outlet's stable
    `source_id`. Measuring through that window would report a zero meaning "not yet".
    """
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if _follows(outlet, inlet):
            return
        time.sleep(0.5)
    raise Failure(
        "VHI never read the pose stream — its inlet did not bind `MyoGestic_Output` "
        "within 30s, so nothing below could be measured"
    )


def check_direction(client) -> str:
    """1. A sweep must bend the rig the way a closing hand bends."""
    reply = client.sweep(DOF, duration_s=1.2)
    if reply is None or not reply.completed:
        raise Failure(f"sweep of {DOF} did not complete")
    if not reply.observed:
        raise Failure(f"sweep of {DOF} moved nothing — that is not a pass")
    observed = ", ".join(f"{o.element} {o.degrees_at_hi:+.1f}°" for o in reply.observed)
    backwards = [o.element for o in reply.observed if o.degrees_at_hi >= 0.0]
    if backwards:
        raise Failure(
            f"canonical +1 on {DOF} extended {', '.join(backwards)} instead of flexing "
            f"({observed})"
        )
    return observed


def _declared(vhi, client, outlet, *, with_control_pose: bool) -> ControlBus:
    """A bus that has declared `DOF`, and optionally the control hand's pose too.

    The target is bound to the *shared* outlet rather than a fresh one. Two outlets named
    `MyoGestic_Output` would leave which one VHI reads up to resolution order, and the
    declaration — not the transport — is what this scenario is meant to vary.
    """
    capabilities = client.capabilities()
    if capabilities is None:
        raise Failure("VHI did not answer GetControlManifest")
    dofs = {"probe": DOF} | ({"pose": POSE_DOF} if with_control_pose else {})
    controls = resolve(load_control_map({"dofs": dofs}), capabilities)
    targets = [VhiTarget(outlet, client=client)]
    if with_control_pose:
        targets.append(VhiTarget(vhi.control_outlet(), client=client, stream="control_pose"))
    bus = ControlBus(controls, targets=targets, hz=32)
    for target in targets:
        target.negotiate()
    return bus


def check_scenarios(vhi, client, outlet, inlet: StreamInlet) -> dict[str, float]:
    """2-4. Round-trip, declaration independence, and per-frame stability.

    The pose is pushed on the shared `outlet` in every scenario, so the only thing that
    differs is what was declared over gRPC — which is exactly the variable under test.
    """
    rendered: dict[str, float] = {}
    for label in ("undeclared", "predicted-only", "predicted+control-pose"):
        bus = None
        if label != "undeclared":
            bus = _declared(
                vhi, client, outlet, with_control_pose=label.endswith("control-pose")
            )
        try:
            seen = _hold(outlet, inlet)
        finally:
            if bus is not None:
                bus.stop()
        if len(seen) < 2:
            raise Failure(f"{label}: VHI_Predict returned {len(seen)} sample(s), need frames")
        spread = max(seen) - min(seen)
        if spread > TOL:
            raise Failure(
                f"{label}: the read-back moved while the input was held — "
                f"{min(seen):+.3f} to {max(seen):+.3f} over {len(seen)} frames"
            )
        if abs(seen[-1] - CANONICAL) > TOL:
            raise Failure(
                f"{label}: sent {CANONICAL:+.1f}, read back {seen[-1]:+.3f} — the renderer "
                f"is not the identity on this path"
            )
        rendered[label] = seen[-1]
        print(f"    {label:24s} {seen[-1]:+.3f} over {len(seen)} frames (spread {spread:.3f})")
    if max(rendered.values()) - min(rendered.values()) > TOL:
        raise Failure(f"direction depends on what was declared: {rendered}")
    return rendered


def _relaunch() -> None:
    """Stop any VHI and start a fresh one, so a run cannot inherit a declaration."""
    subprocess.run(["pkill", "-f", "Godot --path"], check=False, capture_output=True)
    time.sleep(2.0)
    # `launchable` reports rows of (label, argv) for a UI's Launch button, so a tool that
    # actually wants the renderer running has to spawn them itself.
    rows = virtual_hand().launchable()
    if not rows:
        raise Failure("--restart needs a launchable VHI install; none was found")
    for _label, argv in rows:
        subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
        )
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        probe = virtual_hand().canonical_client()
        answered = probe.capabilities() is not None
        probe.stop()
        if answered:
            time.sleep(3.0)
            return
        time.sleep(1.0)
    raise Failure("a relaunched VHI never answered")


def _one_run(run: int, total: int, vhi, inlet: StreamInlet) -> None:
    """Everything one run checks, in the one order that measures what it claims to.

    The sweep first, with no outlet in existence, so `SweepControl` owns the rig; then an
    outlet, which every scenario shares. Creating and dropping it per run is deliberate:
    each run re-proves that a restarted producer is picked up at all.
    """
    print(f"\n{RULE}\nrun {run} of {total}\n{RULE}")
    client = vhi.canonical_client()
    outlet = None
    try:
        print(f"  1. direction: {check_direction(client)}")
        outlet = vhi.outlet()
        _await_binding(outlet, inlet)
        print("  2-4. round-trip, declaration independence, frame stability:")
        check_scenarios(vhi, client, outlet, inlet)
    finally:
        if outlet is not None:
            outlet.stop()
        client.stop()


def main() -> int:
    """Run the checks `--runs` times and report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=2, help="repeat the whole check N times")
    parser.add_argument(
        "--restart", action="store_true", help="relaunch VHI between runs (slow)"
    )
    args = parser.parse_args()

    probe = virtual_hand().canonical_client()
    answered = probe.capabilities() is not None
    probe.stop()
    if not answered:
        print("VHI 2 is not answering. Launch it and try again.", file=sys.stderr)
        return 2

    vhi = virtual_hand()
    inlet = _predict_inlet()
    for run in range(1, args.runs + 1):
        try:
            if args.restart and run > 1:
                print("\n  relaunching VHI...")
                _relaunch()
                vhi = virtual_hand()
                inlet = _predict_inlet()
            _one_run(run, args.runs, vhi, inlet)
        except Failure as failure:
            print(f"\n✗ run {run}: {failure}", file=sys.stderr)
            return 1
        except ValueError as refusal:
            # A resolve or negotiate refusal is a result, not a crash: it means this VHI
            # does not export what the tool drives, and the message says which.
            print(f"\n✗ run {run}: refused before anything rendered:\n{refusal}", file=sys.stderr)
            return 1

    print(f"\n{RULE}")
    print("✓ canonical +1 flexes, reads back as +1, and does so identically under every")
    print(f"  declaration, across {args.runs} run(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
