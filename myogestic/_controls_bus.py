"""Sanitise a control frame once, then fan it out to every target.

Private implementation of `myogestic.controls.Target` and
`myogestic.controls.ControlBus`, re-exported there. The standard stays in
`controls.py`; the runtime lives here.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping, Sequence
from threading import Lock, Thread, current_thread
from time import monotonic
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from myogestic._controls_core import Continuous, ControlSet, Discrete, clip, encode, substitute_rest
from myogestic.outputs.edge_trigger import EdgeTrigger

log = logging.getLogger("myogestic.controls")

if TYPE_CHECKING:
    from myogestic.outputs.filters import VectorFilter


class Target(Protocol):
    """Drive some control DOFs. One protocol for every application.

    A target is **user-owned**, exactly like `myogestic.outputs.Outlet`: construct
    it, hand it to a `ControlBus`, and register teardown with
    ``app.cleanup_hooks``. The framework does not track it.

    Notes
    -----
    `bind` runs on the main thread at construction and **may raise** — that is the
    place to reject a configuration this target cannot drive, while there is still
    a human reading the traceback. `send` runs on the predict thread and must not
    raise; the bus already guarantees every value it delivers is finite and inside
    its declared range.
    """

    def bind(self, controls: ControlSet) -> None:
        """Accept (or refuse) a configuration, before anything is running."""
        ...

    def send(self, values: Mapping[str, float | str], changed: Mapping[str, str]) -> None:
        """Actuate one tick.

        Parameters
        ----------
        values
            Every declared DOF, sanitised: continuous names map to finite floats
            inside their declared range, discrete names to a valid state.
        changed
            Only the discrete DOFs whose state settled *this* tick — the edges. A
            continuous DOF is always in ``values``; a discrete one is only in
            ``changed`` when it just changed, because re-sending a keystroke is not
            the same as re-sending a pose.
        """
        ...

    def stop(self) -> None:
        """Release whatever this target owns. Must be idempotent."""
        ...

    # --- optional, and the bus asks for them by name -----------------------------
    #
    # Declared here because they were not, and a target only found out about them by
    # reading `ControlBus`. Both are read with `getattr`, so leaving them off is legal
    # and means something specific rather than nothing.

    claims: frozenset[str]
    """Which aliases this target drives, for the bus's coverage check.

    Absent means "assume it takes everything" — right for a recorder or a test double
    that does not know. But if *every* target reports and a control appears in none of
    them, nothing drives it, which looks exactly like a control that works and holds
    still. Report it if you can.
    """

    def capabilities(self) -> Sequence[Any] | None:
        """What this target exports, as `myogestic.controls.Capability` values.

        What `myogestic.controls.connect_controls` asks so it can resolve a map before
        anything is bound. Return `None` — not an empty sequence — while the target
        cannot answer, e.g. a remote target that has not started: empty reads as "drives
        nothing" and would resolve to a bus that silently drives nothing.

        Absent is fine for a target whose vocabulary is fixed and known to the caller.
        """
        ...


class ControlBus:
    """Sanitise a frame once, then deliver it to every target.

    Owns the one ordering that must not be re-derived per application::

        substitute rest -> clip -> dead zone -> smooth
                        -> substitute rest -> clip -> deliver

    Rest substitution comes **first** because ``min(hi, max(lo, nan))`` is ``lo`` —
    a NaN would otherwise become full-scale deflection. It happens **again** after
    smoothing because `numpy.clip` passes NaN straight through and a filter carries
    state, so one bad sample would otherwise poison every later one. The final clip
    is not cosmetic either: a smoother undershoots on a falling edge, and for a
    one-way DOF whose rest sits at ``lo`` that undershoot is a sign flip into a
    direction the DOF declares does not exist.

    Parameters
    ----------
    controls
        The validated configuration.
    targets
        Targets to deliver to. Each is `bind`-ed now, so a target that cannot drive
        this configuration says so while a human is watching.
    smoothing
        Optional `myogestic.outputs.filters.VectorFilter` over the continuous
        vector, applied after mapping. Its output is re-sanitised.
    hz
        The rate `push` is expected to be called at, used to convert each discrete
        DOF's ``debounce_s`` into a tick count. A snapshot: changing the caller's
        rate afterwards changes the effective debounce.
    dead_zone
        Optional symmetric dead zone in normalized units, ``0 <= dead_zone < 1``.
        **No default**, because rest is interior for a signed DOF and the right
        value depends on a real signal — shipping a guessed constant would be a
        guess dressed as a safety feature.
    hysteresis
        Optional threshold, ``0 <= hysteresis < 1``, a value must exceed to cross
        rest into the *opposite* direction. Also without a default, and for the
        same reason.
    on_warn
        Called the **first** time each distinct condition occurs — a clamp, a failed
        target, a failed frame. Deliberately once per condition rather than per
        tick: at ``predict_hz`` a repeated warning erases the log that would explain
        it. Pass ``ctx.log`` to surface these in the app.

    Notes
    -----
    `push` is called from the predict thread and `select` / `rebase` from the UI
    thread. That pairing is safe without a lock because the only shared mutable
    state is each `EdgeTrigger`'s single tuple, which is replaced by one atomic
    assignment. Anything added here that mutates more than one field at a time
    needs a lock.
    """

    __slots__ = (
        "_controls",
        "_targets",
        "_smoothing",
        "_hz",
        "_dead_zone",
        "_hysteresis",
        "_triggers",
        "_fired",
        "_lo",
        "_hi",
        "_names",
        "_sign",
        "_reported",
        "_on_warn",
    )

    def __init__(
        self,
        controls: ControlSet,
        *,
        targets: Sequence[Target] = (),
        smoothing: VectorFilter | None = None,
        hz: float = 50.0,
        dead_zone: float | None = None,
        hysteresis: float | None = None,
        on_warn: Callable[[str], None] | None = None,
    ) -> None:
        if hz <= 0 or not math.isfinite(hz):
            raise ValueError(f"hz must be > 0 (got {hz})")
        for label, v in (("dead_zone", dead_zone), ("hysteresis", hysteresis)):
            if v is not None and not (0.0 <= v < 1.0 and math.isfinite(v)):
                raise ValueError(f"{label} must be >= 0 and < 1 (got {v})")

        self._controls = controls
        self._targets = tuple(targets)
        self._smoothing = smoothing
        self._hz = float(hz)
        self._dead_zone = dead_zone
        self._hysteresis = hysteresis
        self._on_warn = on_warn
        self._reported: set[str] = set()

        cont = controls.continuous
        self._names = tuple(d.name for d in cont)
        self._lo = np.array([d.lo for d in cont], dtype=np.float32)
        self._hi = np.array([d.hi for d in cont], dtype=np.float32)
        self._sign: dict[str, float] = {d.name: 0.0 for d in cont}

        self._fired: dict[str, str] = {}
        self._triggers: dict[str, EdgeTrigger[str]] = {}
        for dof in controls.discrete:
            ticks = max(1, math.ceil(dof.debounce_s * self._hz))
            self._triggers[dof.name] = EdgeTrigger(self._record(dof.name), n_stable_ticks=ticks)

        for target in self._targets:
            target.bind(controls)
        self._check_every_control_is_claimed(controls)

    def _check_every_control_is_claimed(self, controls: ControlSet) -> None:
        """Refuse a control no target will drive.

        Several targets can share one control space — one per Virtual Hand, say — so no
        single target need claim all of it, and a target that does not know what it claims
        (a recorder, a test double) is assumed to take everything. But if *every* target
        reports its claims and a control appears in none of them, nothing drives it: the
        failure that looks exactly like a control which is working and holding still.
        """
        reported = [getattr(target, "claims", None) for target in self._targets]
        if not reported or any(claims is None for claims in reported):
            return
        claimed: set[str] = set()
        for claims in reported:
            claimed |= set(claims)
        orphans = [name for name in controls.dofs if name not in claimed]
        if orphans:
            raise ValueError(
                f"no target drives {sorted(orphans)}. Each target claims the addresses it "
                f"handles, so a control claimed by none of them needs a target of its own "
                f"— add one, or take the control out of the map."
            )

    def _record(self, name: str) -> Callable[[str], None]:
        """An `EdgeTrigger` callback that notes an edge for this tick."""

        def note(state: str) -> None:
            self._fired[name] = state

        return note

    def _warn_once(self, key: str, message: str) -> None:
        """Report a condition the first time only — a per-tick log erases itself."""
        if key in self._reported:
            return
        self._reported.add(key)
        if self._on_warn is not None:
            self._on_warn(message)

    def _condition(self, name: str, v: float, dof: Continuous) -> float:
        """Apply the dead zone and hysteresis, if the caller configured them."""
        if self._dead_zone:
            dz = self._dead_zone
            mag = abs(v - dof.rest)
            if mag < dz:
                return dof.rest
            # Rescale so the edge of the dead zone stays continuous rather than
            # jumping by dz the moment the signal escapes it.
            v = dof.rest + math.copysign((mag - dz) / (1.0 - dz), v - dof.rest)
        if self._hysteresis and dof.lo < dof.rest < dof.hi:
            s = math.copysign(1.0, v - dof.rest) if v != dof.rest else 0.0
            last = self._sign[name]
            if s != 0.0 and last != 0.0 and s != last and abs(v - dof.rest) < self._hysteresis:
                return dof.rest
            if s != 0.0:
                self._sign[name] = s
        return v

    def push(self, raw: Mapping[str, Any]) -> Mapping[str, float | str]:
        """Sanitise one frame, deliver it, and return what was delivered.

        Never raises. This runs on the predict thread, where an exception is logged
        with a full traceback on *every* tick — so a failure here degrades to the
        neutral frame instead of burying the log that would explain it.
        """
        try:
            return self._push(raw)
        except Exception as exc:  # noqa: BLE001 - the predict thread must survive
            self._warn_once("push", f"control bus failed, holding rest: {exc!r}")
            rest = self._controls.rest_values()
            self._deliver(rest, {})
            return rest

    def _push(self, raw: Mapping[str, Any]) -> Mapping[str, float | str]:
        values = substitute_rest(self._controls, raw)
        values, clipped = clip(self._controls, values)
        for name in clipped:
            self._warn_once(
                f"clip:{name}",
                f"{name}: value outside its declared range, clamped (reported once)",
            )

        if self._dead_zone or self._hysteresis:
            for dof in self._controls.continuous:
                values[dof.name] = self._condition(dof.name, float(values[dof.name]), dof)

        if self._smoothing is not None and self._names:
            vec = self._smoothing(encode(self._controls, values))
            vec = np.nan_to_num(np.asarray(vec, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
            # Per-channel, because each DOF declares its own domain; a global rail
            # would let a one-way DOF emit the direction it says it cannot.
            vec = np.clip(vec, self._lo, self._hi)
            for i, name in enumerate(self._names):
                values[name] = float(vec[i])

        self._fired = {}
        for name, trigger in self._triggers.items():
            trigger.fire_if_changed(str(values[name]))
        self._deliver(values, dict(self._fired))
        return values

    def _deliver(self, values: Mapping[str, float | str], changed: Mapping[str, str]) -> None:
        """Hand the frame to every target, surviving a target that misbehaves."""
        for target in self._targets:
            try:
                target.send(values, changed)
            except Exception as exc:  # noqa: BLE001 - one bad target must not stop the rest
                self._warn_once(
                    f"send:{type(target).__name__}",
                    f"{type(target).__name__}.send failed, skipping it: {exc!r}",
                )

    def select(self, name: str, state: str) -> bool:
        """Command a discrete DOF from the UI, bypassing the debounce.

        Use this for a manual click: it delivers immediately and rebases the
        trigger, so the next `push` carrying the same state does not fire again.

        Returns
        -------
        bool
            Whether the state was delivered.
        """
        dof = self._controls.dofs.get(name)
        if not isinstance(dof, Discrete) or state not in dof.states:
            return False
        self._triggers[name].rebase(state)
        self._deliver({**self._controls.rest_values(), name: state}, {name: state})
        return True

    def rebase(self, name: str, state: str) -> None:
        """Accept a discrete DOF's state as current without delivering it.

        For when something else already commanded the target and the bus should not
        repeat it.
        """
        dof = self._controls.dofs.get(name)
        if isinstance(dof, Discrete) and state in dof.states:
            self._triggers[name].rebase(state)

    def stop(self) -> None:
        """Deliver the neutral frame, then stop every target. Idempotent.

        Rest is delivered **before** the targets stop: a target that is torn down
        while holding a non-neutral value leaves the application it drives holding
        it too.
        """
        rest = self._controls.rest_values()
        self._deliver(rest, {n: str(rest[n]) for n in self._triggers})
        for target in self._targets:
            try:
                target.stop()
            except Exception as exc:  # noqa: BLE001 - teardown continues regardless
                self._warn_once(f"stop:{type(target).__name__}", f"stop failed: {exc!r}")


def connect_controls(
    control_map: Any,
    targets: Sequence[Any],
    *,
    ctx: Any = None,
    hz: float = 32.0,
    smoothing: Any = None,
) -> ControlBus | None:
    """Resolve a map against what `targets` export, and build the bus. `None` if they cannot say yet.

    The bind every VHI application has to do, and had to write out: a control map names
    *addresses*, and what an address means — number or held state, its range, its neutral
    value — belongs to the target. So a map cannot be resolved until the targets can
    answer, and an application that launches its own target has nobody to ask at import.

    Call it from a UI handler, or anywhere that can afford to block, and call it again
    until it returns something. **Never from a predict callback**: asking a target costs
    an RPC, and stalling the control loop on it is worse than a frame with no bus.

    Parameters
    ----------
    control_map
        The parsed `~myogestic.controls.ControlMap`, from `~myogestic.controls.load_control_map`.
    targets
        Every target the map may name, already constructed. Each is asked what it exports;
        one that answers `None` — a remote target that has not started — makes the whole call
        return `None`, because a map resolved against a partial manifest would bind some
        aliases and silently drop the rest. The target list is therefore one atomic failure
        domain. Use separate calls or links for targets that should remain independently
        useful when another one is unavailable.
    ctx
        The app's `~myogestic.Context`. Given one, the map is recorded as
        ``ctx.control_space`` so a recording carries the mapping it was made under, and
        the outcome is logged.
    hz, smoothing
        Passed to `ControlBus`.

    Returns
    -------
    ControlBus or None
        `None` while any target is unreachable. Try again later; nothing is left
        half-built.
    """
    from myogestic._controls_map import resolve

    merged: list[Any] = []
    for target in targets:
        fetch = getattr(target, "capabilities", None)
        try:
            got = fetch() if callable(fetch) else None
        except ValueError as exc:
            # A target that answered and refused the answer — a remote target too old for the
            # vocabulary this client speaks, say. Reported and retried rather than raised:
            # this is called from a button handler, so a raise takes the window down, and
            # the two outcomes a caller can act on are "got a bus" and "did not". The
            # message is the useful half and it says what to do, so it is logged in full
            # rather than reduced to "not reachable".
            if ctx is not None:
                ctx.log(f"{type(target).__name__} refused: {exc}")
            log.warning("%s refused the handshake: %s", type(target).__name__, exc)
            return None
        if got is None:
            if ctx is not None:
                ctx.log(f"{type(target).__name__} not reachable yet — controls stay unresolved")
            return None
        merged.extend(got)

    controls = resolve(control_map, merged)
    # `on_warn` goes to the same place every other message from this function goes. Without
    # it the bus's warnings are computed and dropped: a value clipped to a one-way control's
    # range, a target whose `send` raised. Each is once-only and each is the only sign that
    # something is being quietly held still.
    bus = ControlBus(
        controls,
        targets=list(targets),
        smoothing=smoothing,
        hz=hz,
        on_warn=None if ctx is None else ctx.log,
    )
    if ctx is not None:
        ctx.control_space = control_map
        ctx.log(f"resolved {len(controls.dofs)} control(s)")
    return bus


class ControlLink:
    """Hold `connect_controls`'s retry, so an application does not carry it as a global.

    `connect_controls` answers `None` while a target cannot yet say what it exports,
    which is the *normal* state for an application that launches its own target: it
    necessarily binds before that target exists. That leaves every such application
    holding the same three things — a nullable bus, a guard, and a re-try — and every
    one of them wrote it out. This is those three things and nothing else.

    Parameters
    ----------
    control_map, targets, ctx, hz, smoothing
        Exactly `connect_controls`'s arguments, kept for every attempt. The targets are
        constructed **once** by the caller and reused: a failed attempt asks each target
        for its capabilities and stops there, so nothing is bound and no target is left
        part-way.

    Examples
    --------
    >>> from myogestic.controls import ControlLink, load_control_map
    >>> class NotStartedYet:
    ...     def capabilities(self):
    ...         return None                   # the target is not up
    >>> control_map = load_control_map({"dofs": {"aim": "cursor.x"}})
    >>> link = ControlLink(control_map, [NotStartedYet()])
    >>> link.ensure() is None                 # call it again on the next click
    True
    >>> link.bus is None
    True

    Notes
    -----
    Call `ensure` from a UI handler or a training thread — anywhere that can afford to
    block — and **never from ``@pipeline.predict``**: asking a target what it exports
    costs a blocking RPC, and that callback has a deadline. `predict` reads `bus` and
    no-ops while it is `None`. One link is one atomic failure domain: if independently
    useful targets may start or fail separately, give each its own map and link.
    """

    __slots__ = ("_bus", "_control_map", "_ctx", "_hz", "_smoothing", "_targets")

    def __init__(
        self,
        control_map: Any,
        targets: Sequence[Any],
        *,
        ctx: Any = None,
        hz: float = 32.0,
        smoothing: Any = None,
    ) -> None:
        self._control_map = control_map
        self._targets = list(targets)
        self._ctx = ctx
        self._hz = hz
        self._smoothing = smoothing
        self._bus: ControlBus | None = None

    @property
    def bus(self) -> ControlBus | None:
        """The bus, or `None` while no target has answered. Read-only."""
        return self._bus

    def ensure(self) -> ControlBus | None:
        """Bind if it is not bound yet, and return the bus. Idempotent and cheap once bound.

        Returns
        -------
        ControlBus or None
            `None` while any target is still unreachable — try again later. Safe to call
            on every click; once it has answered, this is one attribute read.
        """
        if self._bus is None:
            self._bus = connect_controls(
                self._control_map,
                self._targets,
                ctx=self._ctx,
                hz=self._hz,
                smoothing=self._smoothing,
            )
        return self._bus

    def stop(self) -> None:
        """Rest and tear down the bus, and forget it. Idempotent.

        The link is reusable afterwards: the next `ensure` binds the same targets again.
        """
        bus, self._bus = self._bus, None
        if bus is not None:
            bus.stop()


class ControlLinkConnector:
    """Resolve a deferred `ControlLink` without blocking UI or prediction frames.

    A target launched from an application's process panel cannot answer its capability
    request when the application first opens. `ControlLink` deliberately keeps the
    blocking retry explicit; this coordinator supplies a rate-limited, single-flight
    background retry for UI loops.

    Parameters
    ----------
    link
        The `ControlLink` to resolve. It remains the owner of the eventual bus.
    retry_s
        Minimum time between background attempts. ``poll(force=True)`` bypasses this
        interval, but never starts a second attempt while one is in flight.

    Notes
    -----
    Call `poll` from a UI loop. Prediction code only reads ``link.bus`` or ``connected``;
    it never calls `ControlLink.ensure`, which may block on a remote procedure call.
    """

    __slots__ = (
        "_busy",
        "_last_attempt",
        "_last_error",
        "_link",
        "_lock",
        "_retry_s",
        "_status",
        "_stopped",
        "_worker",
    )

    def __init__(self, link: ControlLink, *, retry_s: float = 2.0) -> None:
        if retry_s < 0 or not math.isfinite(retry_s):
            raise ValueError("retry_s must be finite and non-negative")
        self._link = link
        self._retry_s = float(retry_s)
        self._lock = Lock()
        self._worker: Thread | None = None
        self._last_attempt = float("-inf")
        self._last_error: Exception | None = None
        self._busy = False
        self._stopped = False
        self._status = "controls not connected"

    @property
    def connected(self) -> bool:
        """Whether the link has resolved to a bus."""
        return self._link.bus is not None

    @property
    def busy(self) -> bool:
        """Whether a capability request is currently in flight."""
        with self._lock:
            return self._busy

    @property
    def status(self) -> str:
        """A short status suitable for an application's process panel."""
        if self.connected:
            return "controls connected"
        with self._lock:
            return self._status

    @property
    def last_error(self) -> Exception | None:
        """The most recent unexpected connection error, or `None`."""
        with self._lock:
            return self._last_error

    def _attempt(self) -> ControlBus | None:
        try:
            bus = self._link.ensure()
        except Exception as exc:  # noqa: BLE001 - report background failures as state
            with self._lock:
                self._last_error = exc
                self._status = f"control connection failed: {exc}"
            return None

        with self._lock:
            self._last_error = None
            self._status = (
                "controls connected" if bus is not None else "waiting for control targets"
            )
        return bus

    def _run(self) -> None:
        bus = self._attempt()
        with self._lock:
            self._busy = False
            stopped = self._stopped
            if stopped:
                self._status = "control connection stopped"
        if stopped and bus is not None:
            # The application may have closed while a target RPC was in flight.
            self._link.stop()

    def poll(self, *, force: bool = False) -> bool:
        """Start one non-blocking connection attempt when it is due.

        Returns
        -------
        bool
            `True` only when this call started a worker.
        """
        if self.connected:
            return False

        now = monotonic()
        with self._lock:
            if self._stopped or self._busy:
                return False
            if not force and now - self._last_attempt < self._retry_s:
                return False
            self._last_attempt = now
            self._last_error = None
            self._busy = True
            self._status = "connecting controls…"
            worker = Thread(target=self._run, name="control-link-connect", daemon=True)
            self._worker = worker
        try:
            worker.start()
        except Exception:
            with self._lock:
                self._busy = False
            raise
        return True

    def ensure_now(self) -> ControlBus | None:
        """Make one synchronous attempt unless a background worker owns it."""
        if self.connected:
            return self._link.bus
        with self._lock:
            if self._stopped or self._busy:
                return self._link.bus
            self._last_attempt = monotonic()
            self._last_error = None
            self._busy = True
            self._status = "connecting controls…"
        try:
            bus = self._attempt()
            with self._lock:
                stopped = self._stopped
            if stopped and bus is not None:
                self._link.stop()
                return None
            return bus
        finally:
            with self._lock:
                self._busy = False
                if self._stopped:
                    self._status = "control connection stopped"

    def stop(self, *, timeout_s: float = 4.0) -> None:
        """Stop retrying, tear down the bus, and briefly join an in-flight request."""
        with self._lock:
            self._stopped = True
            self._status = "control connection stopped"
            worker = self._worker
        self._link.stop()
        if worker is not None and worker is not current_thread():
            worker.join(timeout=max(0.0, timeout_s))
