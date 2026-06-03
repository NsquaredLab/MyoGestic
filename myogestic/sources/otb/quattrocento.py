"""QuattrocentoSource — native pure-Python source for the OTB Quattrocento.

PC is the TCP client to the amplifier (default 169.254.1.10:23456). Config is
a 40-byte CRC-8-terminated string; data is little-endian int16. See
docs/reference/otb/Read_Quattrocento.m.
"""
from __future__ import annotations

import socket

import numpy as np

from myogestic.sources.otb import _constants as C
from myogestic.sources.otb._base import _OTBSource
from myogestic.sources.otb._decode import decode_le_int16
from myogestic.stream import StreamInfo


class QuattrocentoSource(_OTBSource):
    """Connect to an OTB Quattrocento amplifier over TCP.

    Args:
        device_ip: Amplifier IP (default link-local 169.254.1.10). The host NIC
            must have a 169.254.x.x address on that segment.
        port: TCP port (default 23456).
        fs_mode: 0..3 -> 512 / 2048 / 5120 / 10240 Hz.
        nch_mode: 0..3 -> 120 / 216 / 312 / 408 streamed channels.
        n_bio: Number of biosignal channels to expose (the grid channels at the
            front of the stream). Defaults to all non-accessory channels.
        include_aux: Append the AUX IN + accessory channels (unscaled).
        connect_timeout: Seconds to wait for the TCP connect.
    """

    def __init__(
        self,
        device_ip: str = C.QUATTRO_IP,
        port: int = C.QUATTRO_PORT,
        *,
        fs_mode: int = 1,
        nch_mode: int = 1,
        n_bio: int | None = None,
        include_aux: bool = False,
        connect_timeout: float = 10.0,
    ) -> None:
        super().__init__()
        self._device_ip = device_ip
        self._port = port
        self._fs_mode = fs_mode
        self._nch_mode = nch_mode
        self._include_aux = include_aux
        self._connect_timeout = connect_timeout
        self._nch_total = C.QUATTRO_NCH_BY_MODE[nch_mode]
        # default: everything except the 8 accessory channels is "bio"
        self._n_bio = (
            n_bio if n_bio is not None else C.QUATTRO_BIO_BY_MODE[nch_mode]
        )

    # --- base hooks ---------------------------------------------------------
    def _open(self) -> StreamInfo:
        self._buf.clear()
        if self._sock is not None:  # don't leak a prior socket on reconnect
            try:
                self._sock.close()
            finally:
                self._sock = None
        sock = socket.create_connection(
            (self._device_ip, self._port), timeout=self._connect_timeout
        )
        sock.setblocking(False)
        self._sock = sock
        self._frame_nbytes = self._nch_total * 2  # int16, one sample-instant
        n_out = self._nch_total if self._include_aux else self._n_bio
        return StreamInfo(
            n_channels=n_out,
            fs=C.QUATTRO_FS_BY_MODE[self._fs_mode],
            dtype=np.dtype(np.float32),
            channel_names=C.quattro_channel_names(self._nch_total, self._n_bio)[:n_out],
        )

    def _send_start(self) -> None:
        cfg = C.quattro_config(fs_mode=self._fs_mode, nch_mode=self._nch_mode,
                               acq_on=True)
        self._sock.sendall(cfg)

    def _send_stop(self) -> None:
        cfg = C.quattro_config(fs_mode=self._fs_mode, nch_mode=self._nch_mode,
                               acq_on=False)
        self._sock.sendall(cfg)

    def _decode(self, frame: bytes) -> np.ndarray:
        full = decode_le_int16(frame, n_channels=self._nch_total)
        bio = full[:, : self._n_bio] * np.float32(C.QUATTRO_CONV_FACTOR_MV)
        if not self._include_aux:
            return bio
        # Layout after bio: 16 AUX IN (analog, scale to V), then 8 accessory
        # (counter/trigger/buffer/reserved — raw integers, no scaling).
        acc_start = self._nch_total - C.QUATTRO_N_ACCESSORY
        aux_in = full[:, self._n_bio : acc_start] * np.float32(C.QUATTRO_AUX_FACTOR_V)
        accessory = full[:, acc_start:]
        return np.concatenate([bio, aux_in, accessory], axis=1).astype(np.float32)
