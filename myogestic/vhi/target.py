"""Render control values on a Virtual Hand.

`VhiTarget` is the `myogestic.controls.Target` for the VHI: it takes the sanitised frame
a `myogestic.controls.ControlBus` delivers and writes the values the hand expects.

**The wire layout lives entirely behind this module.** An application declares its own
alias and maps it onto an address VHI publishes; this translates. Every fact about where
a value goes comes from VHI's own manifest, asked for at bind time — never from a table
in this file.

**One stream per DOF.** A control's LSL stream is named for the control's own address and
is one channel wide, so a target that drives nine controls owns nine outlets. There is no
shared frame and no positional layout for the two sides to agree on: a sample applies the
moment it arrives, and the controls that did not deliver hold what they were last
commanded to. That is what the DOFs actually are — independently actuated, possibly from
different producers, possibly at different rates.
"""

from __future__ import annotations

import logging
from contextlib import suppress
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


class PoseSink(Protocol):
    """Where one control's values go — the slice of `myogestic.outputs.Output` used here.

    `myogestic.outputs.LSLOutlet` satisfies it, and so does a recorder or a test double.

    One of these carries **one control**, so a `VhiTarget` holds one per address it
    drives. They are not supplied directly: the target builds them, one per address, by
    calling ``interface.stream_outlet(address, n_channels=1)`` once negotiation has said
    which addresses those are. Substituting a recorder or a double therefore means
    supplying an ``interface=`` whose ``stream_outlet`` returns one of these — the same
    seam, moved up one level so that it can be called once per address.
    """

    def push(self, data: np.ndarray) -> None:
        """Queue a one-channel sample for sending."""
        ...

    def flush(self) -> None:
        """Send the queued sample now rather than on the next tick."""
        ...

    def stop(self) -> None:
        """Take this stream off the network and release it."""
        ...


def _sample(value: float) -> np.ndarray:
    """One control's value, as the one-channel frame its own stream carries."""
    return np.array([value], dtype=np.float32)


def _retire(outlet: PoseSink, rest: float) -> None:
    """Rest a stream, make sure that lands, and take it off the network.

    Every path that gives up on an outlet comes through here. Dropping the reference is
    not enough and is not a smaller version of this: liblsl keeps a stream discoverable
    for as long as its `StreamOutlet` object is alive, so an abandoned outlet stays
    resolvable — sharing its ``source_id`` with whatever replaced it, which is how a
    consumer ends up resolving the dead one. See `myogestic.outputs.LSLOutlet.stop`.

    The rest value is pushed *and flushed* before the stop, for the same reason shutdown
    does: the send loop is paced, so a pushed-only sample would sit unsent while the
    outlet went away, leaving the hand at the last value anybody commanded.

    ``finally``, because an outlet that cannot be rested is exactly the one that must
    still be released — a dead LSL outlet is still a discoverable stream.
    """
    try:
        outlet.push(_sample(rest))
        outlet.flush()
    finally:
        outlet.stop()


class VhiTarget:
    """Drive a Virtual Hand from control values.

    Requires a VHI that speaks the v2 control contract: it *asks* the renderer what it
    exports and refuses anything it cannot place. A build older than the vocabulary this
    client needs is refused by version at bind, not driven on a guess — see
    `myogestic.vhi._control.VhiControlClient.capabilities`.

    One target drives a whole control map. It owns **one LSL outlet per address** it
    drives, each named for that address and one channel wide, all built after negotiation
    has resolved which addresses those are.

    Parameters
    ----------
    client
        A `myogestic.vhi._control.VhiControlClient` — ``virtual_hand().control_client()``.
        Required: the control space is negotiated over it, and it carries discrete
        state, which the pose streams cannot express.
    interface
        The `~myogestic.vhi.interfaces.InterfaceSpec` to build streams from —
        ``virtual_hand()``. The target calls ``stream_outlet(address, n_channels=1)`` on
        it once per address it drives, so the application never states a stream name or a
        width. Anything with that method serves: a recorder or a test double substitutes
        here.

    Notes
    -----
    `bind` **refuses** a configuration it cannot render rather than rendering part of it:
    a silently-dropped control is indistinguishable from one holding still.

    Binding is **deferred** rather than decided when the renderer is silent, because an
    application that launches VHI from its own UI necessarily binds before VHI exists.
    Call `negotiate` once it is up. A renderer that *answers* and does not speak the
    current vocabulary raises.

    On shutdown every stream's declared rest is pushed *and flushed*: the send loop is
    paced, so a pushed-only value would sit unsent while the process exits, leaving the
    hand at its last commanded pose.

    Examples
    --------
    >>> from myogestic.controls import ControlBus, load_control_map, resolve
    >>> from myogestic.vhi import VhiTarget, virtual_hand
    >>>
    >>> vhi = virtual_hand()
    >>> client = vhi.control_client()
    >>> control_map = load_control_map({"dofs": {"my_index": "vhi.prediction.index"}})
    >>> controls = resolve(control_map, client.capabilities())   # needs VHI running
    >>> bus = ControlBus(controls, targets=[VhiTarget(client=client, interface=vhi)])
    >>> _ = bus.push({"my_index": 0.8})        # sanitised on the way to the wire
    """

    __slots__ = (
        "_client", "_discrete", "_dofs", "_interface",
        "_negotiated", "_outlets", "_pending", "_routed",
    )

    def __init__(self, *, client: Any = None, interface: Any = None) -> None:
        if interface is None:
            raise ValueError(
                "VhiTarget needs an `interface=` to build its streams from. It publishes "
                "one stream per control it drives, each named for that control's address, "
                "which it can only do once `bind` has resolved what those are. Pass "
                "interface=virtual_hand()."
            )
        #: What streams are built from. Never None: every outlet is this target's own.
        self._interface = interface
        self._client = client
        #: The configuration still awaiting a reachable VHI, or None once settled.
        self._pending: ControlSet | None = None
        self._dofs: tuple[Continuous, ...] = ()
        #: Names of the held states this target commands over gRPC once negotiated.
        self._discrete: tuple[str, ...] = ()
        #: One outlet per address driven, keyed by address. Owned outright: replaced only
        #: through `_publish`, which retires what it drops.
        self._outlets: dict[str, PoseSink] = {}
        #: Negotiated routes: (alias, weight, lo, hi, address). The address is the key
        #: into `_outlets`; the alias cannot be, since a fan-out sends one alias to
        #: several addresses.
        self._routed: tuple[tuple[str, float, float, float, str], ...] = ()
        #: Tracked explicitly: a configuration of
        #: only discrete DOFs negotiates fine and drives no stream at all.
        self._negotiated = False

    @property
    def claims(self) -> frozenset[str]:
        """Which aliases this target actually drives.

        `ControlBus` reads this to check that every control was claimed by *someone* — a
        map may also name controls another target renders, a keyboard's for instance.
        """
        return frozenset({alias for alias, *_ in self._routed} | set(self._discrete))

    @property
    def negotiated(self) -> bool:
        """Whether the contract has been settled with the renderer."""
        return self._negotiated

    def bind(self, controls: ControlSet) -> None:
        """Negotiate the control space with VHI, or defer until it is reachable.

        Raises
        ------
        ValueError
            When no client was given, when the renderer is too old for the vocabulary
            this client speaks, or when it answers and the configuration cannot be
            rendered — an address it does not export, or two aliases aimed at one
            control. A renderer too old to answer `capabilities()` at all looks identical
            to one that is simply not up yet, so that case is deferred, never raised.
        Exception
            Whatever an outlet raises: a settled negotiation puts each declared rest
            value on the wire, so a stream that cannot be published fails here rather
            than per tick. Deliberate — this is a main-thread setup call where a
            traceback is visible, and a target that cannot write at bind will not write
            later either.
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
                "VhiTarget needs a control client: every address, range and state "
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
        Exception
            Whatever an outlet raises when the rest values that settle a negotiation are
            pushed onto a dead one — the same reason `bind` can, and the same remedy.
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

    def _negotiate(self, controls: ControlSet) -> bool:
        """Try the handshake, and leave no streams behind if it refuses.

        False means "no answer yet", never a refusal.
        """
        try:
            return self._settle(controls)
        except Exception:
            # A refused (re)negotiation must not leave the previous binding's streams
            # published. Nothing drives them any more, and a live outlet keeps its name
            # resolvable and keeps republishing whatever it was last given — a hand
            # frozen mid-gesture with no producer behind it, which reads exactly like a
            # hand being held there on purpose.
            #
            # Stopped, not rested: an outlet that raised is a plausible reason to be here
            # at all, and a teardown that raised in turn would replace the error that
            # says what is actually wrong. Suppressed for that reason and no other.
            for outlet in self._outlets.values():
                with suppress(Exception):
                    outlet.stop()
            self._outlets = {}
            raise

    def _settle(self, controls: ControlSet) -> bool:
        """Resolve alias -> address through the renderer's own manifest, and publish.

        The addresses come from the configuration, the ranges from the renderer. A
        configuration that carries no routes is handed the ones its DOF names imply and
        travels this same path, so there is one resolution here rather than one per kind
        of `ControlSet`.
        """
        capabilities = self.capabilities()
        if capabilities is None:
            return False
        exported = {cap.address: cap for cap in capabilities}
        routes, mine = self._scope_or_refuse(controls, exported)
        if not mine:
            # Nothing in this file is ours. Not an error: `ControlBus` checks that
            # *someone* claims every alias, so an unrendered alias is still caught.
            log.info("VHI renders none of %d configured control(s)", len(controls.dofs))
            self._dofs = ()
            self._discrete = ()
            self._publish((), {})
            self._routed = ()
            self._negotiated = True
            return True
        slots: list[tuple[str, float, float, float, str]] = []
        taken: dict[str, str] = {}
        for alias, refs in routes.items():
            if alias not in controls.dofs or not isinstance(controls.dofs[alias], Continuous):
                continue  # discrete aliases travel over gRPC, not a stream
            for ref in refs:
                cap = exported.get(ref.address)
                if cap is None or getattr(cap, "kind", "") != "continuous":
                    raise ValueError(
                        f"{alias!r} points at {ref.address!r}, which no target can drive "
                        f"as a number: the renderer does not export it as one. "
                        f"Check the address against what it does export — "
                        f"vhi.prediction.* is the model's hand and vhi.control.pose.* the "
                        f"operator's."
                    )
                if ref.address in taken:
                    if taken[ref.address] != alias:
                        # Two of the user's outputs aiming at one control: whichever
                        # wrote last would win silently.
                        raise ValueError(
                            f"{taken[ref.address]!r} and {alias!r} both map to "
                            f"{ref.address!r}. One control cannot take two outputs — "
                            f"remove one, or fan a single output out to several controls "
                            f"instead."
                        )
                    continue  # this alias already drives this address
                taken[ref.address] = alias
                slots.append(
                    (
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
        self._publish(
            tuple(address for *_, address in slots),
            {address: float(cap.rest) for address, cap in exported.items()},
        )
        self._routed = tuple(slots)
        self._negotiated = True
        # Put each declared rest value on the wire immediately: the hand should hold what
        # this configuration calls rest, and the renderer drops an inlet that has never
        # sent anything, re-resolving it in a loop until someone touches the UI.
        if self._routed:
            self._push({dof.name: dof.rest for dof in self._dofs})
        log.info(
            "VHI routed %d alias-address pairs onto %d stream(s)",
            len(slots),
            len(self._outlets),
        )
        return True

    def _publish(self, addresses: tuple[str, ...], rests: Mapping[str, float]) -> None:
        """Swap this target's outlets to exactly one per address in `addresses`.

        **Transactional, because the alternative leaks.** The old code held one outlet
        and simply overwrote the field on a rebind, which drops a *native* object: liblsl
        keeps a stream discoverable for as long as its `StreamOutlet` is alive, so the
        abandoned one stayed on the network sharing a ``source_id`` with its replacement
        and a consumer could resolve either. One outlet made that a curiosity; one per
        address makes it eighteen.

        So: work out the new set, retire what is leaving (rest, flush, stop — see
        `_retire`), build only what is genuinely new, and swap the mapping last. An
        address that survives a rebind keeps the outlet it already had rather than losing
        and regaining a stream the renderer would have to re-resolve, which is a visible
        stall on the hand for a change that did not concern it.

        `rests` is the renderer's own declared rest per address, from the manifest — the
        value to leave a departing stream at. Not the *DOF's* rest, which by definition
        no longer exists for an address this configuration has stopped driving.
        """
        for address, outlet in list(self._outlets.items()):
            if address not in addresses:
                _retire(outlet, rests.get(address, 0.0))
        kept = {a: o for a, o in self._outlets.items() if a in addresses}
        self._outlets = {
            address: kept[address]
            if address in kept
            else self._interface.stream_outlet(address, n_channels=1)
            for address in addresses
        }

    @staticmethod
    def _scope_or_refuse(
        controls: ControlSet,
        exported: Mapping[str, Capability],
    ) -> tuple[Mapping[str, tuple[Any, ...]], set[str]]:
        """What to route and which aliases are this target's — or raise.

        The one thing the two kinds of configuration disagree about, strictness
        included; the resolution itself is shared.

        A **resolved** set carries routes and may name controls another target renders,
        so ownership goes by **namespace**, not exact address: a `vhi.*` address this
        build does not export is still refused by `_settle`, while a `keyboard.*` control
        sharing the file is in no VHI namespace and is simply not ours.

        A set built **directly** — a rig diagnostic, a test — carries no routes: its DOF
        names *are* the addresses, nothing upstream checked them, and there is no other
        target to leave anything to. So every name must be exported, and that has to be
        checked here: the tolerance above would read an unexported name as somebody
        else's rather than as the typo it is.
        """
        if controls.routes:
            namespaces = {address.split(".", 1)[0] for address in exported}
            return controls.routes, {
                alias
                for alias, refs in controls.routes.items()
                if any(
                    getattr(ref, "address", "").split(".", 1)[0] in namespaces
                    for ref in refs
                )
            }
        renderable = {
            address
            for address, cap in exported.items()
            if getattr(cap, "kind", "") == "continuous"
        }
        missing = [name for name in controls.channel_labels() if name not in renderable]
        if missing:
            raise ValueError(
                f"VHI renders {sorted(renderable)} as numbers, which has no place for "
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
        """Encode one sample per driven control for the negotiated contract.

        Only the names `bind` accepted are read, and each falls back to its own
        declared rest, so neither a stray key nor a missing one can move a joint or
        raise on the predict thread.

        ``changed`` carries discrete edges, which go over gRPC rather than onto a stream.
        """
        self._push(values)
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

    def _push(self, values: Mapping[str, float | str]) -> None:
        """Send one value to each control's own stream, in the negotiated ranges."""
        each = {dof.name: float(values.get(dof.name, dof.rest)) for dof in self._dofs}
        for alias, weight, lo, hi, address in self._routed:
            # Weight first, then the target's own range — a gain must not be able to
            # push a value past what the target said it accepts.
            self._outlets[address].push(
                _sample(min(hi, max(lo, weight * each.get(alias, 0.0))))
            )

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
        """Return the hand to its declared rest pose, and take every stream down.

        Each outlet is this target's own — it built them all — so each is stopped here.
        Nothing else can: see `_retire`.
        """
        if self._routed:
            self._push({dof.name: dof.rest for dof in self._dofs})
        for outlet in self._outlets.values():
            outlet.flush()
            outlet.stop()
        self._outlets = {}
        self._routed = ()


__all__ = ["PoseSink", "VhiTarget"]
