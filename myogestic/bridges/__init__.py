"""Bridges — supervised companion subprocesses for heavy / out-of-band capture.

A [`Bridge`][] is a subprocess MyoGestic spawns alongside the app and tears
down on exit (a webcam decoder, an ultrasound daemon, a custom capture script).
It doesn't fit the pull-based ``Source`` model; instead it owns its own buffer
and feeds data back the same way every source does — by publishing an LSL outlet
(or writing a Zarr file the app reads). Register with ``app.bridges(...)``.
"""

from myogestic.bridges.base import Bridge
from myogestic.bridges.custom import CustomBridge
from myogestic.bridges.webcam import WebCamBridge

__all__ = ["Bridge", "CustomBridge", "WebCamBridge"]
