"""Prove that a control +1 always moves the predicted hand the same documented way.

    uv run --extra grpc python tools/verify_control_direction.py
    uv run --extra grpc python tools/verify_control_direction.py --runs 5 --restart

Needs a live VHI 2. Exits 0 when every check holds, 1 when any of them does not, and 2
when VHI never answered — so it is usable as a gate, not only as something to read.

Why this exists as a tool and not only as a test: VHI's own contract suite proves
*direction* from its rig — a sweep reports bone degrees, checked against the movement
library's `Fist` pose — but it cannot drive the LSL inlet, because liblsl is only
vendored into the packaged build. The inlet is the path every real client uses, so the
claim that matters most, "a control +1 flexes, all the way through", has to be checked
from this side.

Four things are checked per run:

1. **Direction.** A sweep of the index must bend the rig the way a closing hand bends:
   positive degrees. This is the anchor, and the only check made from *outside* the
   renderer's own read-back loop — everything below is self-consistency, which a
   renderer and its read-back agree on whichever way they point.
2. **Round-trip.** A control +1 pushed raw on `MyoGestic_Output` must read back as +1 on
   `VHI_Predict`, so the renderer is the identity rather than a sign flip — and *every*
   frame of the hold must read the same, not only the last.
3. **The client's own stack.** The same +1 driven through a negotiated `ControlBus` and
   `VhiTarget` must render identically to that raw frame. A different producer, not a
   different declaration: the channel and the range come from the renderer's manifest
   rather than from a constant in this file, so this is the check that catches those two
   disagreeing.
4. **The control hand does not disturb the predicted one.** Publishing
   `MyoGestic_ControlPose` is now the only thing that puts the control hand into Stream
   mode — there is no handshake — so a second inlet binding mid-run is a live event on
   the renderer, and the predicted hand must read back unchanged through it.

There is nothing to declare any more: a renderer's whole contract is
`GetControlManifest` plus the stream it reads. What used to be three scenarios varying
what the client had declared is now checks 2-4, which vary who writes the frame.

Two ordering rules, both learned the hard way and both properties of the renderer rather
than of this tool:

- **The sweep runs before any outlet exists.** `Output` repeats its last pushed vector at
  `hz`, and the renderer overwrites the whole pose from the inlet every frame — so a
  still-streaming outlet beats `SweepControl`'s own commands and the sweep reports the
  stream's value instead of its own. Held at -0.5, an index sweep reports `+42.5°` and
  looks like a direction bug.
- **One outlet is shared by every check.** A fresh outlet per check made VHI read zeros:
  it re-resolves by name only while it has no inlet at all, so a replaced producer is
  recovered through the outlet's stable `source_id`, not immediately.

Together those are why a control +1 could appear to render either way earlier: a stale
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
#: flexion. Positive X is flexion on this rig — `MovementPoses` reads the other way round
#: because `ApplyMovementPose` negates every row on the way to the bone, which is exactly
#: the trap this check used to fall into: it asserted negative and so passed while the
#: hand bent backwards.
DOF = "vhi.prediction.index"

#: The two stream names, written out here because this tool is a *wire* probe: it pushes
#: raw frames onto the pose stream itself, alongside a `VhiTarget` sharing the same
#: outlet, so it cannot let the target build and name one. Everywhere else the manifest
#: names the stream and nothing in MyoGestic writes these down.
OUTPUT_STREAM = "MyoGestic_Output"
CONTROL_POSE_STREAM = "MyoGestic_ControlPose"

#: The control hand's counterpart, driven alongside `DOF` in the fourth check.
POSE_DOF = "vhi.control.pose.index"

#: Where the index sits on the pose streams. This is the *rig's* layout: `VHI_Predict`
#: publishes the same nine channels in the same order for every client, which is why a
#: raw frame written by this file can be read back without negotiating anything.
INDEX_CHANNEL = 2

#: The value under test. +1 is the direction the DOF's name denotes.
PLUS_ONE = 1.0

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


def _raw(outlet):
    """Write the index channel straight onto the pose stream, bypassing every client.

    The counterpart to `_through`: the channel number comes from this file rather than
    from the manifest, so the two together tell a renderer that is wrong from a client
    that resolved it to the wrong channel.
    """

    def push(value: float) -> None:
        sample = np.zeros(9, np.float32)
        sample[INDEX_CHANNEL] = value
        outlet.push(sample)

    return push


def _through(bus: ControlBus):
    """Write the same value through the client's own stack — bus, target, manifest."""
    return lambda value: bus.push({"probe": value})


def _hold(push, inlet: StreamInlet, value: float = PLUS_ONE, seconds: float = 1.2) -> list[float]:
    """Hold one control value on the pose stream, then read what the rig made of it."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        push(value)
        time.sleep(0.02)
    inlet.flush()
    push(value)
    time.sleep(0.2)
    return _read_back(inlet)


def _follows(push, inlet: StreamInlet) -> bool:
    """Report whether the read-back tracks two different commanded values.

    Not "is it non-zero": the rig *holds* its last pose, so a non-zero read-back can be
    what a previous run left there while the inlet is no longer being read at all. An
    early version accepted exactly that and then measured a dead inlet, reporting a
    zero as though the direction were wrong.
    """
    for probe in (0.0, -0.5):
        seen = _hold(push, inlet, value=probe, seconds=0.5)
        if not seen or abs(seen[-1] - probe) > TOL:
            return False
    return True


def _await_binding(push, inlet: StreamInlet) -> None:
    """Wait until VHI's inlet is reading this outlet and the read-back follows it.

    Not an assertion: a replaced outlet takes a moment to be recovered — VHI re-resolves
    by name only while it has no inlet at all, so recovery rides on the outlet's stable
    `source_id`. Measuring through that window would report a zero meaning "not yet".
    """
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if _follows(push, inlet):
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
    backwards = [o.element for o in reply.observed if o.degrees_at_hi <= 0.0]
    if backwards:
        raise Failure(
            f"control +1 on {DOF} extended {', '.join(backwards)} instead of flexing "
            f"({observed})"
        )
    return observed


def _negotiated_bus(client, outlet, *, control_outlet=None) -> ControlBus:
    """A bus whose targets have resolved `DOF` against the live manifest.

    The predicted target is bound to the *shared* outlet rather than a fresh one: two
    outlets named `MyoGestic_Output` would leave which one VHI reads up to resolution
    order. `control_outlet`, when given, publishes the control hand's stream — which is
    the whole of what puts that hand into Stream mode.
    """
    capabilities = client.capabilities()
    if capabilities is None:
        raise Failure("VHI did not answer GetControlManifest")
    dofs = {"probe": DOF} | ({"pose": POSE_DOF} if control_outlet is not None else {})
    controls = resolve(load_control_map({"dofs": dofs}), capabilities)
    # Named explicitly, which is what splitting one map across a target per hand takes:
    # left to itself each target reads the map to find its stream, and this map names
    # both. Every other caller hands the whole thing to `vhi_targets` instead.
    targets = [VhiTarget(outlet, client=client, stream_name=OUTPUT_STREAM)]
    if control_outlet is not None:
        targets.append(
            VhiTarget(control_outlet, client=client, stream_name=CONTROL_POSE_STREAM)
        )
    bus = ControlBus(controls, targets=targets, hz=32)
    for target in targets:
        target.negotiate()
    return bus


def _measure(label: str, push, inlet: StreamInlet) -> float:
    """Hold +1 through `push` and check every frame of the read-back is +1."""
    seen = _hold(push, inlet)
    if len(seen) < 2:
        raise Failure(f"{label}: VHI_Predict returned {len(seen)} sample(s), need frames")
    spread = max(seen) - min(seen)
    if spread > TOL:
        raise Failure(
            f"{label}: the read-back moved while the input was held — "
            f"{min(seen):+.3f} to {max(seen):+.3f} over {len(seen)} frames"
        )
    if abs(seen[-1] - PLUS_ONE) > TOL:
        raise Failure(
            f"{label}: sent {PLUS_ONE:+.1f}, read back {seen[-1]:+.3f} — the renderer "
            f"is not the identity on this path"
        )
    print(f"    {label:26s} {seen[-1]:+.3f} over {len(seen)} frames (spread {spread:.3f})")
    return seen[-1]


def check_round_trip(vhi, client, outlet, inlet: StreamInlet) -> dict[str, float]:
    """2-4. Identity and frame stability, from producers that genuinely differ.

    A raw frame this file wrote; the same value through the client's own negotiated
    stack, where the channel comes from the manifest instead; and that again while the
    control hand's stream is also being published. The three must agree — they vary who
    writes the frame and what else the renderer is reading, never what it was told,
    because there is nothing left to tell it.
    """
    rendered = {"raw frame": _measure("raw frame", _raw(outlet), inlet)}

    bus = _negotiated_bus(client, outlet)
    try:
        rendered["through a VhiTarget"] = _measure("through a VhiTarget", _through(bus), inlet)
    finally:
        bus.stop()

    # Owned here, not by the bus: a `VhiTarget` deliberately does not stop an outlet it
    # was handed, and one left streaming `MyoGestic_ControlPose` would hold the control
    # hand in Stream mode — and beat a later writer to the inlet — for every run after
    # this one.
    control_outlet = vhi.stream_outlet(CONTROL_POSE_STREAM)
    bus = _negotiated_bus(client, outlet, control_outlet=control_outlet)
    try:
        rendered["+ control hand"] = _measure("+ control hand", _through(bus), inlet)
    finally:
        bus.stop()
        control_outlet.stop()

    if max(rendered.values()) - min(rendered.values()) > TOL:
        raise Failure(f"the same +1 rendered differently per producer: {rendered}")
    return rendered


def _relaunch() -> None:
    """Stop any VHI and start a fresh one, so a run cannot inherit renderer state.

    Nothing is declared any more, but a renderer still carries state a run can inherit:
    the hand it was last left holding, and whichever inlet it has already bound. A cold
    process re-proves that an outlet is picked up from nothing.
    """
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
        probe = virtual_hand().control_client()
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
    outlet, which every check shares. Creating and dropping it per run is deliberate:
    each run re-proves that a restarted producer is picked up at all.
    """
    print(f"\n{RULE}\nrun {run} of {total}\n{RULE}")
    client = vhi.control_client()
    outlet = None
    try:
        print(f"  1. direction: {check_direction(client)}")
        outlet = vhi.stream_outlet(OUTPUT_STREAM)
        _await_binding(_raw(outlet), inlet)
        print("  2-4. round-trip, the client's own stack, and the control hand:")
        check_round_trip(vhi, client, outlet, inlet)
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

    probe = virtual_hand().control_client()
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
    print("✓ control +1 flexes, reads back as +1, and does so identically whether the")
    print(f"  frame is written raw or by a negotiated client, across {args.runs} run(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
