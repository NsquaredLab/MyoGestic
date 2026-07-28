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

Then drive targets through a `ControlBus`, which owns the sanitise ordering::

    bus = ControlBus(controls, targets=[my_target], hz=pipeline.predict_hz)
    app.cleanup_hooks.append(lambda _app: bus.stop())

    @pipeline.predict
    def predict(model, features):
        return bus.push({"index.flexion": float(model.predict(features)[0])})

This module is the public entry point; the implementation lives in
``_controls_core`` (model, loader, transforms) and ``_controls_bus`` (the bus),
split so neither imports its own aggregator.
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
    load_dofs,
    substitute_rest,
)
from myogestic._controls_map import (
    Binding,
    Capability,
    ControlMap,
    TargetRef,
    load_control_map,
    resolve,
)

__all__ = [
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
    "encode",
    "load_control_map",
    "load_dofs",
    "resolve",
    "substitute_rest",
]
