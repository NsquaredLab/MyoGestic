"""Render control values on a Virtual Hand.

`VhiTarget` is the `myogestic.controls.Target` for the VHI: it takes the sanitised frame
a `myogestic.controls.ControlBus` delivers and writes the pose the hand expects.

**The wire layout lives entirely behind this module.** An application declares its own
alias and maps it onto an address VHI publishes; this translates. Every fact about where
a value goes comes from VHI's own manifest, asked for at bind time — never from a table
in this file.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

# Imported at runtime, not just for typing: the routed path needs isinstance checks to
# tell a streamed continuous alias from a discrete one.
from myogestic._controls_core import Continuous

if TYPE_CHECKING:
    from collections.abc import Mapping

    from myogestic._controls_core import ControlSet

log = logging.getLogger("myogestic.vhi_target")

#: Channels on VHI's pose transport. A fallback only — the outlet is asked first, since
#: an application constructs it and may have made it wider.
_POSE_WIDTH = 9


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
        streams do not share one.

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
        "_answered", "_client", "_discrete", "_dofs", "_interface",
        "_negotiated", "_order", "_outlet", "_pending", "_routed", "_slots", "_stream",
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
        #: Whether VHI has ever *answered* the handshake — a refusal is settled, silence
        #: is not.
        self._answered = False
        self._dofs: tuple[Continuous, ...] = ()
        #: Names of the held states this target commands over gRPC once negotiated.
        self._discrete: tuple[str, ...] = ()
        #: Negotiated channel order.
        self._order: tuple[str, ...] = ()
        #: Declared DOFs paired with the channel VHI put them on, for a name-declared
        #: configuration.
        self._slots: tuple[tuple[int, Continuous], ...] = ()
        #: Address-routed slots: (channel, alias, weight, lo, hi, address). The
        #: address rides along as the channel's *label* on a self-describing stream —
        #: the alias cannot be, since a fan-out sends one alias to several channels.
        #: Non-empty when the configuration was resolved against a manifest.
        self._routed: tuple[tuple[int, str, float, float, float, str], ...] = ()
        #: Tracked explicitly rather than inferred from `_order`: a configuration of
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
        routed = {alias for _, alias, *_ in self._routed}
        by_name = {dof.name for _, dof in self._slots}
        # Held states go over gRPC, so a negotiated target claims them whichever pose
        # stream it drives.
        return frozenset(routed | by_name | set(self._discrete))

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
        self._discrete = ()
        self._pending = None
        self._negotiated = False
        self._answered = False
        if not controls.dofs:
            # Checked here rather than left to the handshake: a renderer accepts an empty
            # declaration happily, leaving a target that is bound, negotiated, and
            # renders nothing.
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
        if self._answered:
            raise ValueError(
                "this Virtual Hand does not serve the v2 control contract, so its "
                "controls cannot be discovered. MyoGestic 2.x requires VHI 2.0 or "
                "newer — upgrade the renderer (python -m myogestic.tools.install_vhi), "
                "or run one from source with $VHI_PATH and $GODOT_BIN."
            )
        # Silent — decide nothing, and let `negotiate` settle it.
        self._pending = controls

    def negotiate(self, *, force: bool = False) -> bool:
        """Retry the handshake now — for an application that launches its own renderer.

        Cheap and idempotent when already settled, so it is fine to call from a button
        handler. Never call it from the predict thread — it blocks on an RPC.

        Parameters
        ----------
        force
            Re-run the handshake even if one already succeeded. Needed after the
            renderer restarts: VHI's side of the contract is *stateful* (declaring a
            control-pose stream also puts its control hand into Stream mode), and a
            restart loses that while this target still believes it is negotiated. There
            is no automatic detection of that today.

        Returns
        -------
        bool
            Whether the contract is settled. ``False`` means VHI has not answered yet,
            so nothing is being rendered and this will keep retrying.

        Raises
        ------
        ValueError
            If the renderer answers and does not speak v2, or answers and the
            configuration cannot be rendered. Call this from a setup path or a button
            handler where a traceback is visible, never from the predict thread.
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
        pose = self._stream == "control_pose"
        routes = getattr(controls, "routes", None) or {}
        if routes:
            return self._negotiate_routed(controls, routes, pose)
        return self._negotiate_by_name(controls, pose)

    def _negotiate_routed(self, controls: ControlSet, routes: Mapping, pose: bool) -> bool:
        """Resolve alias -> address -> channel through the renderer's own manifest.

        The addresses come from the configuration; the channels and ranges come from the
        renderer.
        """
        fetch = getattr(self._client, "capabilities", None)
        capabilities = fetch() if callable(fetch) else None
        self._answered = capabilities is not None or getattr(
            self._client, "unimplemented", False
        )
        if capabilities is None:
            return False
        # Only this stream's controls. A renderer publishes several, and a channel index
        # means nothing across them — an address from the wrong stream would put a value
        # on a same-numbered channel of a different hand.
        wanted = (
            "MyoGestic_ControlPose" if self._stream == "control_pose" else "MyoGestic_Output"
        )
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

        # Which of these aliases are *this* target's, decided before anything is declared:
        # `Declare` is all-or-nothing, so a `keyboard.*` control sharing the file would
        # take the VHI controls down with it. Matched by **namespace**, not exact address
        # — a `vhi.*` address this build does not export is still refused below.
        namespaces = {
            address.split(".", 1)[0] for address in (*by_address, *elsewhere)
        }
        mine = {
            alias
            for alias, refs in routes.items()
            if any(
                getattr(ref, "address", "").split(".", 1)[0] in namespaces for ref in refs
            )
        }
        if not mine:
            # Nothing in this file is ours. Not an error: `ControlBus` checks that
            # *someone* claims every alias, so an unrendered alias is still caught.
            log.info("VHI renders none of %d configured control(s)", len(controls.dofs))
            self._dofs = ()
            self._discrete = ()
            self._routed = ()
            self._negotiated = True
            return True
        declaring = (
            controls
            if len(mine) == len(controls.dofs)
            else dataclasses.replace(
                controls,
                dofs={a: d for a, d in controls.dofs.items() if a in mine},
                routes={a: r for a, r in routes.items() if a in mine},
            )
        )
        reply = self._client.declare(declaring, client_name="myogestic", control_pose=pose)
        if reply is None:
            return False
        if not reply.accepted:
            refused = {v.name: v.message for v in reply.verdicts if not v.renderable}
            raise ValueError(
                f"this target declined part of the control space: {refused}. Rendering "
                f"only what it accepted would leave the rest looking like controls that "
                f"work and hold still."
            )

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
                # Only when the caller supplied the outlet. A target building its own
                # renumbers the channels into a compact frame below, so the renderer's
                # index is a routing key here rather than a wire position.
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

        # Filtered the same way the declaration was: `claims` has to report the truth, or
        # `ControlBus`'s every-alias-is-claimed check would see a foreign control as
        # covered.
        self._dofs = tuple(dof for dof in controls.continuous if dof.name in mine)
        self._discrete = tuple(dof.name for dof in controls.discrete if dof.name in mine)
        self._routed = self._own_the_wire(slots) if self._interface else tuple(slots)
        self._order = tuple(reply.continuous_channel_order)
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

    def _negotiate_by_name(self, controls: ControlSet, pose: bool) -> bool:
        """Declare a set whose DOF *names* are the renderer's addresses.

        The path a directly-built `ControlSet` takes — a rig diagnostic, a test — where
        there is no mapping file.
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
        # Each stream carries its own order; reading the wrong one leaves a frame
        # correct on one stream and empty on the other.
        if self._stream == "control_pose":
            order = tuple(reply.control_pose_channel_order)
        else:
            order = tuple(reply.continuous_channel_order)
        declared = controls.channel_labels()
        # The negotiated order is VHI's channel *map*, not a demand that the client
        # command every channel on it: a configuration may declare a subset and leave
        # the rest at rest. A declared DOF with no channel would silently never render.
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
        self._dofs = controls.continuous
        self._discrete = tuple(dof.name for dof in controls.discrete)
        self._order = order
        # Resolve each declared DOF to its negotiated channel once, here, rather than
        # looking names up per tick on the predict thread.
        self._slots = tuple((order.index(d.name), d) for d in controls.continuous)
        self._negotiated = True
        log.info("VHI negotiated %s", list(order))
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
        frame = np.zeros(self._width, dtype=np.float32)
        if self._routed:
            for channel, alias, weight, lo, hi, _address in self._routed:
                # Weight first, then the target's own range — a gain must not be able to
                # push a value past what the target said it accepts.
                value = weight * each.get(alias, 0.0)
                frame[channel] = min(hi, max(lo, value))
            return frame
        # The negotiated order is a *prefix* of the transport, not its full width: the
        # outlet's channel count is fixed at construction and VHI will not name a channel
        # it does not read. The tail stays at zero because the frame width is what the
        # outlet validates against.
        for channel, dof in self._slots:
            frame[channel] = each[dof.name]
        return frame

    def _own_the_wire(
        self, slots: list[tuple[int, str, float, float, float, str]]
    ) -> tuple[tuple[int, str, float, float, float, str], ...]:
        """Build a stream carrying exactly these controls, labelled with their addresses.

        The renderer's channel index is an index into *its* full pose layout — nine wide,
        all nine rendered (channels 6-8 are the wrist). The channels are renumbered into
        a compact frame and each one labelled with the address it carries, so a consumer
        maps by name rather than by position. A consumer that ignores labels cannot
        interpret the stream, which is why the caller opts in by passing `interface=`
        instead of an outlet.

        Sorted by the renderer's own index so the layout is stable across runs.
        """
        ordered = sorted(slots, key=lambda slot: slot[0])
        addresses = [slot[5] for slot in ordered]
        renumbered = tuple(
            (index, alias, weight, lo, hi, address)
            for index, (_, alias, weight, lo, hi, address) in enumerate(ordered)
        )
        if not addresses:
            # Every alias belonged to another stream, or the configuration is discrete
            # only. A zero-channel LSL outlet is not a thing, so this target goes without
            # one and `send` skips the frame.
            self._outlet = None
            self._width = 0
            log.info("VhiTarget has no continuous control on %s; no stream", self._stream)
            return renumbered
        build = (
            self._interface.control_outlet
            if self._stream == "control_pose"
            else self._interface.outlet
        )
        # Replace rather than mutate: LSL fixes a stream's description at construction, so
        # labelling means a new outlet. Any outlet from an earlier bind is dropped here —
        # `bind` is a main-thread call and nothing is streaming yet.
        self._outlet = build(n_channels=len(addresses), channel_names=addresses)
        self._width = len(addresses)
        log.info(
            "VhiTarget built a %d-channel labelled %s stream: %s",
            self._width,
            self._stream,
            addresses,
        )
        return renumbered

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
