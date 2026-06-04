"""Output sinks — the send-side of myogestic.

An :class:`Output` is the counterpart to a ``Source``: push prediction-control
vectors out to a downstream consumer. The base class lives in
:mod:`myogestic.outputs.base`; concrete sinks are :class:`LSLOutlet` (LSL) and
:class:`UDPOutput` (UDP datagrams).
"""

from myogestic.outputs.base import Output
from myogestic.outputs.lsl import LSLOutlet
from myogestic.outputs.udp import UDPOutput

__all__ = ["Output", "LSLOutlet", "UDPOutput"]

# `SerialOutput` is opt-in. Import it directly when you have pyserial:
#     from myogestic.outputs.serial_output import SerialOutput
