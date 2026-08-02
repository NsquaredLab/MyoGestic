"""Output sinks — the send-side of myogestic.

An [`Outlet`][] is the counterpart to a ``Source``: push a vector out to a
downstream consumer at a steady rate. The one shipped outlet is
[`LSLOutlet`][].

An outlet is a *paced sender*, not a way to drive a device. It takes an array,
paces one wire, and has no aliases, no declared range and no rest on shutdown.
Anything that **moves** is a [`myogestic.controls.Target`][], which is where a
control map's declared ranges, clamping and rest-on-teardown live. A target may
write *through* an outlet — [`myogestic.remote.RemoteTarget`][] builds one
[`LSLOutlet`][] per control it drives.

Output-side smoothing filters (applied to the prediction-output vector *before*
it leaves the app) live in [`myogestic.outputs.filters`][] and are re-exported
here: [`OneEuroFilter`][], [`GaussianFilter`][], [`IdentityFilter`][],
the [`VectorFilter`][] protocol, and the [`make_filter`][] factory.

For *discrete* event outputs (fire a side effect only when a prediction
changes), [`EdgeTrigger`][] lives in [`myogestic.outputs.edge_trigger`][]
and is re-exported here too.
"""

from myogestic.outputs.edge_trigger import EdgeTrigger
from myogestic.outputs.filters import (
    GaussianFilter,
    IdentityFilter,
    OneEuroFilter,
    VectorFilter,
    chain,
    make_filter,
)
from myogestic.outputs.lsl import LSLOutlet
from myogestic.outputs.outlet import Outlet

__all__ = [
    "Outlet",
    "LSLOutlet",
    "VectorFilter",
    "IdentityFilter",
    "GaussianFilter",
    "OneEuroFilter",
    "chain",
    "make_filter",
    "EdgeTrigger",
]
