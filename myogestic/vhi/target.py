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

import logging
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from myogestic.vhi.legacy import LEGACY_POSE_DOFS, LEGACY_POSE_WIDTH, encode_pose

if TYPE_CHECKING:
    from collections.abc import Mapping

    from myogestic._controls_core import Continuous, ControlSet

log = logging.getLogger("myogestic.vhi_target")

# The v2 `ContinuousEncoding` values, spelled out so this module does not import the
# generated protobuf (which needs the grpc extra) just to read three integers.
_ENCODING_UNSPECIFIED = 0
_ENCODING_CANONICAL = 1
_ENCODING_LEGACY_NEGATED = 2


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

    Speaks v2 when VHI does, and the legacy pose when it does not. Which one is
    settled once, at `bind`, by asking — never by a version constant in this file.

    Parameters
    ----------
    outlet
        Where pose frames go — normally ``virtual_hand().outlet()``. **User-owned**,
        exactly like any `myogestic.outputs.Output`: construct it yourself and
        register its ``stop`` with ``app.cleanup_hooks``. Only `PoseSink.push` and
        `PoseSink.flush` are called on it.
    client
        Optional `myogestic.vhi._client_v2.VhiCanonicalClient`. When given, `bind`
        negotiates the control space over it; without one this target is legacy-only.
        Also carries discrete state, which the legacy wire cannot express at all.

    Notes
    -----
    `bind` **refuses** a configuration it cannot render rather than rendering part of
    it. A legacy hand has six bones it will move and no wrist, so a silently-dropped
    ``wrist.rotation`` would look exactly like a wrist that is working and holding
    still — the failure a limb controller must never have.

    The fallback is deliberately all-or-nothing. A partly-understood v2 negotiation
    is *more* dangerous than no negotiation: it would leave some DOFs believed
    rendered and others quietly dropped. So anything short of a clean accept — an
    older VHI, an unreachable one, a refused DOF, a channel order the outlet cannot
    carry — falls all the way back to the legacy path, which then applies its own
    refusals.

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

    __slots__ = ("_client", "_dofs", "_negate", "_order", "_outlet", "_width")

    def __init__(self, outlet: PoseSink, *, client: Any = None) -> None:
        self._outlet = outlet
        self._client = client
        self._dofs: tuple[Continuous, ...] = ()
        #: Negotiated channel order in v2 mode; empty means the legacy path.
        self._order: tuple[str, ...] = ()
        #: Whether the negotiated wire wants canonical values negated.
        self._negate = False
        self._width = LEGACY_POSE_WIDTH

    @property
    def negotiated(self) -> bool:
        """Whether `bind` settled on the v2 contract rather than the legacy pose."""
        return bool(self._order)

    def bind(self, controls: ControlSet) -> None:
        """Negotiate with VHI if possible, else accept a legacy pose-only config.

        Raises
        ------
        ValueError
            When the legacy path is taken *and* the configuration declares discrete
            DOFs, declares no continuous ones, or names a DOF the legacy hand has no
            channel for. A negotiated v2 binding has none of those limits — VHI said
            what it can render.
        """
        self._order = ()
        self._negate = False
        if self._client is not None and self._negotiate(controls):
            return
        self._bind_legacy(controls)

    def _negotiate(self, controls: ControlSet) -> bool:
        """Try the v2 handshake. False means "use the legacy path", never an error."""
        reply = self._client.declare(controls, client_name="myogestic")
        if reply is None:
            return False
        if not reply.accepted:
            refused = {v.name: v.message for v in reply.verdicts if not v.renderable}
            log.warning(
                "VHI declined part of the control space, falling back to the legacy "
                "pose: %s. Rendering only what it accepted would leave the rest "
                "looking like joints that work and hold still.",
                refused,
            )
            return False
        order = tuple(reply.continuous_channel_order)
        expected = controls.channel_labels()
        if set(order) != set(expected):
            log.warning(
                "VHI negotiated channels %s but the configuration declares %s — "
                "falling back to the legacy pose rather than guessing the mapping.",
                list(order),
                list(expected),
            )
            return False
        if len(order) > self._width:
            log.warning(
                "VHI negotiated %d channels but this outlet carries only %d. Falling "
                "back to the legacy pose; construct the outlet with at least the "
                "negotiated width to use v2.",
                len(order),
                self._width,
            )
            return False
        # How to encode the stream is not a detail to infer. A server that does not
        # say gets no benefit of the doubt: guessing wrong inverts every joint, which
        # is exactly how the first end-to-end v2 run made a hand extend when it was
        # told to flex.
        encoding = getattr(reply, "continuous_encoding", _ENCODING_UNSPECIFIED)
        if encoding not in (_ENCODING_CANONICAL, _ENCODING_LEGACY_NEGATED):
            log.warning(
                "VHI negotiated channel names but did not say how to encode them "
                "(continuous_encoding=%r). Falling back to the legacy pose rather "
                "than guessing a sign convention.",
                encoding,
            )
            return False
        self._dofs = controls.continuous
        self._order = order
        self._negate = encoding == _ENCODING_LEGACY_NEGATED
        log.info(
            "VHI negotiated the canonical contract: %s (%s)",
            list(order),
            "legacy-negated wire" if self._negate else "canonical wire",
        )
        return True

    def _bind_legacy(self, controls: ControlSet) -> None:
        """The pre-v2 path: a six-DOF pose on a nine-channel wire, or a refusal."""
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
        """Encode one canonical frame for whichever contract `bind` settled on.

        Only the names `bind` accepted are read, and each falls back to its own
        declared rest, so neither a stray key nor a missing one can move a joint or
        raise on the predict thread.

        ``changed`` carries discrete edges. On the legacy path there are none — `bind`
        refuses discrete DOFs there. In v2 they go over gRPC, because a keystroke-like
        state change is not a pose and re-sending it every tick is not the same thing
        as re-sending a number.
        """
        self._outlet.push(self._frame(values))
        if changed and self._client is not None and self.negotiated:
            self._client.set_control(discrete=dict(changed))

    def _frame(self, values: Mapping[str, float | str]) -> np.ndarray:
        """The wire frame for this binding — negotiated order, or the legacy pose."""
        each = {d.name: float(values.get(d.name, d.rest)) for d in self._dofs}
        if not self.negotiated:
            return encode_pose(each)
        # Negotiated: VHI told us the order, and canonical values go out unnegated.
        # The legacy sign flip was never part of the standard — it was a property of
        # the old wire, and v2 does not have it.
        #
        # The negotiated order is a *prefix* of the transport, not its full width: the
        # outlet's channel count is fixed at construction and VHI will not name a
        # channel it does not read. The tail stays at zero rather than being dropped,
        # because the frame width is what the outlet validates against.
        sign = -1.0 if self._negate else 1.0
        frame = np.zeros(self._width, dtype=np.float32)
        for i, name in enumerate(self._order):
            frame[i] = sign * each[name]
        return frame

    def stop(self) -> None:
        """Return the hand to its declared rest pose, and make sure that lands."""
        if self._dofs:
            self._outlet.push(self._frame({d.name: d.rest for d in self._dofs}))
        self._outlet.flush()


__all__ = ["PoseSink", "VhiTarget"]
