"""Output sinks — the send-side of myogestic.

An [`Output`][] is the counterpart to a ``Source``: push prediction-control
vectors out to a downstream consumer. The base class lives in
[`myogestic.outputs.base`][]; concrete sinks are [`LSLOutlet`][] (LSL) and
[`UDPOutput`][] (UDP datagrams).

Output-side smoothing filters (applied to the prediction-output vector *before*
it leaves the app) live in [`myogestic.outputs.filters`][] and are re-exported
here: [`OneEuroFilter`][], [`GaussianFilter`][], [`IdentityFilter`][],
the [`VectorFilter`][] protocol, and the [`make_filter`][] factory.

For *discrete* event outputs (fire a side effect only when a prediction
changes), [`EdgeTrigger`][] lives in [`myogestic.outputs.edge_trigger`][]
and is re-exported here too.
"""

from myogestic.outputs.base import Output
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
from myogestic.outputs.udp import UDPOutput

__all__ = [
    "Output",
    "LSLOutlet",
    "UDPOutput",
    "VectorFilter",
    "IdentityFilter",
    "GaussianFilter",
    "OneEuroFilter",
    "chain",
    "make_filter",
    "EdgeTrigger",
]

# `SerialOutput` is opt-in. Import it directly when you have pyserial:
#     from myogestic.outputs.serial_output import SerialOutput
