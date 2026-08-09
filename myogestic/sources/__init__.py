"""Built-in data sources (LSL, replay, synthetic, target, serial) that feed a [`Stream`][myogestic.stream.Stream]."""

from myogestic.sources.force import SyntheticForceSource
from myogestic.sources.lsl import LSLSource
from myogestic.sources.replay import ReplaySource
from myogestic.sources.synthetic import SyntheticSource
from myogestic.sources.target import TargetSource

__all__ = [
    "LSLSource",
    "ReplaySource",
    "SyntheticForceSource",
    "SyntheticSource",
    "TargetSource",
]

# `SerialSource` is opt-in. Import it directly when you have pyserial:
#     from myogestic.sources.serial_source import SerialSource
