"""QuattrocentoSource — native pure-Python source for the OTB Quattrocento.

PC is the TCP client to the amplifier (default 169.254.1.10:23456). Config is
a 40-byte CRC-8-terminated string; data is little-endian int16. See
docs/reference/otb/Read_Quattrocento.m.
"""
from __future__ import annotations

import socket
from collections.abc import Sequence

import numpy as np

from myogestic.sources.otb import _constants as C
from myogestic.sources.otb._base import _OTBSource
from myogestic.sources.otb._decode import decode_le_int16
from myogestic.stream import StreamInfo


class QuattrocentoSource(_OTBSource):
    """Connect to an OTB Quattrocento amplifier over TCP.

    The device always streams a fixed number of channels per sample-instant
    (``120/216/312/408`` by ``nch_mode``), laid out as ``[bio | 16 AUX IN | 8
    accessory]``. Scaling is applied by that **wire** layout — bio in mV, AUX IN
    in V, accessory raw — and only then are the requested output channels
    selected. This keeps host-side channel selection independent of the wire's
    bio/AUX boundary, so asking for fewer channels never mis-scales them.

    Args:
        device_ip: Amplifier IP (default link-local 169.254.1.10). The host NIC
            must have a 169.254.x.x address on that segment.
        port: TCP port (default 23456).
        fs_mode: 0..3 -> 512 / 2048 / 5120 / 10240 Hz.
        nch_mode: 0..3 -> 120 / 216 / 312 / 408 streamed channels.
        select: Output channel indices into the fully-scaled wire array
            ``[0, nch_total)``. Default: all biosignal channels (or the whole
            wire when ``include_aux``). Pass e.g. ``range(16)`` to expose the
            first 16 biosignal channels correctly scaled in mV.
        include_aux: When ``select`` is None, expose the whole wire (bio + AUX IN
            + accessory) instead of biosignal-only.
        detection: 'monopolar' | 'differential' | 'bipolar' (per-input CONF2).
        hpf: High-pass filter cutoff in Hz — one of 0.7, 10, 100, 200.
        lpf: Low-pass filter cutoff in Hz — one of 130, 500, 900, 4400.
        connect_timeout: Seconds to wait for the TCP connect.
    """

    def __init__(
        self,
        device_ip: str = C.QUATTRO_IP,
        port: int = C.QUATTRO_PORT,
        *,
        fs_mode: int = 1,
        nch_mode: int = 1,
        select: Sequence[int] | None = None,
        include_aux: bool = False,
        detection: str = "monopolar",
        hpf: float = 10,
        lpf: float = 500,
        connect_timeout: float = 10.0,
    ) -> None:
        super().__init__()
        self._device_ip = device_ip
        self._port = port
        self._fs_mode = fs_mode
        self._nch_mode = nch_mode
        self._include_aux = include_aux
        self._connect_timeout = connect_timeout
        self._detection = detection
        self._hpf = hpf
        self._lpf = lpf
        self._conf2 = C.quattro_conf2(detection=detection, hpf=hpf, lpf=lpf)
        self._nch_total = C.QUATTRO_NCH_BY_MODE[nch_mode]
        # Fixed by nch_mode: the bio/AUX boundary used for SCALING (never the
        # output width). bio = [0, wire_bio); AUX IN = [wire_bio, nch_total-8);
        # accessory = last 8.
        self._wire_bio = C.QUATTRO_BIO_BY_MODE[nch_mode]
        # Output channel selection (applied AFTER scaling).
        if select is not None:
            sel = list(select)
        elif include_aux:
            sel = list(range(self._nch_total))
        else:
            sel = list(range(self._wire_bio))
        if sel and (min(sel) < 0 or max(sel) >= self._nch_total):
            raise ValueError(
                f"select indices must be in [0, {self._nch_total}) for nch_mode="
                f"{nch_mode}; got min={min(sel)}, max={max(sel)}."
            )
        self._select = sel

    # --- base hooks ---------------------------------------------------------
    def _apply_target(self, target: str) -> None:
        self._device_ip = target

    def _open(self) -> StreamInfo:
        self._prepare_stream()
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
        names = C.quattro_channel_names(self._nch_total, self._wire_bio)
        return StreamInfo(
            n_channels=len(self._select),
            fs=C.QUATTRO_FS_BY_MODE[self._fs_mode],
            dtype=np.dtype(np.float32),
            channel_names=[names[i] for i in self._select],
        )

    def _send_start(self) -> None:
        assert self._sock is not None
        cfg = C.quattro_config(fs_mode=self._fs_mode, nch_mode=self._nch_mode,
                               acq_on=True, conf2=self._conf2)
        self._sock.sendall(cfg)

    def _send_stop(self) -> None:
        assert self._sock is not None
        cfg = C.quattro_config(fs_mode=self._fs_mode, nch_mode=self._nch_mode,
                               acq_on=False, conf2=self._conf2)
        self._sock.sendall(cfg)

    def _decode(self, frame: bytes) -> np.ndarray:
        full = decode_le_int16(frame, n_channels=self._nch_total)
        scaled = self._scale_wire(full)
        return np.ascontiguousarray(scaled[:, self._select], dtype=np.float32)

    def _scale_wire(self, full: np.ndarray) -> np.ndarray:
        """Scale by the WIRE layout: bio -> mV, AUX IN -> V, accessory raw.

        ``full`` is (n_samples, nch_total). Scaling is independent of ``select``
        so any later index picks a correctly-scaled channel.
        """
        acc_start = self._nch_total - C.QUATTRO_N_ACCESSORY
        out = np.array(full, dtype=np.float32)  # writable copy
        out[:, : self._wire_bio] *= np.float32(C.QUATTRO_CONV_FACTOR_MV)
        out[:, self._wire_bio : acc_start] *= np.float32(C.QUATTRO_AUX_FACTOR_V)
        # accessory (counter/trigger/buffer/reserved) stays raw
        return out

    # --- provenance ---------------------------------------------------------
    def config_dict(self) -> dict:
        """Resolved acquisition settings + exact wire packet, for provenance.

        Everything a downstream recorder needs to reproduce/audit the capture:
        the settings, the scaling factors, and the exact 40-byte start packet.
        """
        return {
            "device": "quattrocento",
            "device_ip": self._device_ip,
            "port": self._port,
            "fs_hz": C.QUATTRO_FS_BY_MODE[self._fs_mode],
            "fs_mode": self._fs_mode,
            "nch_mode": self._nch_mode,
            "nch_wire_total": self._nch_total,
            "wire_bio": self._wire_bio,
            "select": list(self._select),
            "include_aux": self._include_aux,
            "detection": self._detection,
            "hpf_hz": self._hpf,
            "lpf_hz": self._lpf,
            "conf2_byte": self._conf2,
            "conv_factor_mv": float(C.QUATTRO_CONV_FACTOR_MV),
            "aux_factor_v": float(C.QUATTRO_AUX_FACTOR_V),
            "start_packet_hex": C.quattro_config(
                fs_mode=self._fs_mode, nch_mode=self._nch_mode,
                acq_on=True, conf2=self._conf2,
            ).hex(),
        }
