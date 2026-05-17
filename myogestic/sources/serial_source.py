from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import numpy as np
from mne_lsl.lsl import local_clock

from myogestic.stream import StreamInfo

if TYPE_CHECKING:
    import serial  # type: ignore[import-not-found]


class SerialSource:
    """Reads fixed-width binary frames from a serial port.

    Each frame is n_channels float32 values (little-endian).
    The source self-paces via serial blocking reads; timestamps
    are stamped on arrival with mne_lsl.lsl.local_clock().
    """

    def __init__(self, port: str, baud: int, n_channels: int, fs: float):
        self._port = port
        self._baud = baud
        self._n_channels = n_channels
        self._fs = fs
        self._ser: serial.Serial | None = None
        self._frame_bytes = n_channels * 4  # float32 = 4 bytes

    def connect(self) -> StreamInfo:
        import serial  # type: ignore[import-not-found]

        self._ser = serial.Serial(self._port, self._baud, timeout=1.0)
        return StreamInfo(
            n_channels=self._n_channels,
            fs=self._fs,
            dtype=np.dtype(np.float32),
        )

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        if self._ser is None:
            return None, None
        raw = self._ser.read(self._frame_bytes)
        if len(raw) < self._frame_bytes:
            return None, None
        values = struct.unpack(f"<{self._n_channels}f", raw)
        data = np.array([values], dtype=np.float32)
        ts = np.array([local_clock()], dtype=np.float64)
        return data, ts

    def disconnect(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def discover(self) -> list[dict[str, str]]:
        """List available serial ports."""
        import serial.tools.list_ports  # type: ignore[import-not-found]

        return [
            {"name": p.device, "info": p.description or p.device}
            for p in serial.tools.list_ports.comports()
        ]

    def reconnect(self, target: str | None = None) -> StreamInfo:
        """Reconnect to the same or a different serial port."""
        self.disconnect()
        if target is not None:
            self._port = target
        return self.connect()
