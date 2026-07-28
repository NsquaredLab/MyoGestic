"""The canonical control standard — named DOFs, independent of any application.

MyoGestic defines the vocabulary; VHI, a keyboard, a cursor or a robotic hand are
*targets* that render some of it. Nothing in this standard knows what any of them
are: there is no channel index, no pose vector, no movement name, no transport.

Three ideas, and that is the whole standard:

- a **DOF** is one named thing a user controls — `Continuous` or `Discrete`;
- a **control** is one entry in ``[simultaneous]``, over one or more DOFs;
- a **target** renders some DOFs — see `Target`, and `ControlBus` to drive them.

Continuous DOFs are **signed and normalized**: ``[-1, 1]`` with ``0`` at rest, so
a wrist or cursor axis has both directions without anyone configuring one. A name
denotes its ``+1`` direction — ``index.flexion`` is flexion at ``+1`` and
extension at ``-1``. One-way controls declare ``range = [0.0, 1.0]``; that is the
exceptional case, not the default. A target owns its own units: pixels per second
belongs to a cursor target, degrees to a renderer, never here.

Declare your control space in a **file**, and load it in two lines::

    import tomllib
    from myogestic.controls import load_control_map, resolve

    with open("hand.toml", "rb") as f:          # "rb" — tomllib requires binary
        control_map = load_control_map(tomllib.load(f))

    controls = resolve(control_map, target.capabilities())

`load_control_map` takes a plain `Mapping`, never a path, so ``tomllib`` stays out of the
library and the same call accepts JSON, a dict literal, or a config system you already
run. `resolve` is where meaning arrives: the *target* declares whether each address is a
number or a held state, its range, and its states — nothing here decides that.

"""

from __future__ import annotations

from myogestic._controls_bus import ControlBus, Target
from myogestic._controls_core import (
    STANDARD_VERSION,
    Continuous,
    ControlSet,
    Discrete,
    Dof,
    clip,
    decode,
    encode,
    substitute_rest,
)
from myogestic._controls_map import (
    CONTROL_SPACE_FORMAT,
    Binding,
    Capability,
    ControlMap,
    TargetRef,
    dump_control_map,
    load_control_map,
    read_control_space,
    resolve,
)

__all__ = [
    "CONTROL_SPACE_FORMAT",
    "STANDARD_VERSION",
    "Binding",
    "Capability",
    "Continuous",
    "ControlMap",
    "ControlBus",
    "ControlSet",
    "Discrete",
    "Dof",
    "Target",
    "TargetRef",
    "clip",
    "decode",
    "dump_control_map",
    "encode",
    "load_control_map",
    "read_control_space",
    "resolve",
    "substitute_rest",
]
