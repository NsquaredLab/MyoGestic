"""Render control values on a Virtual Hand.

`VhiTarget` is the `myogestic.controls.Target` for the VHI: it takes the sanitised frame
a `myogestic.controls.ControlBus` delivers and writes the pose the hand expects.

**The wire layout lives entirely behind this module.** Nothing upstream of it knows that
VHI counts channels, that the renderer's units run the other way, or that three of its
nine channels are dead; an application declares its own alias, maps it onto an address
VHI publishes, and this translates.

Every fact about where a value goes comes from VHI's own manifest, asked for at bind
time — never from a table in this file. A build that grows a control therefore needs no
change here, and a build that disagrees with the configuration is refused rather than
guessed at.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

# Imported at runtime, not just for typing: the routed path needs isinstance checks to
# tell a streamed continuous alias from a discrete one. _controls_core has no dependency
# back on this module, so this cannot re-create the import cycle the core/bus split fixed.
from myogestic._controls_core import Continuous

if TYPE_CHECKING:
    from collections.abc import Mapping

    from myogestic._controls_core import ControlSet

log = logging.getLogger("myogestic.vhi_target")

# The v2 `ContinuousEncoding` values, spelled out so this module does not import the
# generated protobuf (which needs the grpc extra) just to read three integers.
_ENCODING_UNSPECIFIED = 0
_ENCODING_CANONICAL = 1
_ENCODING_NEGATED = 2

#: Channels on VHI's pose transport. A fallback only — the outlet is asked first, since
#: an application constructs it and may have made it wider.
_POSE_WIDTH = 9


def _encoding_of(capability: Any) -> int:
    """A capability's declared wire encoding, defaulting to canonical."""
    return int(getattr(capability, "encoding", _ENCODING_CANONICAL) or _ENCODING_CANONICAL)


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
    """Drive a Virtual Hand from control values.

    Requires a VHI that speaks the v2 control contract: it *asks* the renderer what it
    exports and refuses anything it cannot place. There is no fallback and no table of
    channel numbers — a pre-2.0 build is reported as unsupported rather than driven on
    a guess.

    Parameters
    ----------
    outlet
        Where pose frames go — normally ``virtual_hand().outlet()``. **User-owned**,
        exactly like any `myogestic.outputs.Output`: construct it yourself and
        register its ``stop`` with ``app.cleanup_hooks``. Only `PoseSink.push` and
        `PoseSink.flush` are called on it.
    client
        A `myogestic.vhi._client_v2.VhiCanonicalClient` — ``virtual_hand().canonical_client()``.
        Required: it is what the control space is negotiated over, and it carries
        discrete state, which the pose transport cannot express at all.
    stream
        Which of the renderer's pose streams this target drives: ``"output"`` (the
        default — the predicted hand) or ``"control_pose"`` (the control hand). It
        decides which channel order *and which encoding* the target reads out of the
        handshake. The two streams do not share a convention, so a target that guessed
        would be right on one and inverted on the other.

    Notes
    -----
    `bind` **refuses** a configuration it cannot render rather than rendering part of
    it: an address the renderer does not export, one it does not carry on this stream,
    two aliases aimed at one control. A silently-dropped control would look exactly
    like a control that is working and holding still — the failure a limb controller
    must never have.

    Binding is **deferred** rather than decided when the renderer is silent, because an
    application that launches VHI from its own UI necessarily binds before VHI exists.
    Call `negotiate` once it is up. A renderer that *answers* and does not speak v2 is a
    settled fact, and raises.

    On shutdown the declared rest frame is pushed *and flushed*. Pushing alone is not
    enough: the send loop is paced, so the frame would sit unsent in the slot while
    the process exits, leaving the hand holding its last commanded pose.

    Examples
    --------
    >>> from myogestic.controls import ControlBus, load_control_map, resolve
    >>> from myogestic.vhi import VhiTarget, virtual_hand
    >>>
    >>> vhi = virtual_hand()
    >>> client = vhi.canonical_client()
    >>> control_map = load_control_map({"dofs": {"my_index": "vhi.prediction.index"}})
    >>> controls = resolve(control_map, client.capabilities())   # needs VHI running
    >>> bus = ControlBus(controls, targets=[VhiTarget(vhi.outlet(), client=client)])
    >>> _ = bus.push({"my_index": 0.8})        # sanitised on the way to the wire
    """

    __slots__ = (
        "_answered", "_client", "_dofs", "_negate", "_negotiated", "_order", "_outlet",
        "_pending", "_routed", "_slots", "_stream", "_width",
    )

    def __init__(
        self,
        outlet: PoseSink,
        *,
        client: Any = None,
        stream: str = "output",
    ) -> None:
        if stream not in ("output", "control_pose"):
            raise ValueError(
                f"stream must be 'output' or 'control_pose', got {stream!r}"
            )
        self._stream = stream
        self._outlet = outlet
        self._client = client
        #: The configuration still awaiting a reachable VHI, or None once settled.
        self._pending: ControlSet | None = None
        #: Whether VHI has ever *answered* the handshake. "It refused" and "it never
        #: replied" need opposite handling: the first is a settled fact, the second is
        #: an application that has not launched its renderer yet.
        self._answered = False
        self._dofs: tuple[Continuous, ...] = ()
        #: Negotiated channel order.
        self._order: tuple[str, ...] = ()
        #: Whether the negotiated wire wants values negated. The renderer declares this;
        #: it is never inferred, because guessing inverts every joint.
        self._negate = False
        #: Declared DOFs paired with the channel VHI put them on, for a name-declared
        #: configuration.
        self._slots: tuple[tuple[int, Continuous], ...] = ()
        #: Address-routed slots: (channel, alias, weight, sign, lo, hi). Non-empty when
        #: the configuration was resolved against a manifest, which is what distinguishes
        #: an alias-mapped set from a name-declared one.
        self._routed: tuple[tuple[int, str, float, float, float, float], ...] = ()
        #: Tracked explicitly rather than inferred from `_order`: a configuration of
        #: only discrete DOFs negotiates fine and has an empty channel order.
        self._negotiated = False
        self._width = int(getattr(outlet, "n_channels", _POSE_WIDTH) or _POSE_WIDTH)

    @property
    def negotiated(self) -> bool:
        """Whether the contract has been settled with the renderer."""
        return self._negotiated

    def bind(self, controls: ControlSet) -> None:
        """Negotiate the control space with VHI, or defer until it is reachable.

        Raises
        ------
        ValueError
            When no client was given, when the renderer answers and does not speak the
            v2 contract, or when it answers and the configuration cannot be rendered —
            an address it does not export, one it does not carry on this stream, or two
            aliases aimed at one control.
        """
        self._order = ()
        self._slots = ()
        self._routed = ()
        self._pending = None
        self._negate = False
        self._negotiated = False
        self._answered = False
        if not controls.dofs:
            # Checked here rather than left to the handshake: a renderer accepts an empty
            # declaration quite happily, and the result is a target that is bound,
            # negotiated, and renders nothing at all.
            raise ValueError(
                "VhiTarget has nothing to render: the configuration declares no DOFs "
                "at all."
            )
        if self._client is None:
            raise ValueError(
                "VhiTarget needs a canonical client: every channel, range and state "
                "comes from the renderer's manifest, so without one there is nothing "
                "to render against. Pass client=virtual_hand().canonical_client()."
            )
        if self._negotiate(controls):
            return
        if self._answered:
            # Reachable and not speaking v2. A settled fact, not a transient one.
            raise ValueError(
                "this Virtual Hand does not serve the v2 control contract, so its "
                "controls cannot be discovered. MyoGestic 2.x requires VHI 2.0 or "
                "newer — upgrade the renderer (python -m myogestic.tools.install_vhi), "
                "or run one from source with $VHI_PATH and $GODOT_BIN."
            )
        # Silent. An application that launches VHI from its own UI binds before VHI
        # exists, so decide nothing: defer and let `negotiate` settle it.
        self._pending = controls

    def negotiate(self, *, force: bool = False) -> bool:
        """Retry the handshake now — for an application that launches its own renderer.

        `bind` runs when the `myogestic.controls.ControlBus` is constructed, which for
        an app that spawns VHI from its own UI is necessarily *before* VHI exists. `bind`
        therefore defers rather than deciding, and this settles it once the renderer is
        actually there.

        Cheap and idempotent when already settled, so it is fine to call from a button
        handler. Never call it from the predict thread — it blocks on an RPC.

        Parameters
        ----------
        force
            Re-run the handshake even if one already succeeded. Needed after the
            renderer restarts: VHI's side of the contract is *stateful* (declaring a
            control-pose stream also puts its control hand into Stream mode), and a
            restart loses that while this target still believes it is negotiated. There
            is no automatic detection of that today, so an application that reconnects
            deliberately should re-declare deliberately.

        Returns
        -------
        bool
            Whether the contract is settled. ``False`` means VHI has not answered yet,
            so nothing is being rendered and this will keep retrying.

        Raises
        ------
        ValueError
            If the renderer answers and does not speak v2, or answers and the
            configuration cannot be rendered. Both are configuration-level facts rather
            than transient ones, so they are raised rather than swallowed; call this
            from a setup path or a button handler where a traceback is visible, never
            from the predict thread.
        """
        if force and self._pending is None:
            # Re-arm from whatever is currently bound, so a caller does not have to
            # remember the ControlSet to re-declare it.
            rebuilt = self._rebound()
            if rebuilt is not None:
                self._pending = rebuilt
                self._negotiated = False
                self._answered = False
        controls = self._pending
        if controls is None:
            return self._negotiated
        if self._negotiate(controls):
            self._pending = None
            return True
        if self._answered:
            raise ValueError(
                "this Virtual Hand does not serve the v2 control contract, so its "
                "controls cannot be discovered. MyoGestic 2.x requires VHI 2.0 or "
                "newer — upgrade the renderer (python -m myogestic.tools.install_vhi), "
                "or run one from source with $VHI_PATH and $GODOT_BIN."
            )
        return False

    def _negotiate(self, controls: ControlSet) -> bool:
        """Try the handshake. False means "no answer yet", never a refusal."""
        pose = "canonical" if self._stream == "control_pose" else ""
        routes = getattr(controls, "routes", None) or {}
        if routes:
            return self._negotiate_routed(controls, routes, pose)
        return self._negotiate_by_name(controls, pose)

    def _negotiate_routed(self, controls: ControlSet, routes: Mapping, pose: str) -> bool:
        """Resolve alias -> address -> channel through the renderer's own manifest.

        The addresses come from the configuration, the channels and ranges come from the
        renderer. Nothing here decides where a control lives; it asks, and refuses rather
        than guessing when the answer does not cover what was configured.
        """
        fetch = getattr(self._client, "capabilities", None)
        capabilities = fetch() if callable(fetch) else None
        self._answered = capabilities is not None or getattr(
            self._client, "unimplemented", False
        )
        if capabilities is None:
            return False
        # Only this stream's controls. A renderer publishes several, and a channel index
        # means nothing across them — routing an address from the wrong stream would put
        # a value on a same-numbered channel of a different hand.
        wanted = (
            "MyoGestic_ControlPose" if self._stream == "control_pose" else "MyoGestic_Output"
        )
        by_address = {
            cap.address: cap
            for cap in capabilities
            if not getattr(cap, "stream_name", "") or cap.stream_name == wanted
        }

        reply = self._client.declare(controls, client_name="myogestic", control_pose=pose)
        if reply is None:
            return False
        if not reply.accepted:
            refused = {v.name: v.message for v in reply.verdicts if not v.renderable}
            raise ValueError(
                f"this target declined part of the control space: {refused}. Rendering "
                f"only what it accepted would leave the rest looking like controls that "
                f"work and hold still."
            )

        slots: list[tuple[int, str, float, float, float, float]] = []
        taken: dict[int, str] = {}
        for alias, refs in routes.items():
            if alias not in controls.dofs or not isinstance(controls.dofs[alias], Continuous):
                continue  # discrete aliases travel over gRPC, not the stream
            for ref in refs:
                cap = by_address.get(ref.address)
                if cap is None or getattr(cap, "kind", "") != "continuous":
                    raise ValueError(
                        f"{alias!r} -> {ref.address!r} is not a streamed continuous control "
                        f"on {wanted!r}. Check the namespace: vhi.prediction.* is the "
                        f"model-driven hand and vhi.control.pose.* is the operator's — a "
                        f"target drives one stream, not both."
                    )
                channel = getattr(cap, "channel", -1)
                if channel < 0:
                    raise ValueError(
                        f"{alias!r} -> {ref.address!r} is not carried on a stream "
                        f"(the target reports no channel for it). Command it with "
                        f"SetControl instead of routing it onto the outlet."
                    )
                if channel >= self._width:
                    raise ValueError(
                        f"{alias!r} -> {ref.address!r} is on channel {channel}, but this "
                        f"outlet carries {self._width}. Construct the outlet at least "
                        f"{channel + 1} channels wide."
                    )
                if channel in taken and taken[channel] != alias:
                    # Two of the user's outputs aiming at one control: whichever wrote
                    # last would win silently, and the other would look like a control
                    # that stopped working.
                    raise ValueError(
                        f"{taken[channel]!r} and {alias!r} both map to {ref.address!r}. "
                        f"One control cannot take two outputs — remove one, or fan a "
                        f"single output out to several controls instead."
                    )
                taken[channel] = alias
                sign = -1.0 if _encoding_of(cap) == _ENCODING_NEGATED else 1.0
                slots.append(
                    (channel, alias, float(ref.weight), sign, float(cap.lo), float(cap.hi))
                )

        self._dofs = controls.continuous
        self._routed = tuple(slots)
        self._order = tuple(reply.continuous_channel_order)
        self._negate = False  # per-capability sign lives in each slot
        self._negotiated = True
        log.info(
            "VHI routed %d alias-address pairs onto channels %s",
            len(slots),
            sorted({c for c, *_ in slots}),
        )
        return True

    def _negotiate_by_name(self, controls: ControlSet, pose: str) -> bool:
        """Declare a set whose DOF *names* are the renderer's addresses.

        The path a `ControlSet` built directly takes — a rig diagnostic, a test — where
        there is no mapping file and the names in play are already the renderer's own.
        """
        reply = self._client.declare(controls, client_name="myogestic", control_pose=pose)
        # "Answered" includes an explicit UNIMPLEMENTED: that server is reachable and
        # will never speak v2. Only silence leaves the question open.
        self._answered = reply is not None or getattr(self._client, "unimplemented", False)
        if reply is None:
            return False
        if not reply.accepted:
            refused = {v.name: v.message for v in reply.verdicts if not v.renderable}
            raise ValueError(
                f"this target declined part of the control space: {refused}. Rendering "
                f"only what it accepted would leave the rest looking like controls that "
                f"work and hold still."
            )
        # Each stream carries its own order and its own encoding. Reading the wrong pair
        # is how a frame ends up correct on one stream and inverted on another — the two
        # conventions coexist by design, so the target must know which stream it drives
        # rather than assume there is one answer.
        if self._stream == "control_pose":
            order = tuple(reply.control_pose_channel_order)
            encoding = getattr(reply, "control_pose_encoding", _ENCODING_UNSPECIFIED)
        else:
            order = tuple(reply.continuous_channel_order)
            encoding = getattr(reply, "continuous_encoding", _ENCODING_UNSPECIFIED)
        declared = controls.channel_labels()
        # The negotiated order is VHI's channel *map*, not a demand that the client
        # command every channel on it: a configuration may declare a subset and leave
        # the rest at rest. What must not happen is a declared DOF that has no channel —
        # that one would silently never render.
        missing = [name for name in declared if name not in order]
        if missing:
            raise ValueError(
                f"VHI accepted {missing} but its channel order {list(order)} has no "
                f"place for them. Rendering the rest would leave these looking like "
                f"controls that work and hold still."
            )
        if len(order) > self._width:
            raise ValueError(
                f"VHI negotiated {len(order)} channels but this outlet carries only "
                f"{self._width}. Construct the outlet at least that wide."
            )
        # How to encode the stream is not a detail to infer. A server that does not say
        # gets no benefit of the doubt: guessing wrong inverts every joint, which is
        # exactly how the first end-to-end v2 run made a hand extend when told to flex.
        if encoding not in (_ENCODING_CANONICAL, _ENCODING_NEGATED):
            raise ValueError(
                f"VHI negotiated channel names but did not say how to encode them "
                f"(encoding={encoding!r}). Refusing rather than guessing a sign "
                f"convention — guessing wrong inverts every joint."
            )
        self._dofs = controls.continuous
        self._order = order
        # Resolve each declared DOF to its negotiated channel once, here, rather than
        # looking names up per tick on the predict thread.
        self._slots = tuple((order.index(d.name), d) for d in controls.continuous)
        self._negate = encoding == _ENCODING_NEGATED
        self._negotiated = True
        log.info(
            "VHI negotiated %s (%s)",
            list(order),
            "negated wire" if self._negate else "canonical wire",
        )
        return True

    def _rebound(self) -> ControlSet | None:
        """The configuration currently bound, for a forced re-declaration."""
        from myogestic._controls_core import ControlSet

        dofs: dict = {d.name: d for d in self._dofs}
        if not dofs:
            return None
        return ControlSet(dofs=dofs)

    def send(self, values: Mapping[str, float | str], changed: Mapping[str, str]) -> None:
        """Encode one frame for the negotiated contract.

        Only the names `bind` accepted are read, and each falls back to its own
        declared rest, so neither a stray key nor a missing one can move a joint or
        raise on the predict thread.

        ``changed`` carries discrete edges, which go over gRPC: a keystroke-like state
        change is not a pose, and re-sending it every tick is not the same thing as
        re-sending a number.
        """
        self._outlet.push(self._frame(values))
        if not changed:
            return
        if self._negotiated:
            self._client.set_control(discrete=dict(changed))
        else:
            log.warning(
                "discrete edge %s dropped: VHI has not been reached yet, so its states "
                "are unresolved. Call VhiTarget.negotiate() once VHI is running.",
                dict(changed),
            )

    def _frame(self, values: Mapping[str, float | str]) -> np.ndarray:
        """The wire frame for this binding, in the negotiated order."""
        each = {d.name: float(values.get(d.name, d.rest)) for d in self._dofs}
        frame = np.zeros(self._width, dtype=np.float32)
        if self._routed:
            for channel, alias, weight, sign, lo, hi in self._routed:
                # Weight first, then the target's own range — a gain must not be able to
                # push a value past what the target said it accepts.
                value = weight * each.get(alias, 0.0)
                frame[channel] = sign * min(hi, max(lo, value))
            return frame
        # The negotiated order is a *prefix* of the transport, not its full width: the
        # outlet's channel count is fixed at construction and VHI will not name a channel
        # it does not read. The tail stays at zero rather than being dropped, because the
        # frame width is what the outlet validates against.
        sign = -1.0 if self._negate else 1.0
        for channel, dof in self._slots:
            frame[channel] = sign * each[dof.name]
        return frame

    def stop(self) -> None:
        """Return the hand to its declared rest pose, and make sure that lands."""
        if self._dofs:
            self._outlet.push(self._frame({d.name: d.rest for d in self._dofs}))
        self._outlet.flush()


__all__ = ["PoseSink", "VhiTarget"]
