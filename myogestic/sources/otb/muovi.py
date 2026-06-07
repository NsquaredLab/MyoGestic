"""MuoviSource — native pure-Python source for OTB Muovi / Muovi+.

PC is the TCP server on port 54321; the probe connects in as client (in AP
mode the probe is the WiFi access point and DHCP-assigns the PC). Big-endian
int16 (EMG) / int24 (EEG); see docs/reference/otb/Read_muovi.m.
"""
from __future__ import annotations

import socket

import numpy as np

from myogestic.sources.otb import _constants as C
from myogestic.sources.otb._base import _OTBSource
from myogestic.sources.otb._decode import decode_be_int16, decode_be_int24
from myogestic.stream import StreamInfo


class MuoviSource(_OTBSource):
    """Connect to an OTB Muovi / Muovi+ probe over TCP.

    Args:
        host_ip: Local interface to bind the server socket. ``""`` binds all.
        port: TCP port to listen on (default 54321). ``0`` picks a free port
            (used in tests).
        plus: ``True`` for Muovi+ (64 bio channels), ``False`` for Muovi (32).
        emg: ``True`` = EMG (2000 Hz, 16-bit), ``False`` = EEG (500 Hz, 24-bit).
        mode: Detection mode 0..3. ``0`` = monopolar gain 8 (default; the only
            unambiguous mode across firmware). Avoid mode 1 (firmware-dependent).
        include_aux: Append the 6 aux channels (IMU/buffer/counter) unscaled.
        accept_timeout: Seconds to wait for the probe to dial in.
    """

    def __init__(
        self,
        host_ip: str = "",
        port: int = C.MUOVI_PORT,
        *,
        plus: bool = False,
        emg: bool = True,
        mode: int = 0,
        include_aux: bool = False,
        accept_timeout: float = 30.0,
    ) -> None:
        super().__init__()
        self._host_ip = host_ip
        self._port = port
        self._plus = plus
        self._emg = emg
        self._mode = mode
        self._include_aux = include_aux
        self._accept_timeout = accept_timeout
        self._server: socket.socket | None = None
        self._geo = C.muovi_geometry(plus=plus, emg=emg, mode=mode)

    # --- normal entry point -------------------------------------------------
    def connect(self) -> StreamInfo:
        """Bind+listen, accept the probe, send the start command."""
        self.connect_listen()
        return self.accept_and_start()

    # --- split entry points (also used by tests) ----------------------------
    def connect_listen(self) -> None:
        """Bind and listen; returns immediately (does not block on accept)."""
        if self._server is not None:  # don't leak a prior server on re-listen
            try:
                self._server.close()
            finally:
                self._server = None
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self._host_ip, self._port))
        self._server.listen(1)

    def accept_and_start(self) -> StreamInfo:
        """Block until the probe connects, then open + send the start command.

        Runs the base lifecycle inline (NOT via base ``connect()``) because the
        server socket / accept is Muovi-specific.
        """
        assert self._server is not None, "call connect_listen() before accept_and_start()"
        self._server.settimeout(self._accept_timeout)
        conn, _addr = self._server.accept()
        conn.setblocking(False)
        self._sock = conn
        info = self._open()
        self._info = info
        try:
            self._send_start()
        except Exception:
            self.disconnect()  # don't leak the accepted socket on a failed start
            raise
        return info

    # --- base hooks ---------------------------------------------------------
    def _open(self) -> StreamInfo:
        self._buf.clear()
        n_out = self._geo.n_total if self._include_aux else self._geo.n_bio
        self._frame_nbytes = self._geo.n_total * self._geo.bytes_per_sample
        return StreamInfo(
            n_channels=n_out,
            fs=self._geo.fs,
            dtype=np.dtype(np.float32),
            channel_names=C.muovi_channel_names(self._geo)[:n_out],
        )

    def _send_start(self) -> None:
        assert self._sock is not None
        cmd = C.muovi_control_byte(emg=self._emg, mode=self._mode, go=True)
        self._sock.sendall(bytes([cmd]))

    def _send_stop(self) -> None:
        assert self._sock is not None
        cmd = C.muovi_control_byte(emg=self._emg, mode=self._mode, go=False)
        self._sock.sendall(bytes([cmd]))

    def _decode(self, frame: bytes) -> np.ndarray:
        if self._geo.bytes_per_sample == 2:
            full = decode_be_int16(frame, n_channels=self._geo.n_total)
        else:
            full = decode_be_int24(frame, n_channels=self._geo.n_total)
        bio = full[:, : self._geo.n_bio] * np.float32(C.MUOVI_CONV_FACTOR_MV)
        if not self._include_aux:
            return bio
        aux = full[:, self._geo.n_bio :]  # unscaled IMU/buffer/counter
        return np.concatenate([bio, aux], axis=1).astype(np.float32)

    def disconnect(self) -> None:
        """Stop streaming and close the device + listening sockets."""
        super().disconnect()
        if self._server is not None:
            try:
                self._server.close()
            finally:
                self._server = None
