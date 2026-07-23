"""The unstructured bridge escape hatch: run any user script as a subprocess."""

from __future__ import annotations

import sys

from myogestic.bridges.base import Bridge


class CustomBridge(Bridge):
    """Bridge that runs an arbitrary user Python script as a subprocess.

    The unstructured escape hatch: when the heavy-data source you want
    doesn't fit [`WebCamBridge`][myogestic.bridges.webcam.WebCamBridge] and you'd
    rather write the decoder yourself than subclass [`Bridge`][]. The
    script runs with the same Python interpreter as the app
    (``sys.executable``); the rest is up to you (publish LSL, write
    Zarr, talk to a custom message bus, ...).

    Parameters
    ----------
    name
        Bridge label.
    script
        Path to the Python script to spawn (e.g.
        ``"capture/ultrasound.py"``).

    Examples
    --------
    >>> from myogestic.bridges import CustomBridge
    >>> bridge = CustomBridge("ultrasound", "capture/ultrasound.py")
    >>> bridge.start()
    >>> bridge.stop()
    """

    def __init__(self, name: str, script: str):
        super().__init__(
            name=name,
            command=[sys.executable, script],
        )
