from __future__ import annotations

import socket

import numpy as np

from myogestic.outputs import Output


class UDPOutput(Output):
    """Send the latest pushed vector as a UDP datagram to ``host:port``.

    Each ``_send`` writes one datagram containing the float32 bytes of
    ``data`` (no length header, no framing). The receiver is expected
    to know the channel count and dtype out-of-band - this is for cases
    where a downstream process (Unity, ROS, a Max/MSP patch) has its
    own decoder and you just want the freshest vector with minimal
    latency.

    Parameters
    ----------
    host
        Destination hostname or IP. ``"127.0.0.1"`` for
        same-machine consumers; a LAN address for the next box over.
    port
        Destination UDP port.
    hz
        Send rate of the daemon thread (Hz). Default 50.

    Examples
    --------
    >>> outlet = UDPOutput("127.0.0.1", 9000, hz=60)
    >>> @pipeline.predict
    ... def predict(model, features):
    ...     vec = model.predict(features.reshape(1, -1))[0]
    ...     outlet.push(vec)
    ...     return {"vec": vec}
    """

    def __init__(self, host: str, port: int, hz: float = 50):
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        super().__init__(hz=hz)

    def _send(self, data: np.ndarray) -> None:
        buf = data.astype(np.float32).tobytes()
        self._sock.sendto(buf, self._addr)

    def stop(self) -> None:
        """Stop the daemon thread and close the UDP socket."""
        super().stop()
        self._sock.close()
