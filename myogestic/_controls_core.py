"""Model, loader and pure transforms for the control standard.

Private core of `myogestic.controls`, the public entry point, which carries the
standard's reference documentation and re-exports everything here. `_controls_bus`
imports this; `controls` imports both.

Continuous DOFs are signed and normalized to ``[-1, 1]`` with ``0`` at rest; a
name denotes its ``+1`` direction. Nothing here knows what a target is.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Version of the *vocabulary format* — not of the recorded archive layout.
STANDARD_VERSION = "1"



@dataclass(frozen=True, slots=True)
class Continuous:
    """A signed, normalized DOF. ``+1`` is the direction the name denotes.

    Attributes
    ----------
    name
        The alias this control was declared under — the user's own name for a model
        output, e.g. ``"my_index"``. Never interpreted.
    lo, hi
        The declared domain. Defaults to ``[-1.0, 1.0]`` — genuinely
        bidirectional, because a wrist or cursor axis needs both directions.
    rest
        The value meaning "no command". Must lie inside the domain.
    label
        Optional display label; the name is used when empty.
    threshold_fraction
        Set when this control is driven by a **classifier** rather than a regressor: the
        input is a probability in ``[0, 1]``, and this is the fraction at which it counts
        as active. Below it the value becomes ``0.0``; at or above it, ``1.0``. Gated here,
        before anything else sees the number.

        Distinct from a target's `Capability.activation_threshold`: this one is about the
        model's confidence. The gated 0/1 is an ordinary control value, fanned out and
        weighted like any other. ``None`` uses the value as given.

    Examples
    --------
    >>> from myogestic.controls import Continuous
    >>> Continuous("my_index").rest
    0.0
    """

    name: str
    lo: float = -1.0
    hi: float = 1.0
    rest: float = 0.0
    label: str = ""
    threshold_fraction: float | None = None


@dataclass(frozen=True, slots=True)
class Discrete:
    """A DOF holding exactly one of ``states``.

    A discrete DOF is a **held state**, not an event stream: it is delivered on
    change, and a repeat is expressed by returning through ``rest``.

    Attributes
    ----------
    name
        The alias this control was declared under. Never interpreted.
    states
        At least two unique state names. These double as display labels.
    rest
        The neutral state. Must be one of ``states``.
    debounce_s
        Seconds a new state must hold before it is delivered. ``0.0`` delivers
        every change immediately.
    activates
        The state a **numeric** activation selects once it reaches `threshold_fraction`.
        Set when the target declares exactly two states, so a binary classifier emitting a
        probability in ``[0, 1]`` needs no thresholding of its own. Empty when a scalar
        cannot pick a state: with three or more states a number is ambiguous.
    threshold_fraction
        The probability fraction at which `activates` is selected. Taken from the target
        when it declares one (`Capability.activation_threshold`); overridable per binding.
    label
        Optional display label; the name is used when empty.

    Examples
    --------
    >>> from myogestic.controls import Discrete
    >>> Discrete("gesture", ("rest", "fist"), "rest").states
    ('rest', 'fist')
    """

    name: str
    states: tuple[str, ...]
    rest: str
    debounce_s: float = 0.0
    label: str = ""
    activates: str = ""
    threshold_fraction: float = 0.5


Dof = Continuous | Discrete
"""Either kind of DOF. A tagged union, so `ty` can check a match exhaustively."""


@dataclass(frozen=True, slots=True)
class ControlSet:
    """A validated control configuration.

    ``dofs`` preserves declaration order, and that order **is** the wire
    order: it is the layout of the vector `encode` produces and the labels a
    target publishes.

    Attributes
    ----------
    dofs
        Resolved DOFs by alias, in declaration order.
    simultaneous
        Control name -> the DOFs it commands. Empty means no declared controls.
    standard_version
        The vocabulary-format version this configuration was written against.
        Recorded verbatim and **not** validated: what a version means is settled by
        the target handshake, not by the loader.

    Examples
    --------
    >>> from myogestic.controls import Continuous, ControlSet
    >>> controls = ControlSet(dofs={"my_index": Continuous("my_index")})
    >>> controls.channel_labels()
    ('my_index',)
    """

    dofs: Mapping[str, Dof] = field(default_factory=dict)
    simultaneous: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    standard_version: str = STANDARD_VERSION
    #: Alias -> the target control addresses its value is routed to, with per-target
    #: weights. Populated by `myogestic.controls.resolve`; empty for a configuration
    #: built without a target manifest. A `Dof` describes what the *alias* accepts;
    #: this says where it goes.
    routes: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)

    @property
    def continuous(self) -> tuple[Continuous, ...]:
        """The continuous DOFs, in declaration order."""
        return tuple(d for d in self.dofs.values() if isinstance(d, Continuous))

    @property
    def discrete(self) -> tuple[Discrete, ...]:
        """The discrete DOFs, in declaration order."""
        return tuple(d for d in self.dofs.values() if isinstance(d, Discrete))

    @property
    def n_concurrent(self) -> int:
        """How many controls this configuration declares simultaneous."""
        return len(self.simultaneous)

    def channel_labels(self) -> tuple[str, ...]:
        """Continuous DOF names in wire order — the channel labels to publish."""
        return tuple(d.name for d in self.continuous)

    def rest_values(self) -> dict[str, float | str]:
        """The neutral frame: every DOF at its declared rest."""
        return {d.name: d.rest for d in self.dofs.values()}





def _as_float(v: Any, rest: float) -> tuple[float, bool]:
    """Coerce a runtime value to a finite float, falling back to ``rest``.

    The single coercion every runtime transform uses. It accepts anything numpy hands
    over — ``np.float32`` is **not** a subclass of `float`, and it is this library's
    prediction dtype, so an ``isinstance(v, float)`` test would silently zero every
    real prediction. Strings and bytes are rejected rather than parsed.

    Returns
    -------
    tuple[float, bool]
        The value, and whether ``rest`` was substituted.
    """
    if v is None or isinstance(v, (str, bytes, bytearray)):
        return rest, True
    try:
        f = float(v)
    except Exception:  # noqa: BLE001 - a __float__ that raises must not reach the caller
        return rest, True
    return (f, False) if math.isfinite(f) else (rest, True)


def substitute_rest(controls: ControlSet, values: Mapping[str, Any]) -> dict[str, float | str]:
    """Fill a full frame, replacing anything unusable with the DOF's rest value.

    A missing key, a non-finite number and an unknown discrete state all become
    rest. Keys that are not declared DOFs are dropped.

    Never raises: this runs on the predict thread, where an exception is logged
    with a full traceback on *every* tick.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.controls import Continuous, ControlSet, substitute_rest
    >>> controls = ControlSet(dofs={"a": Continuous("a")})
    >>> substitute_rest(controls, {"a": np.nan, "unrelated": "x"})
    {'a': 0.0}
    """
    out: dict[str, float | str] = {}
    for name, dof in controls.dofs.items():
        v = values.get(name)
        if isinstance(dof, Discrete):
            if isinstance(v, str) and v in dof.states:
                out[name] = v
            elif dof.activates:
                # A model may emit a probability rather than a state name. Threshold it
                # into one *here*, so the debounce gate, the target and the recording all
                # see a named state and never a bare 0.73.
                level, bad = _as_float(v, float("nan"))
                out[name] = (
                    dof.rest if bad or level < dof.threshold_fraction else dof.activates
                )
            else:
                out[name] = dof.rest
        else:
            level, bad = _as_float(v, dof.rest)
            if not bad and dof.threshold_fraction is not None:
                # A classifier's output is an activation, not a joint value. Gate it here
                # so the weights, the wire and the recording all see the 0/1 that was
                # actually decided.
                level = 1.0 if level >= dof.threshold_fraction else 0.0
            out[name] = level
    return out


def clip(
    controls: ControlSet, values: Mapping[str, Any]
) -> tuple[dict[str, float | str], tuple[str, ...]]:
    """Clamp every value into its DOF's **declared** range.

    Clamping is to the declared domain, never to a global rail: a DOF declared
    ``[0.0, 1.0]`` must not be able to emit ``-1``. Unknown discrete states snap to
    rest. Returns the frame and the names that were actually clamped, so a caller
    can report them once instead of every tick.

    Never raises. Call `substitute_rest` first — this assumes finite numbers.

    Examples
    --------
    >>> from myogestic.controls import Continuous, ControlSet, clip
    >>> controls = ControlSet(dofs={"g": Continuous("g", lo=0.0, hi=1.0)})
    >>> clip(controls, {"g": 2.5})
    ({'g': 1.0}, ('g',))
    """
    out: dict[str, float | str] = {}
    clipped: list[str] = []
    for name, dof in controls.dofs.items():
        v = values.get(name)
        if isinstance(dof, Discrete):
            if isinstance(v, str) and v in dof.states:
                out[name] = v
            else:
                out[name] = dof.rest
                clipped.append(name)
            continue
        f, substituted = _as_float(v, dof.rest)
        bounded = min(dof.hi, max(dof.lo, f))
        if substituted or bounded != f:
            clipped.append(name)
        out[name] = bounded
    return out, tuple(clipped)


def encode(controls: ControlSet, values: Mapping[str, Any]) -> np.ndarray:
    """Continuous DOF values as one ``float32`` vector in declaration order.

    Discrete DOFs are absent by construction — they travel as edges, not as a
    per-tick frame. Call `substitute_rest` (and usually `clip`) first.

    Examples
    --------
    >>> from myogestic.controls import Continuous, ControlSet, encode
    >>> controls = ControlSet(dofs={"a": Continuous("a"), "b": Continuous("b")})
    >>> encode(controls, {"a": 0.5, "b": -0.25}).tolist()
    [0.5, -0.25]
    """
    cont = controls.continuous
    vec = np.empty(len(cont), dtype=np.float32)
    for i, dof in enumerate(cont):
        v = values.get(dof.name)
        vec[i] = _as_float(v, dof.rest)[0]
    return vec


def decode(controls: ControlSet, frame: Sequence[float]) -> dict[str, float]:
    """Inverse of `encode` — a wire frame back to named continuous values.

    Raises
    ------
    ValueError
        If ``frame`` is not as wide as the declared continuous DOFs.

    Examples
    --------
    >>> from myogestic.controls import ControlSet, Continuous, decode
    >>> controls = ControlSet(dofs={"a": Continuous("a")})
    >>> decode(controls, [0.75])
    {'a': 0.75}
    """
    cont = controls.continuous
    if len(frame) != len(cont):
        raise ValueError(
            f"frame has {len(frame)} channels but {len(cont)} continuous DOFs are "
            f"declared ({[d.name for d in cont]}). `decode` is the exact inverse "
            f"of `encode`; a wider pose frame is a target concern, not a control-standard one."
        )
    return {dof.name: float(frame[i]) for i, dof in enumerate(cont)}

