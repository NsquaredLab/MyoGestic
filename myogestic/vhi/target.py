"""Render control values on a Virtual Hand.

`VhiTarget` is the `myogestic.controls.Target` for the VHI: it takes the sanitised frame
a `myogestic.controls.ControlBus` delivers and writes the pose the hand expects.

**The wire layout lives entirely behind this module.** An application declares its own
alias and maps it onto an address VHI publishes; this translates. Every fact about where
a value goes comes from VHI's own manifest, asked for at bind time — never from a table
in this file.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

# Imported at runtime, not just for typing: negotiation needs isinstance checks to tell a
# streamed continuous alias from a discrete one, and `TargetRef` to give a configuration
# that carries no routes the ones its DOF names imply.
from myogestic._controls_core import Continuous
from myogestic._controls_map import TargetRef

if TYPE_CHECKING:
    from collections.abc import Mapping

    from myogestic._controls_core import ControlSet
    from myogestic._controls_map import Capability

log = logging.getLogger("myogestic.vhi_target")

#: Channels on VHI's pose transport. A fallback only — the outlet is asked first, since
#: an application constructs it and may have made it wider.
_POSE_WIDTH = 9

#: Stream names to filter a manifest by when nothing else says. A fallback only — an
#: `InterfaceSpec` is asked first, since it is what actually names the outlet and a
#: configuration may have renamed either stream.
_DEFAULT_STREAM_NAMES = {
    "output": "MyoGestic_Output",
    "control_pose": "MyoGestic_ControlPose",
}


class PoseSink(Protocol):
    """The slice of `myogestic.outputs.Output` a `VhiTarget` uses.

    `myogestic.outputs.LSLOutlet` satisfies it, and so does a recorder or a test double.
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
    exports and refuses anything it cannot place. A pre-2.0 build is reported as
    unsupported rather than driven on a guess.

    Parameters
    ----------
    outlet
        Where pose frames go — normally ``virtual_hand().outlet()``. **User-owned**:
        construct it yourself and register its ``stop`` with ``app.cleanup_hooks``.
        Only `PoseSink.push` and `PoseSink.flush` are called on it.
    client
        A `myogestic.vhi._control.VhiControlClient` — ``virtual_hand().control_client()``.
        Required: the control space is negotiated over it, and it carries discrete
        state, which the pose transport cannot express.
    stream
        Which of the renderer's pose streams this target drives: ``"output"`` (the
        default — the predicted hand) or ``"control_pose"`` (the control hand). It
        decides which channel order the target reads out of the handshake; the two
        streams do not share one. The stream's *name* — what the manifest is filtered by
        — comes from ``interface`` when one was given (``output_stream_name`` or
        ``control_pose_stream_name``), so a renamed stream negotiates against the
        capabilities that report the new name rather than the default.

    Notes
    -----
    `bind` **refuses** a configuration it cannot render rather than rendering part of it:
    a silently-dropped control is indistinguishable from one holding still.

    Binding is **deferred** rather than decided when the renderer is silent, because an
    application that launches VHI from its own UI necessarily binds before VHI exists.
    Call `negotiate` once it is up. A renderer that *answers* and does not speak v2
    raises.

    On shutdown the declared rest frame is pushed *and flushed*: the send loop is paced,
    so a pushed-only frame would sit unsent while the process exits, leaving the hand at
    its last commanded pose.

    Examples
    --------
    >>> from myogestic.controls import ControlBus, load_control_map, resolve
    >>> from myogestic.vhi import VhiTarget, virtual_hand
    >>>
    >>> vhi = virtual_hand()
    >>> client = vhi.control_client()
    >>> control_map = load_control_map({"dofs": {"my_index": "vhi.prediction.index"}})
    >>> controls = resolve(control_map, client.capabilities())   # needs VHI running
    >>> bus = ControlBus(controls, targets=[VhiTarget(vhi.outlet(), client=client)])
    >>> _ = bus.push({"my_index": 0.8})        # sanitised on the way to the wire
    """

    __slots__ = (
        "_client", "_discrete", "_dofs", "_interface",
        "_negotiated", "_outlet", "_pending", "_routed", "_stream",
        "_width",
    )

    def __init__(
        self,
        outlet: PoseSink | None = None,
        *,
        client: Any = None,
        stream: str = "output",
        interface: Any = None,
    ) -> None:
        if stream not in ("output", "control_pose"):
            raise ValueError(
                f"stream must be 'output' or 'control_pose', got {stream!r}"
            )
        if outlet is None and interface is None:
            raise ValueError(
                "VhiTarget needs either an outlet to write to or an `interface=` to "
                "build one from. With an interface it builds a stream carrying exactly "
                "the controls this configuration drives, labelled with their addresses, "
                "which it can only do once `bind` has resolved them."
            )
        self._stream = stream
        #: Set at construction, or built at `bind` when only an `interface` was given.
        self._outlet = outlet
        #: The `InterfaceSpec` to build an outlet from, or None when one was supplied.
        #: Its presence selects a labelled, exactly-wide stream over the renderer's full
        #: positional pose layout.
        self._interface = interface if outlet is None else None
        self._client = client
        #: The configuration still awaiting a reachable VHI, or None once settled.
        self._pending: ControlSet | None = None
        self._dofs: tuple[Continuous, ...] = ()
        #: Names of the held states this target commands over gRPC once negotiated.
        self._discrete: tuple[str, ...] = ()
        #: Negotiated channel order: (channel, alias, weight, lo, hi, address). The
        #: address rides along as the channel's *label* on a self-describing stream —
        #: the alias cannot be, since a fan-out sends one alias to several channels.
        self._routed: tuple[tuple[int, str, float, float, float, str], ...] = ()
        #: Tracked explicitly: a configuration of
        #: only discrete DOFs negotiates fine and has an empty channel order.
        self._negotiated = False
        #: Frame width. Fixed by the supplied outlet, or decided at `bind` from how many
        #: controls were actually routed when this target builds its own.
        self._width = int(getattr(outlet, "n_channels", _POSE_WIDTH) or _POSE_WIDTH)

    @property
    def claims(self) -> frozenset[str]:
        """Which aliases this target actually drives.

        A bus with one target per hand shares a single control map, so no one target
        drives all of it. `ControlBus` reads this to check that every control was
        claimed by *someone*.
        """
        # Held states go over gRPC, so a negotiated target claims them whichever pose
        # stream it drives.
        return frozenset({alias for _, alias, *_ in self._routed} | set(self._discrete))

    @property
    def negotiated(self) -> bool:
        """Whether the contract has been settled with the renderer."""
        return self._negotiated

    def bind(self, controls: ControlSet) -> None:
        """Negotiate the control space with VHI, or defer until it is reachable.

        Raises
        ------
        ValueError
            When no client was given, or when the renderer answers and the
            configuration cannot be rendered — an address it does not export, one it
            does not carry on this stream, or two aliases aimed at one control. A
            renderer too old to answer `capabilities()` at all looks identical to one
            that is simply not up yet, so that case is deferred, never raised.
        """
        self._routed = ()
        self._discrete = ()
        self._pending = None
        self._negotiated = False
        if not controls.dofs:
            # Checked here rather than left to negotiation: resolving an empty
            # configuration against the manifest succeeds trivially, leaving a target
            # that is bound, negotiated, and renders nothing.
            raise ValueError(
                "VhiTarget has nothing to render: the configuration declares no DOFs "
                "at all."
            )
        if self._client is None:
            raise ValueError(
                "VhiTarget needs a control client: every channel, range and state "
                "comes from the renderer's manifest, so without one there is nothing "
                "to render against. Pass client=virtual_hand().control_client()."
            )
        if self._negotiate(controls):
            return
        # Silent — decide nothing, and let `negotiate` settle it. A renderer too old to
        # answer `capabilities()` at all looks identical to one that is simply not up
        # yet, so there is no signal left here to raise on rather than defer.
        self._pending = controls

    def negotiate(self, *, force: bool = False) -> bool:
        """Retry the handshake now — for an application that launches its own renderer.

        Cheap and idempotent when already settled, so it is fine to call from a button
        handler. Never call it from the predict thread — it blocks on an RPC.

        Parameters
        ----------
        force
            Re-run the handshake even if one already succeeded. Useful after the
            renderer restarts or its manifest changes — this target caches what it
            resolved and does not notice on its own. There is no automatic detection
            of that today.

        Returns
        -------
        bool
            Whether the contract is settled. ``False`` means VHI has not answered yet,
            so nothing is being rendered and this will keep retrying.

        Raises
        ------
        ValueError
            If the renderer answers and the configuration cannot be rendered. Call this
            from a setup path or a button handler where a traceback is visible, never
            from the predict thread.
        """
        if force and self._pending is None:
            # Re-arm from whatever is currently bound, so a caller does not have to
            # remember the ControlSet to re-negotiate it.
            rebuilt = self._rebound()
            if rebuilt is not None:
                self._pending = rebuilt
                self._negotiated = False
        controls = self._pending
        if controls is None:
            return self._negotiated
        if self._negotiate(controls):
            self._pending = None
            return True
        return False

    def _wanted_stream(self) -> str:
        """The LSL stream name this target's frames are published under.

        The manifest is filtered by it: a capability on another stream is another
        target's, and a channel index means nothing across streams.

        Taken from the interface when there is one, because that is what names the
        outlet — an `InterfaceSpec` that renamed a stream would otherwise publish to one
        name while negotiation filtered against another, and every capability would be
        dropped. Only the outlet-only construction path, where nothing says, falls back
        to the names `virtual_hand()` uses.
        """
        default = _DEFAULT_STREAM_NAMES[self._stream]
        attribute = (
            "control_pose_stream_name" if self._stream == "control_pose" else "output_stream_name"
        )
        # `control_pose_stream_name` is optional on an InterfaceSpec, so an interface
        # that has none is the fallback case too.
        return getattr(self._interface, attribute, None) or default

    def _negotiate(self, controls: ControlSet) -> bool:
        """Try the handshake. False means "no answer yet", never a refusal.

        Resolves alias -> address -> channel through the renderer's own manifest: the
        addresses come from the configuration, the channels and ranges from the
        renderer. A configuration that carries no routes is handed the ones its DOF
        names imply and travels this same path, so there is one resolution here rather
        than one per kind of `ControlSet`.
        """
        capabilities = self.capabilities()
        if capabilities is None:
            return False
        # Only this stream's controls. A renderer publishes several, and a channel index
        # means nothing across them — an address from the wrong stream would put a value
        # on a same-numbered channel of a different hand.
        wanted = self._wanted_stream()
        by_address = {
            cap.address: cap
            for cap in capabilities
            if not getattr(cap, "stream_name", "") or cap.stream_name == wanted
        }
        # What the *other* streams carry, so "not mine" can be told from "nobody's".
        # Skipping the first is how two targets share one map; refusing the second keeps
        # a typo an error instead of a control that renders nothing.
        elsewhere = {
            cap.address: cap.stream_name
            for cap in capabilities
            if getattr(cap, "stream_name", "") and cap.stream_name != wanted
        }
        routes, mine = self._scope(controls, wanted, by_address, elsewhere)
        if not mine:
            # Nothing in this file is ours. Not an error: `ControlBus` checks that
            # *someone* claims every alias, so an unrendered alias is still caught.
            log.info("VHI renders none of %d configured control(s)", len(controls.dofs))
            self._dofs = ()
            self._discrete = ()
            self._routed = ()
            self._negotiated = True
            return True
        slots: list[tuple[int, str, float, float, float, str]] = []
        taken: dict[int, str] = {}
        for alias, refs in routes.items():
            if alias not in controls.dofs or not isinstance(controls.dofs[alias], Continuous):
                continue  # discrete aliases travel over gRPC, not the stream
            for ref in refs:
                cap = by_address.get(ref.address)
                if cap is None and ref.address in elsewhere:
                    # Another stream's control, and the renderer says so. Not an error:
                    # a bus may hold one target per hand and share a single map between
                    # them, and `ControlBus` checks that *someone* claimed it.
                    log.debug(
                        "%r -> %r belongs to %s; leaving it to the target that drives it",
                        alias,
                        ref.address,
                        elsewhere[ref.address],
                    )
                    continue
                if cap is None or getattr(cap, "kind", "") != "continuous":
                    raise ValueError(
                        f"{alias!r} points at {ref.address!r}, which no target can drive "
                        f"as a number: the renderer does not export it on any pose stream. "
                        f"Check the address against what it does export — "
                        f"vhi.prediction.* is the model's hand and vhi.control.pose.* the "
                        f"operator's."
                    )
                channel = getattr(cap, "channel", -1)
                if channel < 0:
                    raise ValueError(
                        f"{alias!r} -> {ref.address!r} is not carried on a stream "
                        f"(the target reports no channel for it). Command it with "
                        f"SetControl instead of routing it onto the outlet."
                    )
                if self._interface is None and channel >= self._width:
                    raise ValueError(
                        f"{alias!r} -> {ref.address!r} is on channel {channel}, but this "
                        f"outlet carries {self._width}. Construct the outlet at least "
                        f"{channel + 1} channels wide, or pass `interface=` instead of an "
                        f"outlet and let this target size its own."
                    )
                if channel in taken and taken[channel] != alias:
                    # Two of the user's outputs aiming at one control: whichever wrote
                    # last would win silently.
                    raise ValueError(
                        f"{taken[channel]!r} and {alias!r} both map to {ref.address!r}. "
                        f"One control cannot take two outputs — remove one, or fan a "
                        f"single output out to several controls instead."
                    )
                taken[channel] = alias
                slots.append(
                    (
                        channel,
                        alias,
                        float(ref.weight),
                        float(cap.lo),
                        float(cap.hi),
                        ref.address,
                    )
                )

        # Filtered the same way `mine` was: `claims` has to report the truth, or
        # `ControlBus`'s every-alias-is-claimed check would see a foreign control as
        # covered.
        self._dofs = tuple(dof for dof in controls.continuous if dof.name in mine)
        self._discrete = tuple(dof.name for dof in controls.discrete if dof.name in mine)
        if self._interface is not None:
            # As wide as the renderer's pose layout, taken from the manifest — the same
            # table the renderer reads a channel back with. A zero-channel LSL outlet is
            # not a thing, so a configuration driving nothing continuous goes without one
            # and `send` skips the frame.
            self._build_outlet(
                max((cap.channel for cap in by_address.values()), default=-1) + 1
                if slots
                else 0
            )
        self._routed = tuple(slots)
        self._negotiated = True
        # Put the declared rest pose on the wire immediately: the hand should hold what
        # this configuration calls rest, and the renderer drops an inlet that has never
        # sent anything, re-resolving it in a loop until someone touches the UI.
        if self._outlet is not None and self._dofs:
            self._outlet.push(self._frame({d.name: d.rest for d in self._dofs}))
        log.info(
            "VHI routed %d alias-address pairs onto channels %s",
            len(slots),
            sorted({c for c, *_ in slots}),
        )
        return True

    def _scope(
        self,
        controls: ControlSet,
        wanted: str,
        by_address: Mapping[str, Capability],
        elsewhere: Mapping[str, str],
    ) -> tuple[Mapping[str, tuple[Any, ...]], set[str]]:
        """What to route onto channels, and which aliases are this target's.

        The one thing the two kinds of configuration disagree about — the resolution
        itself is shared.

        A **resolved** set carries routes and may be shared with a second target, so
        ownership goes by **namespace**, not exact address: a `vhi.*` address this build
        does not export is still refused by `_negotiate`, while a `keyboard.*` control
        sharing the file is in no VHI namespace and is simply not ours.

        A set built **directly** — a rig diagnostic, a test — carries no routes: its DOF
        names *are* the addresses, nothing upstream checked them, and there is no second
        target to leave anything to. So every name must be exported on this stream, and
        that has to be checked here: the tolerance above would read an unexported name
        as somebody else's rather than as the typo it is.
        """
        if controls.routes:
            namespaces = {
                address.split(".", 1)[0] for address in (*by_address, *elsewhere)
            }
            return controls.routes, {
                alias
                for alias, refs in controls.routes.items()
                if any(
                    getattr(ref, "address", "").split(".", 1)[0] in namespaces
                    for ref in refs
                )
            }
        # Address -> channel rather than a name tuple: an address's *position* in a
        # sorted list is not its channel unless every channel below it is on this stream
        # too, and nothing guarantees that. A name with no channel never renders, but the
        # map may name a subset and leave the rest of the hand at rest.
        streamed = {a: cap.channel for a, cap in by_address.items() if cap.channel >= 0}
        missing = [name for name in controls.channel_labels() if name not in streamed]
        if missing:
            order = sorted(streamed, key=streamed.__getitem__)
            raise ValueError(
                f"VHI's {wanted} channel order {order} has no place for "
                f"{missing}. Rendering the rest would leave these looking like "
                f"controls that work and hold still."
            )
        # Weight 1.0 and the name as its own address: exactly what `resolve` would have
        # produced had there been a map to resolve.
        return (
            {dof.name: (TargetRef(dof.name),) for dof in controls.continuous},
            set(controls.dofs),
        )

    def _rebound(self) -> ControlSet | None:
        """The configuration currently bound, for a forced re-negotiation."""
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

        ``changed`` carries discrete edges, which go over gRPC rather than onto the pose
        stream.
        """
        if self._outlet is not None:
            self._outlet.push(self._frame(values))
        if not changed:
            return
        # Only *our* edges. `changed` is the bus's, so on a shared map it also carries the
        # edges of every other target, and forwarding those makes VHI log a rejection per
        # keystroke.
        ours = {name: state for name, state in changed.items() if name in self._discrete}
        if not ours:
            return
        if self._negotiated:
            self._client.set_control(discrete=ours)
        else:
            log.warning(
                "discrete edge %s dropped: VHI has not been reached yet, so its states "
                "are unresolved. Call VhiTarget.negotiate() once VHI is running.",
                ours,
            )

    def _frame(self, values: Mapping[str, float | str]) -> np.ndarray:
        """The wire frame for this binding, in the negotiated order."""
        each = {d.name: float(values.get(d.name, d.rest)) for d in self._dofs}
        # The negotiated channels are a *subset* of the transport, not its full width:
        # the outlet's channel count is fixed at construction and VHI will not name a
        # channel it does not read. Everything unrouted stays at zero.
        frame = np.zeros(self._width, dtype=np.float32)
        for channel, alias, weight, lo, hi, _address in self._routed:
            # Weight first, then the target's own range — a gain must not be able to
            # push a value past what the target said it accepts.
            frame[channel] = min(hi, max(lo, weight * each.get(alias, 0.0)))
        return frame

    def _build_outlet(self, width: int) -> None:
        """Build this target's own stream, `width` channels of the renderer's pose layout.

        The alternative to being handed one. It carries the renderer's channels at the
        renderer's own indices — there is no compaction and nothing to label, because a
        channel *is* an address: the manifest says `vhi.prediction.index` is channel 2, and
        both ends read that from the same table. A narrower frame would only mean the
        receiver had to be told how to put it back.
        """
        if width == 0:
            self._outlet = None
            self._width = 0
            log.info("VhiTarget has no continuous control on %s; no stream", self._stream)
            return
        build = (
            self._interface.control_outlet
            if self._stream == "control_pose"
            else self._interface.outlet
        )
        # Replace rather than mutate: LSL fixes a stream's description at construction. Any
        # outlet from an earlier bind is dropped here — `bind` is a main-thread call and
        # nothing is streaming yet.
        self._outlet = build(n_channels=width)
        self._width = width

    def capabilities(self) -> tuple[Capability, ...] | None:
        """What the renderer exports, or `None` while it cannot be reached.

        The same question `KeyboardTarget.capabilities` answers off a local list, so a
        caller can ask a mixed set of targets what they render without knowing which of
        them needs a live connection. `None` is the honest answer for a renderer that has
        not started: not an empty manifest, which would read as "renders nothing".
        """
        fetch = getattr(self._client, "capabilities", None)
        got = fetch() if callable(fetch) else None
        return None if got is None else tuple(got)

    def stop(self) -> None:
        """Return the hand to its declared rest pose, and make sure that lands.

        An outlet this target *built* is also stopped, because nothing else can: a
        caller-supplied one is left alone, since the application owns it and may still
        be using it.
        """
        if self._outlet is None:
            return
        if self._dofs:
            self._outlet.push(self._frame({d.name: d.rest for d in self._dofs}))
        self._outlet.flush()
        if self._interface is not None:
            stop = getattr(self._outlet, "stop", None)
            if callable(stop):
                stop()


__all__ = ["PoseSink", "VhiTarget"]
