"""Output sinks — the send-side of myogestic.

An :class:`Output` is the counterpart to a ``Source``: push prediction-control
vectors out to a downstream consumer. The base class lives in
:mod:`myogestic.outputs.base`; concrete sinks are :class:`LSLOutlet` (LSL) and
:class:`UDPOutput` (UDP datagrams).

Output-side smoothing filters (applied to the prediction-output vector *before*
it leaves the app) live in :mod:`myogestic.outputs.filters` and are re-exported
here: :class:`OneEuroFilter`, :class:`GaussianFilter`, :class:`IdentityFilter`,
the :class:`VectorFilter` protocol, and the :func:`make_filter` factory.
"""

from myogestic.outputs.base import Output
from myogestic.outputs.filters import (
    GaussianFilter,
    IdentityFilter,
    OneEuroFilter,
    VectorFilter,
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
    "make_filter",
]

# `SerialOutput` is opt-in. Import it directly when you have pyserial:
#     from myogestic.outputs.serial_output import SerialOutput
