"""Serial-port output — writes packed binary frames of the latest vector."""

from __future__ import annotations

import struct

import numpy as np

from myogestic.outputs.base import Output


class SerialOutput(Output):
    """Pack the latest vector with `struct` and write it to a serial port.

    Each ``_send`` writes one little-endian packed frame: ``len(data)``
    values of format-char ``fmt``. No framing byte, no checksum - the
    receiver (an Arduino, a microcontroller, a haptic driver) is
    expected to read a fixed-size frame matching its known channel
    count.

    Parameters
    ----------
    port
        Serial port path. Examples: ``"/dev/cu.usbmodem1101"``
        on macOS, ``"/dev/ttyACM0"`` on Linux, ``"COM3"`` on
        Windows.
    baud
        Baud rate. Default 115200 - matches typical Arduino
        sketches; tune to your firmware.
    hz
        Send rate of the daemon thread (Hz). Default 10. Keep this
        low: serial UART has a hard ceiling and queue-induced
        latency stacks fast.
    fmt
        `struct` format character per value. ``"f"`` for float32
        (default), ``"B"`` for uint8, ``"h"`` for int16, etc. See
        the Python `struct` docs.

    Examples
    --------
    >>> haptic = SerialOutput("/dev/ttyACM0", baud=115200, hz=30,
    ...                       fmt="B")
    >>> @pipeline.predict
    ... def predict(model, features):
    ...     intensities = (model.predict(features.reshape(1, -1))[0] * 255
    ...                    ).clip(0, 255).astype(np.uint8)
    ...     haptic.push(intensities)
    ...     return {"intensities": intensities}

    Requires the ``serial`` extra (``uv sync --extra serial``) to pull
    in ``pyserial``.
    """

    def __init__(self, port: str, baud: int = 115200, hz: float = 10, fmt: str = "f"):
        import serial  # type: ignore

        self._ser = serial.Serial(port, baud)
        self._fmt = fmt
        super().__init__(hz=hz)

    def _send(self, data: np.ndarray) -> None:
        packed = struct.pack(f"<{len(data)}{self._fmt}", *data.flat)
        self._ser.write(packed)
