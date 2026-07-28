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

# Imported at runtime, not just for typing: the routed path needs isinstance checks to
# tell a streamed continuous alias from a discrete one. _controls_core has no dependency
# back on this module, so this cannot re-create the import cycle the core/bus split fixed.
from myogestic._controls_core import Continuous
from myogestic.vhi.legacy import (
    LEGACY_ADDRESS_CHANNELS,
    LEGACY_POSE_DOFS,
    LEGACY_POSE_WIDTH,
    encode_pose,
)


def _encoding_of(capability: Any) -> int:
    """A capability's declared wire encoding, defaulting to canonical."""
    return int(getattr(capability, "encoding", _ENCODING_CANONICAL) or _ENCODING_CANONICAL)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from myogestic._controls_core import ControlSet

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
    stream
        Which of the renderer's pose streams this target drives: ``"output"`` (the
        default — the predicted hand) or ``"control_pose"`` (the control hand). It
        decides which channel order *and which encoding* the target reads out of the
        handshake. The two streams do not share a convention, so a target that guessed
        would be right on one and inverted on the other.
    client
        Optional `myogestic.vhi._client_v2.VhiCanonicalClient`. When given, `bind`
        negotiates the control space over it; without one this target is legacy-only.
        Also carries discrete state, which the legacy *wire* cannot express at all.
    legacy_client
        Optional `myogestic.vhi._client.VhiControlClient`, used **only** on the legacy
        path and only for discrete DOFs — the pre-v2 way to render a held state was
        v1's ``SetMovement``. Supplying one lets an application declare a discrete DOF
        and still run against an unmodified VHI; without one the legacy path refuses
        discrete DOFs outright, because a silently dropped state is worse than a
        refusal. This parameter exists to be deleted with v1.

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

    __slots__ = (
        "_answered", "_client", "_dofs", "_legacy", "_legacy_states", "_negate",
        "_negotiated", "_order", "_outlet", "_pending", "_routed", "_slots", "_stream",
        "_width",
    )

    def __init__(
        self,
        outlet: PoseSink,
        *,
        client: Any = None,
        legacy_client: Any = None,
        stream: str = "output",
    ) -> None:
        if stream not in ("output", "control_pose"):
            raise ValueError(
                f"stream must be 'output' or 'control_pose', got {stream!r}"
            )
        self._stream = stream
        self._outlet = outlet
        self._client = client
        self._legacy = legacy_client
        #: Canonical discrete state -> the v1 movement name that renders it. Only
        #: populated on the legacy path; empty once v2 is negotiated.
        self._legacy_states: dict[str, str] = {}
        #: The configuration still awaiting a reachable VHI, or None once settled.
        self._pending: ControlSet | None = None
        #: Whether VHI has ever *answered* the handshake. "It refused" and "it never
        #: replied" need opposite handling, and both make `_negotiate` return False.
        self._answered = False
        self._dofs: tuple[Continuous, ...] = ()
        #: Negotiated channel order in v2 mode; empty means the legacy path.
        self._order: tuple[str, ...] = ()
        #: Whether the negotiated wire wants canonical values negated.
        self._negate = False
        #: Declared DOFs paired with the channel VHI put them on.
        self._slots: tuple[tuple[int, Continuous], ...] = ()
        #: Address-routed slots: (channel, alias, weight, sign, lo, hi). Non-empty only
        #: when the configuration was resolved against a target manifest, which is what
        #: distinguishes an alias-mapped set from a name-declared one.
        self._routed: tuple[tuple[int, str, float, float, float, float], ...] = ()
        #: Tracked explicitly rather than inferred from `_order`: a configuration of
        #: only discrete DOFs negotiates fine and has an empty channel order, and
        #: inferring from the order would leave it believing it was on the legacy path
        #: — where it would render nothing at all.
        self._negotiated = False
        self._width = LEGACY_POSE_WIDTH

    @property
    def negotiated(self) -> bool:
        """Whether `bind` settled on the v2 contract rather than the legacy pose."""
        return self._negotiated

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
        self._slots = ()
        self._routed = ()
        self._legacy_states = {}
        self._pending = None
        self._negate = False
        self._negotiated = False
        self._answered = False
        if self._client is not None and self._negotiate(controls):
            return
        if self._client is not None and not self._answered:
            # VHI has said nothing. "An older build" and "not started yet" are
            # indistinguishable, and an app that launches VHI from its own UI binds
            # before VHI exists — so decide nothing here. Committing now would pick a
            # sign convention that a v2 build then contradicts, and applying the legacy
            # refusals now would reject a configuration a v2 build could render.
            self._pending = controls
            try:
                self._bind_legacy(controls)
            except ValueError as exc:
                log.info(
                    "the legacy path cannot render this configuration (%s) — waiting for "
                    "a v2 handshake instead. Call VhiTarget.negotiate() once VHI is up.",
                    exc,
                )
            return
        # VHI answered and refused, or there is no client at all. Either way the legacy
        # path is the answer and its refusals are authoritative.
        self._bind_legacy(controls)

    def negotiate(self, *, force: bool = False) -> bool:
        """Retry the handshake now — for an application that launches its own renderer.

        `bind` runs when the `myogestic.controls.ControlBus` is constructed, which for
        an app that spawns VHI from its own UI is necessarily *before* VHI exists. That
        makes "no answer" ambiguous at bind time: an older build and a build that is
        not up yet look identical. `bind` therefore defers rather than deciding, and
        this settles it once the renderer is actually there.

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
            Whether the contract is **settled**. ``False`` means VHI has not answered
            yet, so this will keep retrying and may still end up on v2 — it does *not*
            mean nothing renders: a legacy-encoded frame is still sent meanwhile, and
            will be correct if the renderer turns out to be a pre-v2 build.

        Raises
        ------
        ValueError
            If the renderer answers and the configuration cannot be rendered on the
            path that answer selects — for instance a discrete state matching none of
            the movements VHI reports. That is a configuration error rather than a
            transient one, so it is raised rather than swallowed; call this from a
            setup path or a button handler where a traceback is visible, never from
            the predict thread.
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
            return self._negotiated or bool(self._dofs) or bool(self._legacy_states)
        if self._client is not None and self._negotiate(controls):
            self._pending = None
            return True
        if self._answered:
            # VHI answered and would not negotiate: it is a pre-v2 build, so settle on
            # the legacy path and stop asking.
            self._pending = None
            self._bind_legacy(controls)
            return True
        # Still silent. Make the legacy path usable if it can be, but stay pending: a
        # renderer that appears later must still get a handshake, or a configuration
        # bound before VHI started would keep a convention that build contradicts.
        if controls.discrete and not self._legacy_states:
            self._legacy_states = self._resolve_legacy_states(controls)
        if self._client is None and (self._dofs or self._legacy_states):
            # Nothing left to ask — the legacy path is the only path, and it works.
            self._pending = None
            return True
        # Still waiting on an answer. Report unsettled so a caller knows to keep asking
        # (and can tell "VHI is not up" apart from "VHI is pre-v2"), even though the
        # legacy path is already encoding frames in the meantime.
        return False

    def _negotiate_routed(self, controls: ControlSet, routes: Mapping, pose: str) -> bool:
        """Resolve alias -> address -> channel through the target's own manifest.

        The addresses come from the configuration, the channels and ranges come from the
        target. Nothing here decides where a control lives; it asks, and refuses rather
        than guessing when the answer does not cover what was configured.
        """
        fetch = getattr(self._client, "capabilities", None)
        capabilities = fetch() if callable(fetch) else None
        self._answered = capabilities is not None or getattr(
            self._client, "unimplemented", False
        )
        if capabilities is None:
            return False
        by_address = {cap.address: cap for cap in capabilities}

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
                        f"{alias!r} -> {ref.address!r} is not a streamed continuous "
                        f"control on this target, so it has no channel to occupy."
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
                sign = -1.0 if _encoding_of(cap) == _ENCODING_LEGACY_NEGATED else 1.0
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

    def _rebound(self) -> ControlSet | None:
        """The configuration currently bound, for a forced re-declaration."""
        from myogestic._controls_core import ControlSet

        dofs: dict = {d.name: d for d in self._dofs}
        if not dofs:
            return None
        return ControlSet(dofs=dofs)

    def _negotiate(self, controls: ControlSet) -> bool:
        """Try the v2 handshake. False means "use the legacy path", never an error."""
        pose = "canonical" if self._stream == "control_pose" else ""
        routes = getattr(controls, "routes", None) or {}
        if routes and not self._negotiate_routed(controls, routes, pose):
            return False
        if routes:
            return True
        reply = self._client.declare(controls, client_name="myogestic", control_pose=pose)
        # "Answered" includes an explicit UNIMPLEMENTED: that server is reachable and
        # will never speak v2, so the legacy path is settled rather than provisional.
        # Only silence leaves the question open.
        self._answered = reply is not None or getattr(self._client, "unimplemented", False)
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
        # Each stream carries its own order and its own encoding. Reading the wrong
        # pair is how a frame ends up correct on one stream and inverted on another —
        # the two conventions coexist by design, so the target must know which stream
        # it drives rather than assume there is one answer.
        if self._stream == "control_pose":
            order = tuple(reply.control_pose_channel_order)
            encoding = getattr(reply, "control_pose_encoding", _ENCODING_UNSPECIFIED)
        else:
            order = tuple(reply.continuous_channel_order)
            encoding = getattr(reply, "continuous_encoding", _ENCODING_UNSPECIFIED)
        declared = controls.channel_labels()
        # The negotiated order is VHI's channel *map*, not a demand that the client
        # command every channel on it: a configuration may declare a subset and leave
        # the rest at rest, exactly as the legacy path allows. What must not happen is
        # a declared DOF that has no channel — that one would silently never render.
        missing = [name for name in declared if name not in order]
        if missing:
            log.warning(
                "VHI accepted %s but its channel order %s has no place for them — "
                "falling back to the legacy pose rather than guessing the mapping.",
                missing,
                list(order),
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
        # Resolve each declared DOF to its negotiated channel once, here, rather than
        # looking names up per tick on the predict thread.
        self._slots = tuple((order.index(d.name), d) for d in controls.continuous)
        self._negate = encoding == _ENCODING_LEGACY_NEGATED
        self._negotiated = True
        log.info(
            "VHI negotiated the canonical contract: %s (%s)",
            list(order),
            "legacy-negated wire" if self._negate else "canonical wire",
        )
        return True

    def _bind_legacy(self, controls: ControlSet) -> None:
        """The pre-v2 path: a six-DOF pose on a nine-channel wire, or a refusal."""
        routes = getattr(controls, "routes", None) or {}
        if routes:
            self._bind_legacy_routed(controls, routes)
            return
        if controls.discrete:
            self._legacy_states = self._resolve_legacy_states(controls)
            if not self._legacy_states:
                # VHI is not up yet. Not a configuration error — this application
                # launches its own renderer, so bind runs first by construction.
                # Resolution is retried by `negotiate`.
                self._pending = controls
        pose = controls.continuous
        if not pose and not controls.discrete:
            raise ValueError(
                "VhiTarget has nothing to render: the configuration declares no DOFs "
                "at all."
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

    def _bind_legacy_routed(self, controls: ControlSet, routes: Mapping) -> None:
        """An address-mapped configuration, driving an unmodified pre-v2 build.

        A pre-v2 VHI cannot be asked what it exports, so the address-to-channel map is
        stated once in `myogestic.vhi.legacy` rather than discovered. That keeps a
        configuration written against v2 addresses working against the old binary — which
        is the whole point of the compatibility path — and it dies with v1.
        """
        slots: list[tuple[int, str, float, float, float, float]] = []
        unknown: list[str] = []
        taken: dict[int, str] = {}
        for alias, refs in routes.items():
            dof = controls.dofs.get(alias)
            if not isinstance(dof, Continuous):
                continue
            for ref in refs:
                channel = LEGACY_ADDRESS_CHANNELS.get(ref.address)
                if channel is None:
                    unknown.append(ref.address)
                    continue
                if channel in taken and taken[channel] != alias:
                    raise ValueError(
                        f"{taken[channel]!r} and {alias!r} both map to {ref.address!r}. "
                        f"One control cannot take two outputs — remove one, or fan a "
                        f"single output out to several controls instead."
                    )
                taken[channel] = alias
                # Legacy units: flexion is negative there, so a canonical value negates.
                slots.append((channel, alias, float(ref.weight), -1.0, -1.0, 1.0))
        if unknown:
            raise ValueError(
                f"VhiTarget has no legacy channel for {sorted(set(unknown))}. An "
                f"unmodified VHI renders only "
                f"{sorted(set(LEGACY_ADDRESS_CHANNELS))} — and dropping them silently "
                f"would render as a joint that is working and holding still."
            )
        if controls.discrete:
            self._legacy_states = self._resolve_legacy_states(controls)
        self._dofs = controls.continuous
        self._routed = tuple(slots)

    def _resolve_legacy_states(self, controls: ControlSet) -> dict[str, str]:
        """Map each declared discrete state onto a v1 movement name, or refuse.

        The pre-v2 renderer for a held state is v1's ``SetMovement``, which matches
        movement names exactly — so the states are resolved case-insensitively against
        what VHI reports it has, the same way the v2 service does it server-side.
        Resolution happens once, at bind, so a click never pays for a query.
        """
        names = [d.name for d in controls.discrete]
        if self._legacy is None and self._client is not None and not self._answered:
            # A v2-only target whose renderer is not up yet. Refusing here would fail a
            # perfectly renderable configuration at construction; v2 handles discrete
            # DOFs natively, so wait for the handshake instead.
            return {}
        if self._legacy is None:
            raise ValueError(
                f"VhiTarget cannot render discrete DOFs {names} on the legacy path: the "
                f"old wire carries a pose and nothing else. Pass legacy_client="
                f"virtual_hand().control_client() to render them through v1 SetMovement, "
                f"or client=virtual_hand().canonical_client() to negotiate v2."
            )
        state = self._legacy.get_state()
        available = list(state.available_movements) if state is not None else []
        if not available:
            # Absent, not wrong. Signalled by an empty result so `bind` can defer.
            return {}
        lookup = {movement.lower(): movement for movement in available}
        resolved: dict[str, str] = {}
        unresolved: list[str] = []
        for dof in controls.discrete:
            for value in dof.states:
                movement = lookup.get(value.lower())
                if movement is None:
                    unresolved.append(value)
                else:
                    resolved[value] = movement
        if unresolved:
            raise ValueError(
                f"VhiTarget has no movement for the states {sorted(set(unresolved))}. This "
                f"VHI offers {available}. Rename the states, or drop them — rendering only "
                f"the ones that resolve would make the rest look like a state that applied."
            )
        return resolved

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
        if not changed:
            return
        if self.negotiated and self._client is not None:
            self._client.set_control(discrete=dict(changed))
        elif self._legacy_states:
            # The legacy path renders a held state through v1 SetMovement, one edge at
            # a time. cycle=False: a discrete DOF is a held state, so it snaps to the
            # pose and stays — cycling would render a trajectory nobody asked for.
            for state in changed.values():
                movement = self._legacy_states.get(state)
                if movement is not None:
                    self._legacy.set_movement(movement, cycle=False)
        elif self._pending is not None:
            log.warning(
                "discrete edge %s dropped: VHI has not been reached yet, so its states "
                "are unresolved. Call VhiTarget.negotiate() once VHI is running.",
                dict(changed),
            )

    def _frame(self, values: Mapping[str, float | str]) -> np.ndarray:
        """The wire frame for this binding — negotiated order, or the legacy pose."""
        each = {d.name: float(values.get(d.name, d.rest)) for d in self._dofs}
        if self._routed:
            frame = np.zeros(self._width, dtype=np.float32)
            for channel, alias, weight, sign, lo, hi in self._routed:
                # Weight first, then the target's own range — a gain must not be able to
                # push a value past what the target said it accepts.
                value = weight * each.get(alias, 0.0)
                frame[channel] = sign * min(hi, max(lo, value))
            return frame
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
        for channel, dof in self._slots:
            frame[channel] = sign * each[dof.name]
        return frame

    def stop(self) -> None:
        """Return the hand to its declared rest pose, and make sure that lands."""
        if self._dofs:
            self._outlet.push(self._frame({d.name: d.rest for d in self._dofs}))
        self._outlet.flush()


__all__ = ["PoseSink", "VhiTarget"]
