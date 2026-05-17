from myogestic.sources.lsl import LSLSource
from myogestic.sources.replay import ReplaySource

__all__ = ["LSLSource", "ReplaySource"]

# `SerialSource` is opt-in. Import it directly when you have pyserial:
#     from myogestic.sources.serial_source import SerialSource
