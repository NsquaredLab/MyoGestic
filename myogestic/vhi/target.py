"""Render canonical control values on a Virtual Hand.

`VhiTarget` is the `myogestic.controls.Target` for the VHI: it takes the sanitised
frame a `myogestic.controls.ControlBus` delivers and writes the pose the hand
expects. Today that pose is the legacy 9-channel layout produced by
`myogestic.vhi.legacy.encode_pose`, which is the point — the canonical layer can be
driven end to end against an **unmodified** VHI build, so the standard is proven
before anything on the VHI side changes.

The wire layout lives entirely behind this module. Nothing upstream of it knows that
VHI counts channels, that flexion is negative there, or that three of its channels
are dead; an application declares ``index.flexion`` and this translates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from myogestic.vhi.legacy import LEGACY_POSE_DOFS, encode_pose

if TYPE_CHECKING:
    from collections.abc import Mapping

    import numpy as np

    from myogestic._controls_core import Continuous, ControlSet


class PoseSink(Protocol):
    """The slice of `myogestic.outputs.Output` a `VhiTarget` uses.

    Narrow on purpose: a target needs somewhere to put a pose frame and a way to
    make the last one land before shutdown, nothing more. `myogestic.outputs.LSLOutlet`
    satisfies it, and so does a recorder or a test double — which is why this target
    is testable without a hand running.
    """

    def push(self, data: np.ndarray) -> None:
        """Queue a pose frame for sending."""
        ...

    def flush(self) -> None:
        """Send the queued frame now rather than on the next tick."""
        ...


class VhiTarget:
    """Drive a Virtual Hand from canonical DOF values.

    Parameters
    ----------
    outlet
        Where pose frames go — normally ``virtual_hand().outlet()``. **User-owned**,
        exactly like any `myogestic.outputs.Output`: construct it yourself and
        register its ``stop`` with ``app.cleanup_hooks``. Only `PoseSink.push` and
        `PoseSink.flush` are called on it.

    Notes
    -----
    `bind` **refuses** a configuration this target cannot render rather than
    rendering part of it. A legacy hand has six bones it will move and no wrist, so a
    silently-dropped ``wrist.rotation`` would look exactly like a wrist that is
    working and holding still — the failure a limb controller must never have.

    On shutdown the declared rest frame is pushed *and flushed*. Pushing alone is not
    enough: the send loop is paced, so the frame would sit unsent in the slot while
    the process exits, leaving the hand holding its last commanded pose.

    Examples
    --------
    >>> from myogestic.controls import ControlBus, load_dofs
    >>> from myogestic.vhi import VhiTarget, virtual_hand
    >>>
    >>> controls = load_dofs({"dofs": {"index.flexion": "continuous"}})
    >>> outlet = virtual_hand().outlet()
    >>> bus = ControlBus(controls, targets=[VhiTarget(outlet)])
    >>> _ = bus.push({"index.flexion": 0.8})    # 0.8 flexed, sanitised on the way
    """

    __slots__ = ("_dofs", "_outlet")

    def __init__(self, outlet: PoseSink) -> None:
        self._outlet = outlet
        self._dofs: tuple[Continuous, ...] = ()

    def bind(self, controls: ControlSet) -> None:
        """Accept a pose-only configuration, or refuse it with the reason.

        Raises
        ------
        ValueError
            If the configuration declares discrete DOFs, declares no continuous
            ones, or names a DOF the legacy hand has no channel for.
        """
        if controls.discrete:
            names = [d.name for d in controls.discrete]
            raise ValueError(
                f"VhiTarget cannot render discrete DOFs {names}: legacy VHI's "
                f"ControlMode makes streamed pose and named movements mutually "
                f"exclusive, so one target cannot serve both. Command movements "
                f"through virtual_hand().control_client() for now — the v2 interface "
                f"removes the exclusivity and this restriction goes with it."
            )
        pose = controls.continuous
        if not pose:
            raise ValueError(
                "VhiTarget has nothing to render: the configuration declares no "
                "continuous DOFs. A hand pose is continuous by nature."
            )
        unknown = [d.name for d in pose if d.name not in LEGACY_POSE_DOFS]
        if unknown:
            raise ValueError(
                f"VhiTarget has no legacy channel for {unknown}. An unmodified VHI "
                f"build renders exactly {list(LEGACY_POSE_DOFS)} — its 9-channel pose "
                f"has no wrist at all (channels 6-8 are read by no consumer). Rename "
                f"or drop them; dropping them silently would render as a joint that "
                f"is working and holding still."
            )
        self._dofs = pose

    def send(self, values: Mapping[str, float | str], changed: Mapping[str, str]) -> None:
        """Encode one canonical frame as a legacy pose and push it.

        ``changed`` is unused — `bind` refuses discrete DOFs, so there are no edges
        to deliver. Only the names `bind` accepted are read, and each falls back to
        its own declared rest, so neither a stray key nor a missing one can move a
        joint or raise on the predict thread.
        """
        frame = encode_pose({d.name: float(values.get(d.name, d.rest)) for d in self._dofs})
        self._outlet.push(frame)

    def stop(self) -> None:
        """Return the hand to its declared rest pose, and make sure that lands."""
        if self._dofs:
            self._outlet.push(encode_pose({d.name: d.rest for d in self._dofs}))
        self._outlet.flush()


__all__ = ["PoseSink", "VhiTarget"]
