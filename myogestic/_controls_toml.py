"""Parse and validate a control configuration mapping into typed DOFs.

Private helper for `myogestic.controls.load_dofs`. Everything here is pure: it
takes a plain `Mapping` (typically from ``tomllib.loads``) and returns typed
objects or a list of human-readable faults. It never touches the filesystem, so
`tomllib` stays out of the library.

Every fault is **accumulated** and reported once, because three typos should cost
one edit round-trip rather than three runs. Message shape is
``<what> <where>: <problem>. <what to write>`` — the voice of
`myogestic.outputs.filters.make_filter` ("Choose: ...").
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

#: A canonical control name: dotted lowercase segments. Segment 1 is what is
#: controlled (``hand``, ``wrist``, ``cursor``), segment 2+ is the function.
#: Deliberately a grammar and not a closed vocabulary — a fixed list would be a
#: registry, and would gate new targets on a library release.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")

#: Keys accepted inside an escalated (inline-table) DOF value.
_DOF_KEYS = frozenset({"kind", "range", "rest", "states", "debounce_s", "label"})

_KINDS = ("continuous", "discrete")


def check_name(name: str, errs: list[str]) -> bool:
    """Append a fault unless ``name`` matches the canonical grammar."""
    if _NAME_RE.match(name):
        return True
    errs.append(
        f"[dofs] {name!r}: not a canonical control name. Use dotted lowercase "
        f'segments, e.g. "index.flexion" — what is controlled, then the function.'
    )
    return False


def normalise_value(name: str, value: Any, errs: list[str]) -> dict[str, Any] | None:
    """Turn one ``[dofs]`` value into a keyword mapping, or record why it cannot.

    Three value shapes are legal, dispatched on TOML type:

    - a string — the kind, all defaults (``"index.flexion" = "continuous"``)
    - an array of strings — a discrete DOF's states, ``[0]`` the rest state
    - an inline table — any of `_DOF_KEYS`

    The three rejected shapes below are the ones TOML accepts happily but that
    mean something the author did not intend; each gets a named error rather than
    a surprising DOF.
    """
    if isinstance(value, str):
        if value not in _KINDS:
            errs.append(
                f"[dofs] {name!r}: unknown kind {value!r}. Choose: "
                f"{', '.join(repr(k) for k in _KINDS)}."
            )
            return None
        return {"kind": value}

    if isinstance(value, list):
        # Hazard 1: `"grip.force" = [0.0, 1.0]` parses as a discrete DOF whose
        # states are two floats. Authors write this meaning a range, because that
        # literal *is* the escalation form for one.
        if any(not isinstance(s, str) for s in value):
            errs.append(
                f"[dofs] {name!r}: arrays declare discrete states, which must be "
                f'strings (got {value!r}). For a custom range write '
                f"{{ kind = \"continuous\", range = [lo, hi] }}."
            )
            return None
        return {"kind": "discrete", "states": value}

    if isinstance(value, Mapping):
        # Hazard 2: an unquoted dotted key (`hand.grip = "continuous"`) parses as
        # a nested table, which is structurally identical to the escalation form —
        # and it coexists with a quoted `"hand.grip"` without a duplicate-key
        # error, so one of the two DOFs would vanish silently.
        if not (set(value) & _DOF_KEYS):
            errs.append(
                f"[dofs] {name!r}: looks like an unquoted dotted key. Quote the "
                f'name — `"{name}.<something>" = "continuous"` — or, if this is an '
                f"escalated value, give it one of: {', '.join(sorted(_DOF_KEYS))}."
            )
            return None
        if unknown := sorted(set(value) - _DOF_KEYS):
            errs.append(
                f"[dofs] {name!r}: unknown key(s) {unknown}. Choose: "
                f"{', '.join(sorted(_DOF_KEYS))}."
            )
            return None
        return dict(value)

    errs.append(
        f"[dofs] {name!r}: a DOF is a kind string, an array of state names, or an "
        f"inline table (got {type(value).__name__})."
    )
    return None


def check_range(name: str, lo: float, hi: float, errs: list[str]) -> bool:
    """Validate a continuous domain: finite, ordered, and rest-expressible.

    Only ``[-h, h]``, ``[0, h]`` and ``[-h, 0]`` are accepted. A shape like
    ``[-0.6, 1.0]`` is rejected because it parks the neutral value off-centre —
    the value a DOF holds when the model says "nothing" must be representable.
    """
    if not (math.isfinite(lo) and math.isfinite(hi)):
        errs.append(f"[dofs] {name!r}: range must be finite (got [{lo}, {hi}]).")
        return False
    if lo >= hi:
        errs.append(
            f"[dofs] {name!r}: range must be increasing (got [{lo}, {hi}]). "
            f"Write range = [{min(lo, hi)}, {max(lo, hi)}]."
        )
        return False
    if not (lo == -hi or lo == 0.0 or hi == 0.0):
        errs.append(
            f"[dofs] {name!r}: range [{lo}, {hi}] cannot hold a neutral value. "
            f"Use a signed range [-h, h], or a one-way range [0, h] / [-h, 0]."
        )
        return False
    return True


def check_states(name: str, states: Any, errs: list[str]) -> tuple[str, ...] | None:
    """Validate a discrete DOF's state list and return it."""
    if not isinstance(states, (list, tuple)) or any(not isinstance(s, str) for s in states):
        errs.append(f"[dofs] {name!r}: states must be a list of strings (got {states!r}).")
        return None
    if len(states) < 2:
        errs.append(
            f"[dofs] {name!r}: a discrete DOF needs at least two states, e.g. "
            f'states = ["rest", "active"] (got {list(states)}).'
        )
        return None
    if len(set(states)) != len(states):
        errs.append(f"[dofs] {name!r}: duplicate states in {list(states)}.")
        return None
    # Hazard 3: the array form silently makes element 0 the rest state, so a list
    # that names `rest` later on means the opposite of what it reads like.
    if "rest" in states[1:]:
        errs.append(
            f"[dofs] {name!r}: 'rest' appears at index {states.index('rest')}, but the "
            f"first state is the neutral one. Put 'rest' first, or name the neutral "
            f"state explicitly with rest = \"...\"."
        )
        return None
    return tuple(states)


def check_simultaneous(
    block: Any, known: frozenset[str], errs: list[str]
) -> dict[str, tuple[str, ...]]:
    """Validate ``[simultaneous]``: control name -> the DOFs it commands.

    Absent or empty is legal and means **zero** declared controls (a monitor- or
    record-only session). It is never read as "every DOF is live" — inferring that
    would make adding a DOF silently change what the session claims to control.
    """
    if block is None:
        return {}
    if not isinstance(block, Mapping):
        errs.append(
            "[simultaneous]: must be a table of control name -> list of DOF names, "
            'e.g. proportional = ["index.flexion", "thumb.flexion"].'
        )
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for control, names in block.items():
        if isinstance(names, str) or not isinstance(names, (list, tuple)):
            errs.append(
                f"[simultaneous] {control!r}: must be a list of DOF names, e.g. "
                f'{control} = ["index.flexion"].'
            )
            continue
        if not names:
            errs.append(
                f"[simultaneous] {control!r}: names no DOFs. List at least one, or "
                f"delete the line."
            )
            continue
        if unknown := [n for n in names if n not in known]:
            errs.append(
                f"[simultaneous] {control!r}: {unknown} are not declared DOFs. "
                f"Declared: {sorted(known)}."
            )
            continue
        if len(set(names)) != len(names):
            errs.append(f"[simultaneous] {control!r}: names a DOF twice ({list(names)}).")
            continue
        out[control] = tuple(names)
    return out
