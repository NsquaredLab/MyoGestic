"""Map user-owned model outputs onto target-owned control addresses.

Two vocabularies meet here, and keeping them apart is the whole design:

**The left side is yours.** ``fist``, ``my_thumb``, ``drive_x`` — whatever your model
calls its outputs. MyoGestic never prescribes these names, never parses meaning out of
them, and never requires them to look canonical. The same alias may map to a Virtual Hand
in one configuration and to a cursor axis in another.

**The right side belongs to the target.** ``vhi.prediction.index.flexion`` is a name VHI
declares in its own manifest, along with everything needed to send it correctly: whether
it takes a number or a held state, its domain, its neutral value, its states. MyoGestic
resolves those addresses at handshake time and **hard-codes none of their semantics** — a
target that grows a new control needs no change here.

So a declaration is a *mapping*, and it is deliberately not usable until a target has
answered:

.. code-block:: toml

    [dofs]
    my_thumb = "vhi.prediction.thumb"                  # one output, one control

    fist = [                                           # one output, fanned out
      "vhi.prediction.index",
      "vhi.prediction.middle",
    ]

    pinch = [                                          # ...with per-target gain
      { target = "vhi.prediction.thumb", weight = 0.6 },
      { target = "vhi.prediction.index" },
    ]

`load_control_map` parses that into a `ControlMap` — names and structure checked, meaning
still unknown. `resolve` turns it into a `myogestic.controls.ControlSet` once a target has
declared what it can do, and refuses an address the target does not export, naming the
alternatives.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from myogestic._controls_core import Continuous, ControlSet, Discrete

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: A target address: dotted, lowercase, at least two segments. The first segment
#: namespaces the target (``vhi.``, ``keyboard.``, ``cursor.``) so two targets cannot
#: collide in one configuration. This is the *only* name shape this module constrains,
#: and it constrains it because the target owns it — not the user.
_ADDRESS_SEGMENTS = 2

#: Keys accepted in a per-target inline table.
_TARGET_KEYS = frozenset({"target", "weight"})

#: Keys accepted in a binding's inline table (the 1:1-with-metadata form).
_BINDING_KEYS = frozenset({"target", "targets", "weight", "debounce_s", "label"})


def _is_address(value: Any) -> bool:
    """Whether ``value`` looks like a target-owned address rather than a user name."""
    if not isinstance(value, str) or not value:
        return False
    parts = value.split(".")
    if len(parts) < _ADDRESS_SEGMENTS:
        return False
    return all(p and p.replace("_", "a").isalnum() and p == p.lower() for p in parts)


@dataclass(frozen=True, slots=True)
class TargetRef:
    """One target control a binding sends to, and the gain applied on the way.

    Attributes
    ----------
    address
        The target-owned control address, e.g. ``"vhi.prediction.index.flexion"``.
    weight
        Multiplied into the value **before** the target applies its own range. A
        fan-out where one member should move less than the others is the reason this
        exists: ``weight = 0.6`` on a thumb sends it 60% of what the fingers get.
        Defaults to ``1.0``.
    """

    address: str
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class Binding:
    """One ``[dofs]`` line: a user-owned alias bound to one or more target controls.

    Attributes
    ----------
    alias
        The user's own name for a model output. Arbitrary.
    targets
        Where its value goes. More than one is a **broadcast**: the same scalar reaches
        every listed control, each applying its own declared range and direction.
    debounce_s
        For a binding that resolves to a discrete control: how long a state must hold
        before it counts as a transition. Declared here because it is a property of
        *this* control loop, not of the target.
    label
        Optional display label; the alias is used when empty.
    """

    alias: str
    targets: tuple[TargetRef, ...]
    debounce_s: float = 0.0
    label: str = ""


@dataclass(frozen=True, slots=True)
class ControlMap:
    """A parsed but **unresolved** declaration: aliases bound to target addresses.

    Deliberately not a usable control space. Whether ``fist`` is a number or a held
    state, and what its range is, are facts the *target* declares — so a `ControlMap`
    carries no such answers, and `resolve` is where they arrive.

    Examples
    --------
    >>> from myogestic.controls import load_control_map
    >>> cmap = load_control_map({"dofs": {"my_index": "vhi.prediction.index"}})
    >>> cmap.addresses()
    ('vhi.prediction.index',)
    """

    bindings: Mapping[str, Binding] = field(default_factory=dict)

    def addresses(self) -> tuple[str, ...]:
        """Every distinct target address this map references, in first-seen order."""
        seen: dict[str, None] = {}
        for binding in self.bindings.values():
            for ref in binding.targets:
                seen.setdefault(ref.address, None)
        return tuple(seen)

    def as_dict(self) -> dict[str, Any]:
        """A plain mapping that round-trips through `load_control_map`.

        Tagged with `CONTROL_SPACE_FORMAT` so anything that persists it stays legible:
        a reader can name the format it found rather than guessing from the shape.
        """
        dofs: dict[str, Any] = {}
        for binding in self.bindings.values():
            plain = all(ref.weight == 1.0 for ref in binding.targets)
            if plain and len(binding.targets) == 1 and not binding.debounce_s and not binding.label:
                dofs[binding.alias] = binding.targets[0].address
            elif plain and not binding.debounce_s and not binding.label:
                dofs[binding.alias] = [ref.address for ref in binding.targets]
            else:
                entry: dict[str, Any] = {
                    "targets": [
                        {"target": ref.address, "weight": ref.weight} for ref in binding.targets
                    ]
                }
                if binding.debounce_s:
                    entry["debounce_s"] = binding.debounce_s
                if binding.label:
                    entry["label"] = binding.label
                dofs[binding.alias] = entry
        return {"format": CONTROL_SPACE_FORMAT, "dofs": dofs}


@dataclass(frozen=True, slots=True)
class Capability:
    """One control a **target** exports, with the semantics the target declares.

    Built from a target's manifest — for VHI, from its ``GetControlManifest`` reply.
    Nothing in MyoGestic invents these values; a target that changes its mind about a
    control's range says so here and every client follows.

    Attributes
    ----------
    address
        The stable dotted address, e.g. ``"vhi.prediction.index.flexion"``.
    kind
        ``"continuous"`` or ``"discrete"``.
    lo, hi, rest
        Continuous only: the domain and the neutral value.
    states, rest_state
        Discrete only: the accepted states and the neutral one.
    channel
        Which channel of the target's stream carries this control, or ``-1`` when it is
        not streamed. Published per capability rather than inferred from a list, because
        two addresses may legitimately name one control — a short form and its explicit
        axis form.
    encoding
        How a value must be encoded on that stream: ``1`` canonical, ``2``
        legacy-negated, ``0`` unstated. A client that reads ``0`` must not guess.
    stream_name
        Which stream carries it. A channel number is meaningless without this: a target
        may publish two streams, and channel 2 of one is not channel 2 of the other.
    description
        Human-readable. For a log or an error message; never parsed.

    Examples
    --------
    >>> from myogestic.controls import Capability
    >>> Capability("cursor.x_velocity", "continuous", lo=-1.0, hi=1.0).signed
    True
    """

    address: str
    kind: str
    lo: float = -1.0
    hi: float = 1.0
    rest: float = 0.0
    states: tuple[str, ...] = ()
    rest_state: str = ""
    channel: int = -1
    encoding: int = 0
    stream_name: str = ""
    description: str = ""

    @property
    def signed(self) -> bool:
        """Whether this control accepts values on both sides of its neutral value."""
        return self.kind == "continuous" and self.lo < self.rest


# --- parsing -------------------------------------------------------------------


def _parse_target(alias: str, value: Any, errs: list[str]) -> TargetRef | None:
    """One fan-out member: a bare address, or a table with a weight."""
    if _is_address(value):
        return TargetRef(address=value)
    if isinstance(value, str):
        errs.append(
            f"[dofs] {alias!r}: {value!r} is not a target address. An address is dotted "
            f"lowercase with at least two segments and names the *target's* control, "
            f'e.g. "vhi.prediction.index".'
        )
        return None
    if not isinstance(value, dict):
        errs.append(
            f"[dofs] {alias!r}: expected an address or a "
            f'{{ target = "...", weight = 0.6 }} table, got {type(value).__name__}.'
        )
        return None

    unknown = sorted(set(value) - _TARGET_KEYS)
    if unknown:
        errs.append(
            f"[dofs] {alias!r}: unknown key(s) {unknown} in a target table. "
            f"Accepted: {sorted(_TARGET_KEYS)}."
        )
        return None
    address = value.get("target")
    if not _is_address(address):
        errs.append(f"[dofs] {alias!r}: {address!r} is not a target address.")
        return None

    weight = value.get("weight", 1.0)
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        errs.append(f"[dofs] {alias!r}: weight for {address!r} must be a number.")
        return None
    weight = float(weight)
    if not math.isfinite(weight):
        # A non-finite gain becomes a full-scale deflection the moment it is multiplied
        # in, and NaN would defeat the clamp entirely.
        errs.append(f"[dofs] {alias!r}: weight for {address!r} must be finite.")
        return None
    return TargetRef(address=address, weight=weight)


def _parse_binding(alias: Any, value: Any, errs: list[str]) -> Binding | None:
    """One ``[dofs]`` entry. The alias is checked for usability, never for shape."""
    if not isinstance(alias, str) or not alias.strip():
        errs.append(
            f"[dofs] key {alias!r}: an alias must be a non-empty string. It is *your* "
            f"name for a model output — any readable name works."
        )
        return None

    debounce_s = 0.0
    label = ""

    if isinstance(value, dict) and not ({"target", "targets"} & set(value)):
        # TOML turns an unquoted dotted key into a NESTED TABLE, so `my.thumb = "..."`
        # arrives here as alias "my" with value {"thumb": "..."} — a binding nobody
        # wrote, which would otherwise be reported as a mysterious unknown key. The
        # discriminator is the absence of target/targets, and it matters: the old parser
        # had the same trap and a phantom entry there shifted every wire index after it.
        nested = [k for k, v in value.items() if isinstance(v, (str, list, dict))]
        errs.append(
            f"[dofs] {alias!r}: this is a table, not a mapping — TOML read "
            f"{'.'.join([alias, *nested[:1]])} as a nested key. Quote the whole alias if "
            f'it contains a dot: "{".".join([alias, *nested[:1]])}" = "some.target.address". '
            f"Otherwise give it a target, e.g. {alias} = \"vhi.prediction.index\"."
        )
        return None

    if isinstance(value, dict):
        unknown = sorted(set(value) - _BINDING_KEYS)
        if unknown:
            errs.append(
                f"[dofs] {alias!r}: unknown key(s) {unknown}. Accepted: "
                f"{sorted(_BINDING_KEYS)}."
            )
            return None
        raw_targets = value.get("targets", value.get("target"))
        for key, dest in (("debounce_s", "debounce_s"), ("label", "label")):
            if key not in value:
                continue
            got = value[key]
            if dest == "label":
                if not isinstance(got, str):
                    errs.append(f"[dofs] {alias!r}: label must be a string.")
                    return None
                label = got
            else:
                if isinstance(got, bool) or not isinstance(got, (int, float)):
                    errs.append(f"[dofs] {alias!r}: debounce_s must be a number.")
                    return None
                if not math.isfinite(got) or got < 0:
                    errs.append(f"[dofs] {alias!r}: debounce_s must be >= 0 and finite.")
                    return None
                debounce_s = float(got)
        if "weight" in value and isinstance(raw_targets, str):
            raw_targets = {"target": raw_targets, "weight": value["weight"]}
    else:
        raw_targets = value

    items: Sequence[Any] = raw_targets if isinstance(raw_targets, list) else [raw_targets]
    if not items:
        errs.append(f"[dofs] {alias!r}: an empty list binds nothing. Remove it, or name a target.")
        return None

    refs: list[TargetRef] = []
    for item in items:
        ref = _parse_target(alias, item, errs)
        if ref is not None:
            refs.append(ref)
    if len(refs) != len(items):
        return None

    seen: set[str] = set()
    for ref in refs:
        if ref.address in seen:
            # Two entries for one address would silently apply only the last weight.
            errs.append(f"[dofs] {alias!r}: {ref.address!r} is listed more than once.")
            return None
        seen.add(ref.address)

    return Binding(alias=alias, targets=tuple(refs), debounce_s=debounce_s, label=label)


def load_control_map(config: Mapping[str, Any]) -> ControlMap:
    """Parse a ``[dofs]`` mapping of user aliases to target control addresses.

    Takes a `~collections.abc.Mapping`, not a path — parse your own TOML (or JSON, or a
    dict literal) and hand it over, so this library reads no configuration files.

    What this checks is structure, not meaning: that every alias is usable and every
    address is address-shaped. Whether an address *exists*, and what it accepts, is the
    target's to say — see `resolve`.

    Parameters
    ----------
    config
        Typically ``tomllib.load(f)``. The ``dofs`` table maps each alias to one
        address, a list of addresses (a broadcast), or a table with per-target weights.

    Returns
    -------
    ControlMap
        The parsed mapping, still unresolved.

    Raises
    ------
    ValueError
        With **every** fault found, not just the first — a half-corrected config file is
        worse than an uncorrected one.

    Examples
    --------
    >>> from myogestic.controls import load_control_map
    >>> cmap = load_control_map(
    ...     {"dofs": {"fist": ["vhi.prediction.index", "vhi.prediction.middle"]}}
    ... )
    >>> [ref.address for ref in cmap.bindings["fist"].targets]
    ['vhi.prediction.index', 'vhi.prediction.middle']
    """
    errs: list[str] = []
    raw = config.get("dofs")
    if raw is None:
        raise ValueError(
            'no [dofs] table. Map one of your model outputs to a target control, e.g.\n'
            '  [dofs]\n  my_index = "vhi.prediction.index"'
        )
    if not isinstance(raw, dict):
        raise ValueError(f"[dofs] must be a table, got {type(raw).__name__}.")

    bindings: dict[str, Binding] = {}
    for alias, value in raw.items():
        binding = _parse_binding(alias, value, errs)
        if binding is not None:
            bindings[binding.alias] = binding

    if errs:
        raise ValueError("\n".join(errs))
    if not bindings:
        raise ValueError("[dofs] is empty. Declare at least one mapping.")
    return ControlMap(bindings=bindings)


# --- resolution ----------------------------------------------------------------


def _did_you_mean(address: str, available: Sequence[str]) -> str:
    """Addresses sharing the longest dotted prefix with ``address``, for an error."""
    wanted = address.split(".")
    best: list[str] = []
    best_depth = 0
    for candidate in available:
        parts = candidate.split(".")
        depth = 0
        for a, b in zip(wanted, parts, strict=False):
            if a != b:
                break
            depth += 1
        if depth > best_depth:
            best_depth, best = depth, [candidate]
        elif depth == best_depth and depth:
            best.append(candidate)
    return ", ".join(sorted(best))


def resolve(
    control_map: ControlMap, capabilities: Sequence[Capability]
) -> ControlSet:
    """Resolve a `ControlMap` against what a target says it can do.

    This is where meaning arrives. Each alias becomes a
    `myogestic.controls.Continuous` or `myogestic.controls.Discrete` **because its
    target said so** — nothing here decides on the target's behalf.

    The resulting `myogestic.controls.ControlSet` is keyed by *your* aliases, so a
    `myogestic.controls.ControlBus` and every model stay in your vocabulary; the routing
    to addresses travels alongside in `myogestic.controls.ControlSet.routes`.

    Parameters
    ----------
    control_map
        From `load_control_map`.
    capabilities
        What the target exports — for VHI, its ``GetControlManifest`` reply.

    Returns
    -------
    ControlSet
        Resolved, and usable.

    Raises
    ------
    ValueError
        For an address the target does not export (naming the near misses and the full
        list), for a broadcast whose members disagree about kind or states, or for a
        negative weight on a control that does not accept signed values.

    Examples
    --------
    >>> from myogestic.controls import Capability, load_control_map, resolve
    >>> caps = [Capability("cursor.x_velocity", "continuous", lo=-1.0, hi=1.0)]
    >>> cmap = load_control_map({"dofs": {"drive_x": "cursor.x_velocity"}})
    >>> resolved = resolve(cmap, caps)
    >>> resolved.dofs["drive_x"].lo
    -1.0
    """
    by_address = {cap.address: cap for cap in capabilities}
    available = sorted(by_address)
    errs: list[str] = []
    dofs: dict[str, Continuous | Discrete] = {}
    routes: dict[str, tuple[TargetRef, ...]] = {}

    for alias, binding in control_map.bindings.items():
        resolved: list[tuple[TargetRef, Capability]] = []
        missing = False
        for ref in binding.targets:
            cap = by_address.get(ref.address)
            if cap is None:
                near = _did_you_mean(ref.address, available)
                hint = f" Did you mean: {near}?" if near else ""
                errs.append(
                    f"[dofs] {alias!r}: this target does not export {ref.address!r}.{hint}\n"
                    f"    It exports: {', '.join(available) if available else '(nothing)'}"
                )
                missing = True
                continue
            resolved.append((ref, cap))
        if missing or not resolved:
            continue

        kinds = {cap.kind for _, cap in resolved}
        if len(kinds) > 1:
            errs.append(
                f"[dofs] {alias!r}: its targets disagree about what they take "
                f"({sorted(kinds)}). One output cannot be both a number and a held state."
            )
            continue
        kind = kinds.pop()

        for ref, cap in resolved:
            if ref.weight < 0 and not cap.signed:
                errs.append(
                    f"[dofs] {alias!r}: weight {ref.weight} on {ref.address!r} is negative, "
                    f"but that control only accepts [{cap.lo}, {cap.hi}] — it has no "
                    f"opposite direction to send. Use a positive weight, or a target that "
                    f"declares signed motion."
                )

        if kind == "discrete":
            state_sets = {tuple(cap.states) for _, cap in resolved}
            if len(state_sets) > 1:
                errs.append(
                    f"[dofs] {alias!r}: its targets accept different states "
                    f"({[sorted(s) for s in state_sets]}). A broadcast state must mean the "
                    f"same thing everywhere."
                )
                continue
            cap = resolved[0][1]
            if not cap.states:
                errs.append(f"[dofs] {alias!r}: {cap.address!r} declares no states.")
                continue
            dofs[alias] = Discrete(
                name=alias,
                states=tuple(cap.states),
                rest=cap.rest_state or cap.states[0],
                debounce_s=binding.debounce_s,
                label=binding.label,
            )
        else:
            # The alias is signed only if *every* target can render both directions —
            # otherwise a negative prediction would be silently clamped away on one of
            # them, which reads as a control that works and then stops working.
            signed = all(cap.signed for _, cap in resolved)
            dofs[alias] = Continuous(
                name=alias,
                lo=-1.0 if signed else 0.0,
                hi=1.0,
                rest=0.0,
                label=binding.label,
            )
        routes[alias] = tuple(ref for ref, _ in resolved)

    if errs:
        raise ValueError("\n".join(errs))
    return ControlSet(dofs=dofs, routes=routes)


#: The value of ``control_space["format"]`` in a recording written by this version.
CONTROL_SPACE_FORMAT = "alias-address/1"


def read_control_space(raw: Mapping[str, Any]) -> ControlMap:
    """A recording's persisted control space, as a `ControlMap`.

    New recordings store the alias-to-address mapping and tag it with
    `CONTROL_SPACE_FORMAT`. That tag is what makes the format **legible**: a reader can
    say which form a recording used instead of inferring it from the shape.

    Parameters
    ----------
    raw
        The ``control_space`` object out of a session's ``meta.json`` or a model's
        ``.controls.json`` sidecar.

    Returns
    -------
    ControlMap
        Still unresolved — an archived mapping means nothing until a target declares
        what its addresses do, exactly like a freshly parsed file.

    Raises
    ------
    ValueError
        For a control space written in the pre-alias format, naming the format it found.
        It is **not** normalised on the way in: that older shape declared its own kinds
        and ranges, which the target now owns, so silently reinterpreting it would put
        made-up semantics on archived data and call them recorded fact. Re-record, or
        read the archive with the version that wrote it.

    Examples
    --------
    >>> from myogestic.controls import read_control_space
    >>> read_control_space(
    ...     {"format": "alias-address/1", "dofs": {"my_index": "vhi.prediction.index"}}
    ... ).addresses()
    ('vhi.prediction.index',)
    """
    fmt = raw.get("format")
    if fmt == CONTROL_SPACE_FORMAT:
        return load_control_map(raw)
    if fmt is None:
        # The pre-alias shape is recognisable without a tag: its values are kinds
        # ("continuous"), state lists, or tables carrying `kind` — never addresses.
        raise ValueError(
            f"this control space predates the alias/address format "
            f"({CONTROL_SPACE_FORMAT!r}) and is not supported. It declared its own kinds "
            f"and ranges, which the target now owns, so there is no faithful way to read "
            f"it forward — reinterpreting it would put invented semantics on archived "
            f"data. Re-record with this version, or read the archive with the version "
            f"that wrote it."
        )
    raise ValueError(
        f"unknown control-space format {fmt!r}; this version writes and reads "
        f"{CONTROL_SPACE_FORMAT!r}."
    )


__all__ = [
    "CONTROL_SPACE_FORMAT",
    "read_control_space",
    "Binding",
    "Capability",
    "ControlMap",
    "TargetRef",
    "load_control_map",
    "resolve",
]
