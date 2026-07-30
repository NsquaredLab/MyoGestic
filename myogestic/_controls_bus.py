"""Sanitise a control frame once, then fan it out to every target.

Private implementation of `myogestic.controls.Target` and
`myogestic.controls.ControlBus`, re-exported there. The standard stays in
`controls.py`; the runtime lives here.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from myogestic._controls_core import Continuous, ControlSet, Discrete, clip, encode, substitute_rest
from myogestic.outputs.edge_trigger import EdgeTrigger

if TYPE_CHECKING:
    from myogestic.outputs.filters import VectorFilter


class Target(Protocol):
    """Render some control DOFs. One protocol for every application.

    A target is **user-owned**, exactly like `myogestic.outputs.Output`: construct
    it, hand it to a `ControlBus`, and register teardown with
    ``app.cleanup_hooks``. The framework does not track it.

    Notes
    -----
    `bind` runs on the main thread at construction and **may raise** — that is the
    place to reject a configuration this target cannot render, while there is still
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
        Targets to deliver to. Each is `bind`-ed now, so a target that cannot render
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
        "_controls", "_targets", "_smoothing", "_hz", "_dead_zone", "_hysteresis",
        "_triggers", "_fired", "_lo", "_hi", "_names", "_sign", "_reported", "_on_warn",
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
            self._triggers[dof.name] = EdgeTrigger(
                self._record(dof.name), n_stable_ticks=ticks
            )

        for target in self._targets:
            target.bind(controls)
        self._check_every_control_is_claimed(controls)

    def _check_every_control_is_claimed(self, controls: ControlSet) -> None:
        """Refuse a control no target will render.

        Several targets can share one control space — one per Virtual Hand, say — so no
        single target need claim all of it, and a target that does not know what it claims
        (a recorder, a test double) is assumed to take everything. But if *every* target
        reports its claims and a control appears in none of them, nothing renders it: the
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
                f"no target renders {sorted(orphans)}. Each target drives one of the "
                f"renderer's pose streams, so a control on another stream needs a target "
                f"for that stream too — add one, or take the control out of the map."
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
            vec = np.nan_to_num(np.asarray(vec, dtype=np.float32), nan=0.0,
                                posinf=0.0, neginf=0.0)
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
