"""Live check that VHI renders control DOFs as their names claim.

This is the one thing no offline test can prove. ``tests/test_vhi_target.py`` pins
exactly what `myogestic.vhi.VhiTarget` puts on the wire, and
``tests/test_vhi_legacy.py`` pins those wire values against two real recorded
sessions — but both stop at the wire. Whether channel 2 at ``-1`` curls the *index*
finger, and curls rather than extends it, is a fact about VHI's renderer that only
VHI can answer.

Two claims are under test, and each is a decision the migration rests on:

1. **Identity.** The channel map was read out of ``PredictedHandSkeleton.cs``, the
   *consumer*. The fixtures that confirm it come from ``ControlHandSkeleton``, the
   *producer*. They agree, which is strong — but if the two skeletons ever indexed
   differently, offline evidence could not tell.
2. **The extension half renders.** VHI multiplies the sample by a per-bone gain with
   no clamping, so a control ``-1`` should rotate the other way rather than being
   ignored. That reading is why the control domain is signed ``[-1, 1]`` at all. It
   has never been observed, because no operator ever extended on record.

Run it with the VHI binary up — launch it from any example's ProcessLauncher, or
start the binary directly — and watch the **predicted** hand:

    uv run python tools/check_vhi_bridge.py

Each DOF is driven alone to ``+1``, then to ``-1``, then released. Answer the printed
questions as you watch; ~35 s in total.
"""

from __future__ import annotations

import time

from myogestic.controls import Continuous, ControlBus, ControlSet
from myogestic.vhi import VhiTarget, virtual_hand
from myogestic.vhi.pose import POSE_DOFS

#: Seconds to hold each excursion. Long enough to look at, short enough to sit through.
HOLD_S = 1.5

#: What each control name claims will move, for the operator to check against.
EXPECTED = {
    "thumb.flexion": "the thumb curls across the palm",
    "thumb.abduction": "the thumb swings away from the index finger",
    "index.flexion": "the index finger curls",
    "middle.flexion": "the middle finger curls",
    "ring.flexion": "the ring finger curls",
    "little.flexion": "the little finger curls",
}


def main() -> None:
    """Sweep every pose DOF through both directions and print the checklist."""
    # Built directly rather than from a mapping file: this is a rig diagnostic, so the
    # names ARE the pose channels under test — there is no user vocabulary involved.
    controls = ControlSet(dofs={n: Continuous(n) for n in POSE_DOFS})
    outlet = virtual_hand().outlet()
    # No smoothing: a ramp would blur which frame produced which pose.
    bus = ControlBus(controls, targets=[VhiTarget(outlet)])

    print(f"Driving {len(POSE_DOFS)} DOFs, one at a time. Watch the PREDICTED hand.\n")
    observations: list[str] = []
    try:
        for name in POSE_DOFS:
            print(f"{name}  —  at +1, expect: {EXPECTED[name]}")
            for value in (1.0, -1.0):
                print(f"    {value:+.0f} ...", flush=True)
                # The outlet re-sends the latest frame at its own rate, so one push
                # per excursion is enough — no need to spin.
                bus.push({name: value})
                time.sleep(HOLD_S)
            bus.push({name: 0.0})
            time.sleep(0.4)
            observations.append(name)
    finally:
        # Rest the hand and make the frame land before the outlet's thread dies.
        bus.stop()
        outlet.stop()

    print("\nThe hand should now be back at rest.\n")
    print("Answer these — any 'no' blocks the VHI v2 stage:\n")
    for name in observations:
        print(f"  [ ] {name} at +1: {EXPECTED[name]}, and nothing else moved?")
    print("  [ ] every DOF at -1 moved the OPPOSITE way (not ignored, not the same way)?")
    print("  [ ] the hand returned to rest when this script exited?")


if __name__ == "__main__":
    main()
