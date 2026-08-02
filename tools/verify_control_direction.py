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

**The inbound wire is one stream per DOF.** VHI publishes a stream named after the
address itself, one channel wide — `vhi.prediction.index` carries `vhi.prediction.index`
on channel 0 — and applies a DOF the moment its sample arrives; nothing waits for a whole
pose, and a DOF nobody drives holds its last value. The *read-back* outlets are the
exception and are unchanged: `VHI_Predict` and `VHI_Control` are still nine positional
channels of standard values, which is why this file can read channel 2 back without
negotiating anything.

Four things are checked per run:

1. **Direction.** A sweep of the index must bend the rig the way a closing hand bends:
   positive degrees. This is the anchor, and the only check made from *outside* the
   target's own read-back loop — everything below is self-consistency, which a
   target and its read-back agree on whichever way they point. It is also the only
   check that never touches an inlet, so it is unaffected by the shape of the wire.
2. **Round-trip.** A control +1 pushed raw on the DOF's own one-channel stream must read
   back as +1 on `VHI_Predict`, so the target is the identity rather than a sign flip
   — and *every* frame of the hold must read the same, not only the last.
3. **The client's own stack.** The same +1 driven through a `RemoteTarget` and a
   `ControlBus` must produce identically to that raw frame. A different producer, not a
   different declaration: the stream name and the range both come from the target's
   manifest rather than from a constant in this file, so this is the check that catches
   those two disagreeing. There is no channel index left to get wrong — the *name* is
   the only thing a manifest and a target can now disagree about, so that is what the
   raw frame writes down and the negotiated one reads.
4. **The control hand does not disturb the predicted one.** Publishing a control-pose
   stream is the only thing that puts the control hand into Stream mode — there is no
   handshake — so a second inlet binding mid-run is a live event on the target, and
   the predicted hand must read back unchanged through it.

There is nothing to declare any more: a target's whole contract is
`GetControlManifest` plus the streams it reads. What used to be three scenarios varying
what the client had declared is now checks 2-4, which vary who writes the frame.

Two ordering rules, both learned the hard way and both properties of the target rather
than of this tool:

- **The sweep runs before any outlet exists.** `Outlet` repeats its last pushed value at
  `hz`, and the target applies whatever arrives on a DOF's stream — so a still-streaming
  outlet beats `SweepControl`'s own commands and the sweep reports the stream's value
  instead of its own. Held at -0.5, an index sweep reports `+42.5°` and looks like a
  direction bug. One stream per DOF made this *harder* to spot rather than rarer: a stale
  producer now pins the one finger it owns while the rest of the hand still follows the
  rig.
- **One producer per stream at a time, and an outlet is stopped before it is replaced.**
  A second outlet alongside a live one is not a swap: both publish the same name and the
  same `source_id`, so which one VHI reads is resolution order, and the loser's frames go
  nowhere while this tool measures them. So the raw outlet is retired before the
  negotiated targets publish theirs, and `_await_binding` waits for the target to pick
  the replacement up — it re-resolves by name only while it has no inlet at all, so
  recovery otherwise rides on the `source_id`, and is not immediate.

Together those are why a control +1 could appear to move either way earlier: a stale
outlet left streaming by a previous process still wins that DOF's inlet, and which
producer VHI binds depends on resolution order. Per-DOF streams split that hazard nine
ways rather than removing it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

import numpy as np
from mne_lsl.lsl import StreamInlet, resolve_streams

from myogestic.controls import ControlBus, load_control_map, resolve
from myogestic.remote import RemoteTarget
from myogestic.vhi import virtual_hand

#: The DOF driven throughout: the predicted hand's index, whose bare name denotes
#: flexion. Positive X is flexion on this rig — `MovementPoses` reads the other way round
#: because `ApplyMovementPose` negates every row on the way to the bone, which is exactly
#: the trap this check used to fall into: it asserted negative and so passed while the
#: hand bent backwards.
#:
#: It is the name of its own stream too, because that is what VHI publishes: one
#: one-channel stream per address. Written out here rather than read off the manifest
#: because this tool is a *wire* probe — the raw check has to place a frame without
#: asking a client where it goes. Everywhere else the manifest names the stream and
#: nothing in MyoGestic writes a stream name down.
DOF = "vhi.prediction.index"

#: The control hand's counterpart, driven alongside `DOF` in the fourth check — and, on
#: this wire, the name of its stream as well.
POSE_DOF = "vhi.control.pose.index"

#: Where the index sits on `VHI_Predict`. That outlet is what the per-DOF wire did *not*
#: change: nine positional channels, published the same way for every client, which is
#: why a raw frame written by this file can be read back without negotiating anything.
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
    """Write the DOF's own one-channel stream, bypassing every client.

    The counterpart to `_through`: the stream is named from this file rather than from
    the manifest, so the two together tell a target that reads the wrong stream from a
    client that resolved the address onto one.
    """

    def push(value: float) -> None:
        outlet.push(np.array([value], np.float32))

    return push


def _through(bus: ControlBus):
    """Write the same value through the client's own stack — bus, targets, manifest."""
    return lambda value: bus.push({"probe": value})


def _hold(push, inlet: StreamInlet, value: float = PLUS_ONE, seconds: float = 1.2) -> list[float]:
    """Hold one control value on the DOF's stream, then read what the rig made of it."""
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

    Not "is it non-zero": the rig *holds* its last value, and on this wire it holds it
    per DOF — so a non-zero read-back can be what a previous run left there while the
    inlet is no longer being read at all. An early version accepted exactly that and then
    measured a dead inlet, reporting a zero as though the direction were wrong.
    """
    for probe in (0.0, -0.5):
        seen = _hold(push, inlet, value=probe, seconds=0.5)
        if not seen or abs(seen[-1] - probe) > TOL:
            return False
    return True


def _await_binding(push, inlet: StreamInlet, producer: str) -> None:
    """Wait until VHI's inlet is reading `producer` and the read-back follows it.

    Not an assertion: a replaced outlet takes a moment to be recovered — VHI re-resolves
    by name only while it has no inlet at all, so recovery otherwise rides on the outlet's
    stable `source_id`. Measuring through that window would report a zero meaning "not
    yet".
    """
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if _follows(push, inlet):
            return
        time.sleep(0.5)
    raise Failure(
        f"VHI never read {producer} — its inlet did not bind {DOF!r} within 30s, so "
        f"nothing measured through it would mean anything"
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


def _negotiated_bus(vhi, client, *, control_hand: bool = False) -> ControlBus:
    """A bus whose target resolved its streams against the live manifest.

    Nothing here names a stream. The target looks the map's addresses up in the manifest
    and publishes one stream per address it drives, named for that address and one
    channel wide, and it owns every one of them. That is the whole reason this check is
    worth running beside the raw one.
    """
    capabilities = client.capabilities()
    if capabilities is None:
        raise Failure("VHI did not answer GetControlManifest")
    dofs = {"probe": DOF} | ({"pose": POSE_DOF} if control_hand else {})
    control_map = load_control_map({"dofs": dofs})
    target = RemoteTarget(client=client, interface=vhi)
    bus = ControlBus(resolve(control_map, capabilities), targets=[target], hz=32)
    if not target.negotiate():
        raise Failure("the target never settled its contract with VHI")
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
            f"{label}: sent {PLUS_ONE:+.1f}, read back {seen[-1]:+.3f} — the target "
            f"is not the identity on this path"
        )
    print(f"    {label:26s} {seen[-1]:+.3f} over {len(seen)} frames (spread {spread:.3f})")
    return seen[-1]


def check_round_trip(vhi, client, outlet, inlet: StreamInlet) -> dict[str, float]:
    """2-4. Identity and frame stability, from producers that genuinely differ.

    A raw frame this file wrote onto the DOF's own stream; the same value through a
    `RemoteTarget` and a `ControlBus`, where the stream name and the range come from the
    manifest instead; and that again while the control hand's stream is also being
    published. The three must agree — they vary who writes the frame and what else the
    target is reading, never what it was told, because there is nothing left to tell it.
    """
    observed = {"raw frame": _measure("raw frame", _raw(outlet), inlet)}
    # Retired before the targets below publish the same name: two live outlets sharing a
    # name and a `source_id` are not a swap, and the one VHI keeps reading is whichever
    # resolution order left it holding — so the negotiated frames would go nowhere while
    # this file measured the raw outlet's last value and called it agreement. `_one_run`
    # stops it again on the way out, which is idempotent and is what covers a failure
    # raised above this line.
    outlet.stop()

    for label, control_hand in (("through a RemoteTarget", False), ("+ control hand", True)):
        bus = _negotiated_bus(vhi, client, control_hand=control_hand)
        try:
            _await_binding(_through(bus), inlet, label)
            observed[label] = _measure(label, _through(bus), inlet)
        finally:
            # This also stops the outlets the targets built — a target owns an outlet it
            # built itself. One left streaming a control-pose DOF would hold that hand in
            # Stream mode, and beat a later writer to the inlet, for every run after this.
            bus.stop()

    if max(observed.values()) - min(observed.values()) > TOL:
        raise Failure(f"the same +1 measured differently per producer: {observed}")
    return observed


def _relaunch() -> None:
    """Stop any VHI and start a fresh one, so a run cannot inherit target state.

    Nothing is declared any more, but a target still carries state a run can inherit:
    the value it was last left holding on every DOF, and whichever inlets it has already
    bound. A cold process re-proves that an outlet is picked up from nothing.
    """
    subprocess.run(["pkill", "-f", "Godot --path"], check=False, capture_output=True)
    time.sleep(2.0)
    # `launchable` reports rows of (label, argv) for a UI's Launch button, so a tool that
    # actually wants the target running has to spawn them itself.
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

    The sweep first, with no outlet in existence, so `SweepControl` owns the rig; then
    the DOF's own one-channel stream, which `check_round_trip` retires before the
    negotiated targets publish theirs. Creating and dropping it per run is deliberate:
    each run re-proves that a restarted producer is picked up at all.
    """
    print(f"\n{RULE}\nrun {run} of {total}\n{RULE}")
    client = vhi.control_client()
    outlet = None
    try:
        print(f"  1. direction: {check_direction(client)}")
        outlet = vhi.stream_outlet(DOF, n_channels=1)
        _await_binding(_raw(outlet), inlet, "a raw outlet")
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
            print(f"\n✗ run {run}: refused before anything moved:\n{refusal}", file=sys.stderr)
            return 1

    print(f"\n{RULE}")
    print("✓ control +1 flexes, reads back as +1, and does so identically whether the")
    print(f"  frame is written raw or by a negotiated client, across {args.runs} run(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
