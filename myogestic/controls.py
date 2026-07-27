"""The canonical control standard — named DOFs, independent of any application.

MyoGestic defines the vocabulary; VHI, a keyboard, a cursor or a robotic hand are
*targets* that render some of it. Nothing in this module knows what any of them
are: there is no channel index, no pose vector, no movement name, no transport.

Three ideas, and that is the whole standard:

- a **DOF** is one named thing a user controls — `Continuous` or `Discrete`;
- a **control** is one entry in ``[simultaneous]``, over one or more DOFs;
- a **target** renders some DOFs (see ``myogestic.controls.Target``, added
  alongside the adapters).

Continuous DOFs are **signed and normalized**: ``[-1, 1]`` with ``0`` at rest, so
a wrist or cursor axis has both directions without anyone configuring one. A name
denotes its ``+1`` direction — ``index.flexion`` is flexion at ``+1`` and
extension at ``-1``. One-way controls declare ``range = [0.0, 1.0]``; that is the
exceptional case, not the default.

`load_dofs` takes a plain `Mapping`, never a path, so ``tomllib`` stays out of the
library and a configuration is just a dict of experiment parameters whose
provenance is the caller's business::

    import tomllib
    from pathlib import Path
    from myogestic.controls import load_dofs

    controls = load_dofs(tomllib.loads(Path("controls.toml").read_text()))

The matching TOML is one line per DOF::

    [dofs]
    "index.flexion" = "continuous"                                 # [-1, 1], rest 0
    "hand.grasp"    = ["rest", "fist", "pinch"]                    # array => discrete
    "grip.force"    = { kind = "continuous", range = [0.0, 1.0] }  # one-way

    [simultaneous]
    proportional = ["index.flexion"]
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from myogestic._controls_toml import (
    check_name,
    check_range,
    check_simultaneous,
    check_states,
    normalise_value,
)

#: Version of the *vocabulary format* — not of the recorded archive layout.
STANDARD_VERSION = "1"

__all__ = [
    "STANDARD_VERSION",
    "ControlSet",
    "Continuous",
    "Discrete",
    "Dof",
    "clip",
    "decode",
    "encode",
    "load_dofs",
    "substitute_rest",
]


@dataclass(frozen=True, slots=True)
class Continuous:
    """A signed, normalized DOF. ``+1`` is the direction the name denotes.

    Attributes
    ----------
    name
        Canonical dotted name, e.g. ``"index.flexion"``.
    lo, hi
        The declared domain. Defaults to ``[-1.0, 1.0]`` — genuinely
        bidirectional, because a wrist or cursor axis needs both directions.
    rest
        The value meaning "no command". Must lie inside the domain.
    label
        Optional display label; the name is used when empty.

    Examples
    --------
    >>> from myogestic.controls import Continuous
    >>> Continuous("index.flexion").rest
    0.0
    """

    name: str
    lo: float = -1.0
    hi: float = 1.0
    rest: float = 0.0
    label: str = ""


@dataclass(frozen=True, slots=True)
class Discrete:
    """A DOF holding exactly one of ``states``.

    A discrete DOF is a **held state**, not an event stream: it is delivered on
    change, and a repeat is expressed by returning through ``rest``.

    Attributes
    ----------
    name
        Canonical dotted name, e.g. ``"hand.grasp"``.
    states
        At least two unique state names. These double as display labels.
    rest
        The neutral state. Must be one of ``states``.
    debounce_s
        Seconds a new state must hold before it is delivered. ``0.0`` delivers
        every change immediately.
    label
        Optional display label; the name is used when empty.

    Examples
    --------
    >>> from myogestic.controls import Discrete
    >>> Discrete("hand.grasp", ("rest", "fist"), "rest").states
    ('rest', 'fist')
    """

    name: str
    states: tuple[str, ...]
    rest: str
    debounce_s: float = 0.0
    label: str = ""


Dof = Continuous | Discrete
"""Either kind of DOF. A tagged union, so `ty` can check a match exhaustively."""


@dataclass(frozen=True, slots=True)
class ControlSet:
    """A validated control configuration.

    ``dofs`` preserves declaration order, and that order **is** the canonical wire
    order: it is the layout of the vector `encode` produces and the labels a
    target publishes.

    Attributes
    ----------
    dofs
        Declared DOFs by canonical name, in declaration order.
    simultaneous
        Control name -> the DOFs it commands. Empty means no declared controls.
    standard_version
        The vocabulary-format version this configuration was written against.

    Examples
    --------
    >>> from myogestic.controls import load_dofs
    >>> controls = load_dofs({"dofs": {"index.flexion": "continuous"}})
    >>> controls.channel_labels()
    ('index.flexion',)
    >>> controls.n_concurrent
    0
    """

    dofs: Mapping[str, Dof] = field(default_factory=dict)
    simultaneous: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    standard_version: str = STANDARD_VERSION

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

    def as_dict(self) -> dict[str, Any]:
        """A plain mapping that round-trips through `load_dofs`."""
        dofs: dict[str, Any] = {}
        for d in self.dofs.values():
            if isinstance(d, Continuous):
                entry: dict[str, Any] = {
                    "kind": "continuous",
                    "range": [d.lo, d.hi],
                    "rest": d.rest,
                }
            else:
                entry = {
                    "kind": "discrete",
                    "states": list(d.states),
                    "rest": d.rest,
                    "debounce_s": d.debounce_s,
                }
            if d.label:
                entry["label"] = d.label
            dofs[d.name] = entry
        return {
            "standard_version": self.standard_version,
            "dofs": dofs,
            "simultaneous": {k: list(v) for k, v in self.simultaneous.items()},
        }


def _build_dof(name: str, kw: Mapping[str, Any], errs: list[str]) -> Dof | None:
    """Turn one normalised DOF mapping into a typed DOF, or record why not."""
    kind = kw.get("kind", "continuous")
    label = str(kw.get("label", ""))

    if kind == "discrete":
        states = check_states(name, kw.get("states"), errs)
        if states is None:
            return None
        rest = kw.get("rest", states[0])
        if rest not in states:
            errs.append(
                f"[dofs] {name!r}: rest {rest!r} is not one of {list(states)}. "
                f'Write rest = "{states[0]}".'
            )
            return None
        debounce = kw.get("debounce_s", 0.0)
        if not (isinstance(debounce, (int, float)) and not isinstance(debounce, bool)):
            errs.append(f"[dofs] {name!r}: debounce_s must be a number (got {debounce!r}).")
            return None
        if debounce < 0.0 or not math.isfinite(debounce):
            errs.append(f"[dofs] {name!r}: debounce_s must be >= 0 (got {debounce}).")
            return None
        return Discrete(name, states, str(rest), float(debounce), label)

    if kind != "continuous":
        errs.append(f"[dofs] {name!r}: unknown kind {kind!r}. Choose: 'continuous', 'discrete'.")
        return None

    if "states" in kw:
        errs.append(
            f"[dofs] {name!r}: states belong to a discrete DOF. Add "
            f'kind = "discrete", or remove states.'
        )
        return None

    rng = kw.get("range", [-1.0, 1.0])
    if not (isinstance(rng, (list, tuple)) and len(rng) == 2 and all(_num(v) for v in rng)):
        errs.append(
            f"[dofs] {name!r}: range must be two numbers, e.g. range = [-1.0, 1.0] "
            f"(got {rng!r})."
        )
        return None
    lo, hi = float(rng[0]), float(rng[1])
    if not check_range(name, lo, hi, errs):
        return None

    rest = kw.get("rest", 0.0)
    if not _num(rest):
        errs.append(f"[dofs] {name!r}: rest must be a number (got {rest!r}).")
        return None
    rest = float(rest)
    if not (lo <= rest <= hi):
        errs.append(f"[dofs] {name!r}: rest {rest} is outside range [{lo}, {hi}].")
        return None
    return Continuous(name, lo, hi, rest, label)


def _num(v: Any) -> bool:
    """True for a real number that is not a bool."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def load_dofs(config: Mapping[str, Any]) -> ControlSet:
    """Validate a parsed control configuration.

    Takes a plain mapping — typically ``tomllib.loads(...)`` — never a path, so
    the library never reads a file. Unknown top-level tables are ignored, which is
    what lets a target keep its own settings in the same document.

    Every problem is collected and reported together, so three typos cost one edit
    round-trip rather than three runs.

    Parameters
    ----------
    config
        The parsed configuration. ``dofs`` is required; ``simultaneous`` and
        ``standard_version`` are optional.

    Returns
    -------
    ControlSet
        The validated configuration, preserving declaration order.

    Raises
    ------
    ValueError
        With every fault found, one per line.

    Examples
    --------
    >>> from myogestic.controls import load_dofs
    >>> controls = load_dofs({
    ...     "dofs": {
    ...         "index.flexion": "continuous",
    ...         "hand.grasp": ["rest", "fist"],
    ...     },
    ...     "simultaneous": {"grip": ["hand.grasp"]},
    ... })
    >>> [d.name for d in controls.continuous]
    ['index.flexion']
    >>> controls.dofs["hand.grasp"].rest
    'rest'
    >>> controls.n_concurrent
    1
    """
    errs: list[str] = []
    version = str(config.get("standard_version", STANDARD_VERSION))

    raw = config.get("dofs")
    if raw is None:
        raise ValueError(
            "no [dofs] table. Declare at least one DOF, e.g.\n"
            '  [dofs]\n  "index.flexion" = "continuous"'
        )
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"[dofs] must be a table of name -> kind (got {type(raw).__name__}). "
            'Write e.g. [dofs] then "index.flexion" = "continuous".'
        )

    dofs: dict[str, Dof] = {}
    for name, value in raw.items():
        if not check_name(name, errs):
            continue
        kw = normalise_value(name, value, errs)
        if kw is None:
            continue
        dof = _build_dof(name, kw, errs)
        if dof is not None:
            dofs[name] = dof

    simultaneous = check_simultaneous(config.get("simultaneous"), frozenset(dofs), errs)

    if errs:
        raise ValueError("\n".join(errs))
    return ControlSet(dofs, simultaneous, version)


def substitute_rest(controls: ControlSet, values: Mapping[str, Any]) -> dict[str, float | str]:
    """Fill a full frame, replacing anything unusable with the DOF's rest value.

    A missing key, a non-finite number and an unknown discrete state all become
    rest. Keys that are not declared DOFs are dropped — a ``@pipeline.predict``
    return value carries other things (a class label for the UI, diagnostics), and
    those are not this function's business.

    Never raises. Sanitising on the predict thread must not be able to fail: an
    exception there is logged with a full traceback on *every* tick.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.controls import load_dofs, substitute_rest
    >>> controls = load_dofs({"dofs": {"a.flexion": "continuous"}})
    >>> substitute_rest(controls, {"a.flexion": np.nan, "unrelated": "x"})
    {'a.flexion': 0.0}
    """
    out: dict[str, float | str] = {}
    for name, dof in controls.dofs.items():
        v = values.get(name)
        if isinstance(dof, Discrete):
            out[name] = v if isinstance(v, str) and v in dof.states else dof.rest
            continue
        if v is None or isinstance(v, str):
            out[name] = dof.rest
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            out[name] = dof.rest
            continue
        out[name] = f if math.isfinite(f) else dof.rest
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
    >>> from myogestic.controls import clip, load_dofs
    >>> controls = load_dofs({"dofs": {"g.force": {"kind": "continuous",
    ...                                            "range": [0.0, 1.0]}}})
    >>> clip(controls, {"g.force": 2.5})
    ({'g.force': 1.0}, ('g.force',))
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
        f = float(v) if _num(v) else dof.rest
        if not math.isfinite(f):
            f = dof.rest
        bounded = min(dof.hi, max(dof.lo, f))
        if bounded != f:
            clipped.append(name)
        out[name] = bounded
    return out, tuple(clipped)


def encode(controls: ControlSet, values: Mapping[str, Any]) -> np.ndarray:
    """Continuous DOF values as one ``float32`` vector in declaration order.

    Discrete DOFs are absent by construction — they travel as edges, not as a
    per-tick frame. Call `substitute_rest` (and usually `clip`) first.

    Examples
    --------
    >>> from myogestic.controls import encode, load_dofs
    >>> controls = load_dofs({"dofs": {"a.flexion": "continuous",
    ...                                "b.flexion": "continuous"}})
    >>> encode(controls, {"a.flexion": 0.5, "b.flexion": -0.25}).tolist()
    [0.5, -0.25]
    """
    cont = controls.continuous
    vec = np.empty(len(cont), dtype=np.float32)
    for i, dof in enumerate(cont):
        v = values.get(dof.name)
        vec[i] = float(v) if _num(v) else dof.rest
    return vec


def decode(controls: ControlSet, frame: Sequence[float]) -> dict[str, float]:
    """Inverse of `encode` — a wire frame back to named continuous values.

    One declaration drives both directions, so the channel selection used to
    *serve* a target cannot drift from the one used to *train* against it.

    Raises
    ------
    ValueError
        If ``frame`` is not as wide as the declared continuous DOFs.

    Examples
    --------
    >>> from myogestic.controls import decode, load_dofs
    >>> controls = load_dofs({"dofs": {"a.flexion": "continuous"}})
    >>> decode(controls, [0.75])
    {'a.flexion': 0.75}
    """
    cont = controls.continuous
    if len(frame) < len(cont):
        raise ValueError(
            f"frame has {len(frame)} channels but {len(cont)} continuous DOFs are "
            f"declared ({[d.name for d in cont]})."
        )
    return {dof.name: float(frame[i]) for i, dof in enumerate(cont)}
