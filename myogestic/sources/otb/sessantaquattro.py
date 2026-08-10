"""SessantaquattroSource — native pure-Python source for OTB Sessantaquattro(+).

PC is the TCP server on port 45454; the device connects in as client (in AP
mode the device is the access point and DHCP-assigns the PC, otherwise its
"Server IP address" web-page field must point at the PC). Big-endian int16
(16-bit) / int24 (24-bit); see docs/reference/otb/README.md.

The accessory-channel count is probed, not configured: the protocol documents
say "2 AUX + 2 accessory" but a Sessantaquattro+ sends eight. A wrong count
does not fail, it silently de-interleaves, so the width is recovered from the
ramp counter in the last channel.
"""
from __future__ import annotations

import logging
import socket
import time

import numpy as np

from myogestic.sources.otb import _constants as C
from myogestic.sources.otb._base import _OTBSource
from myogestic.sources.otb._decode import decode_be_int16, decode_be_int24
from myogestic.stream import StreamInfo

_log = logging.getLogger(__name__)

_COUNTER_WRAP = 1 << 16
#: How long to wait for the probe's worth of samples before giving up. The device
#: streams the moment GO=1 lands, so this only trips if it went quiet.
_PROBE_TIMEOUT_S = 5.0

_PROBE_SAMPLES = 32  # a wrong width scrambles the counter within a few samples


class SessantaquattroSource(_OTBSource):
    """Connect to an OTB Sessantaquattro / Sessantaquattro+ over TCP.

    Args:
        host_ip: Local interface to bind the server socket. ``""`` binds all.
        port: TCP port to listen on (default 45454). ``0`` picks a free port
            (used in tests).
        nch_mode: NCH 0..3 -> 8/16/32/64 bioelectrical channels.
        fs_mode: FSAMP 0..3 -> 500/1000/2000/4000 Hz (x4 in accelerometer mode).
        mode: Detection mode; one of ``monopolar``, ``bipolar``,
            ``differential``, ``accelerometer``, ``impedance``,
            ``impedance_advanced``, ``test``. Only ``bipolar`` halves the
            channel count; ``accelerometer`` pins it to 8.
        high_res: ``True`` = 24-bit samples, ``False`` = 16-bit.
        hpf: Enable the device's exponential-moving-average high-pass
            (cut-off = fs/190).
        gain: GAIN code 0..3. Note code 0 means preamp gain 8 at 16-bit but
            gain 2 at 24-bit, so its LSB is 286.1 nV either way.
        include_aux: Append the accessory channels (AUX, quaternion,
            buffer/trigger, counter) unscaled.
        accept_timeout: Seconds to wait for the device to dial in.

    Attributes
    ----------
        dropped_samples: Samples the device produced that never arrived,
            counted from the ramp counter.
        dropout_events: Number of distinct gaps making up ``dropped_samples``.
    """

    def __init__(
        self,
        host_ip: str = "",
        port: int = C.SESSANTAQUATTRO_PORT,
        *,
        nch_mode: int = 3,
        fs_mode: int = 2,
        mode: str = "monopolar",
        high_res: bool = False,
        hpf: bool = True,
        gain: int = 0,
        include_aux: bool = False,
        accept_timeout: float = 30.0,
    ) -> None:
        super().__init__()
        if nch_mode not in C.SESSANTAQUATTRO_BIO_BY_NCH:
            raise ValueError(f"nch_mode must be 0..3, got {nch_mode!r}")
        if fs_mode not in C.SESSANTAQUATTRO_FS_BY_MODE:
            raise ValueError(f"fs_mode must be 0..3, got {fs_mode!r}")
        if mode not in C.SESSANTAQUATTRO_MODE_CODE:
            raise ValueError(
                f"mode must be one of {sorted(C.SESSANTAQUATTRO_MODE_CODE)}, got {mode!r}"
            )
        self._host_ip = host_ip
        self._port = port
        self._nch_mode = nch_mode
        self._fs_mode = fs_mode
        self._mode = mode
        self._high_res = high_res
        self._hpf = hpf
        self._gain = gain
        self._include_aux = include_aux
        self._accept_timeout = accept_timeout
        self._server: socket.socket | None = None
        self._geo: C.SessantaquattroGeometry | None = None
        self.dropped_samples = 0
        self.dropout_events = 0
        self._last_counter: int | None = None
        self._warned_dropout = False
        self._identified = False
        self._probe_nbytes = 0

    # --- normal entry point -------------------------------------------------
    def connect(self) -> StreamInfo:
        """Bind+listen, accept the device, send the start command."""
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
        """Block until the device connects, then open + send the start command.

        Runs the base lifecycle inline (NOT via base ``connect()``) because the
        server socket / accept is Sessantaquattro-specific.
        """
        assert self._server is not None, "call connect_listen() before accept_and_start()"
        self._server.settimeout(self._accept_timeout)
        conn, _addr = self._server.accept()
        conn.setblocking(False)
        self._sock = conn
        self._open()  # provisional geometry only; it sizes the probe
        try:
            self._send_start()
            info = self._identify_from_stream()
        except Exception:
            self.disconnect()  # don't leak the accepted socket on a failed start
            raise
        self._info = info
        return info

    def read_settings(self, timeout: float = 1.0) -> bytes | None:
        """Ask the device for its current settings (GETSET=1, INFO=000).

        Returns the 13 configuration bytes, the first two being the control
        bytes in force, or ``None`` if the device does not answer in time.
        Call this *before* starting the stream -- once data is flowing the
        reply cannot be told apart from sample bytes.
        """
        sock = self._sock
        if sock is None:
            raise RuntimeError("not connected")
        sock.sendall(C.SESSANTAQUATTRO_GET_SETTINGS_WORD.to_bytes(2, "big"))
        sock.settimeout(timeout)
        try:
            reply = bytearray()
            while len(reply) < C.SESSANTAQUATTRO_SETTINGS_NBYTES:
                chunk = sock.recv(C.SESSANTAQUATTRO_SETTINGS_NBYTES - len(reply))
                if not chunk:
                    return None
                reply.extend(chunk)
            return bytes(reply)
        except (TimeoutError, OSError):
            return None
        finally:
            sock.setblocking(False)

    # --- base hooks ---------------------------------------------------------
    def _open(self) -> StreamInfo:
        self._prepare_stream()
        self.dropped_samples = 0
        self.dropout_events = 0
        self._last_counter = None
        self._warned_dropout = False
        self._identified = False
        # Provisional, and only to size the probe: the real width comes from
        # `_identify_from_stream`, which runs before any StreamInfo is returned.
        self._set_geometry(max(C.SESSANTAQUATTRO_ACCESSORY_CANDIDATES))
        assert self._geo is not None
        self._probe_nbytes = (
            _PROBE_SAMPLES * self._geo.n_total * self._geo.bytes_per_sample
        )
        n_out = self._geo.n_total if self._include_aux else self._geo.n_bio
        return StreamInfo(
            n_channels=n_out,
            fs=self._geo.fs,
            dtype=np.dtype(np.float32),
            channel_names=C.sessantaquattro_channel_names(self._geo)[:n_out],
        )

    def _set_geometry(self, n_accessory: int) -> None:
        self._geo = C.sessantaquattro_geometry(
            nch_mode=self._nch_mode,
            fs_mode=self._fs_mode,
            mode=self._mode,
            n_accessory=n_accessory,
            high_res=self._high_res,
        )
        self._frame_nbytes = self._geo.n_total * self._geo.bytes_per_sample

    def _config_word(self, *, go: bool) -> int:
        return C.sessantaquattro_config_word(
            nch_mode=self._nch_mode,
            fs_mode=self._fs_mode,
            mode=self._mode,
            high_res=self._high_res,
            hpf=self._hpf,
            gain=self._gain,
            go=go,
        )

    def _identify_from_stream(self) -> StreamInfo:
        """Fix the accessory width from the live stream, then report the real geometry.

        `StreamInfo` is a contract `Stream` checks every chunk against, so it cannot
        be a guess. The accessory width is only knowable from the data — it is
        recovered from the ramp counter — and data only flows once GO=1 has landed,
        so the probe belongs here, between starting the transfer and handing the
        info back.

        Declaring the widest candidate instead and correcting later does not work:
        with ``include_aux=True`` a device reporting a 4-wide block then fails every
        chunk with ``expected (_, 72)`` against its actual 68. Reported from the UI.
        """
        assert self._sock is not None
        deadline = time.monotonic() + _PROBE_TIMEOUT_S
        while len(self._buf) < self._probe_nbytes:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Sessantaquattro: only {len(self._buf)} of {self._probe_nbytes} "
                    f"probe bytes arrived in {_PROBE_TIMEOUT_S:.0f}s. The device "
                    "accepted the connection but is not streaming."
                )
            try:
                chunk = self._sock.recv(65536)
            except BlockingIOError:
                time.sleep(0.005)
                continue
            if not chunk:
                raise ConnectionError(
                    "Sessantaquattro: device closed the connection during the probe"
                )
            self._buf.extend(chunk)

        self._identify_geometry(bytes(self._buf[: self._probe_nbytes]))
        self._identified = True
        assert self._geo is not None
        n_out = self._geo.n_total if self._include_aux else self._geo.n_bio
        return StreamInfo(
            n_channels=n_out,
            fs=self._geo.fs,
            dtype=np.dtype(np.float32),
            channel_names=C.sessantaquattro_channel_names(self._geo)[:n_out],
        )

    def _send_start(self) -> None:
        """Send the settings *with GO=1*. One word, and only one.

        Do not send the settings with GO=0 first. Measured against an SE004
        (firmware 5.24) over three trials: GO=1 alone streams immediately at
        233.8 kB/s, while settings-then-GO makes the device **close the
        connection** having sent nothing — with or without a delay between the
        two writes. GO=0 is the stop command, and on a fresh connection the
        device honours it by hanging up, so the GO=1 that follows lands on a
        dead socket. The stream then reconnects and the device redials, which
        presents as a connection that flaps forever and never delivers a sample.
        """
        assert self._sock is not None
        self._sock.sendall(self._config_word(go=True).to_bytes(2, "big"))

    def _send_stop(self) -> None:
        assert self._sock is not None
        self._sock.sendall(self._config_word(go=False).to_bytes(2, "big"))

    def _drain(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Identify the channel count before the base slices any frames.

        The probe changes ``_frame_nbytes``, so slicing first would cut on the
        provisional width and reshape on the real one.
        """
        if not self._identified:
            if len(self._buf) < self._probe_nbytes:
                return None, None  # wait for enough bytes to decide
            self._identify_geometry(bytes(self._buf[: self._probe_nbytes]))
            self._identified = True
        return super()._drain()

    def _decode(self, frame: bytes) -> np.ndarray:
        assert self._geo is not None
        full = self._decode_words(frame, self._geo.n_total)
        self._track_counter(full[:, -1])
        bio = full[:, : self._geo.n_bio] * np.float32(C.SESSANTAQUATTRO_CONV_FACTOR_MV)
        if not self._include_aux:
            return bio
        aux = full[:, self._geo.n_bio :]  # unscaled AUX / quaternion / counter
        return np.concatenate([bio, aux], axis=1).astype(np.float32)

    # --- geometry probe -----------------------------------------------------
    def _decode_words(self, frame: bytes, n_channels: int) -> np.ndarray:
        assert self._geo is not None
        if self._geo.bytes_per_sample == 2:
            return decode_be_int16(frame, n_channels=n_channels)
        return decode_be_int24(frame, n_channels=n_channels)

    def _identify_geometry(self, frame: bytes) -> None:
        """Pick the accessory width whose last channel is a clean ramp.

        Raises if none does; a guess would mislabel every channel.
        """
        assert self._geo is not None
        width = self._geo.bytes_per_sample
        tried: list[str] = []
        for n_accessory in C.SESSANTAQUATTRO_ACCESSORY_CANDIDATES:
            self._set_geometry(n_accessory)
            assert self._geo is not None
            n_total = self._geo.n_total
            n_samples = min(len(frame) // (n_total * width), _PROBE_SAMPLES)
            if n_samples < 2:
                tried.append(f"{n_total} (too few samples to test)")
                continue
            usable = frame[: n_samples * n_total * width]
            counter = self._decode_words(usable, n_total)[:, -1]
            if self._is_ramp(counter):
                if n_accessory != max(C.SESSANTAQUATTRO_ACCESSORY_CANDIDATES):
                    _log.info(
                        "Sessantaquattro: %d accessory channels (%d total)",
                        n_accessory,
                        n_total,
                    )
                return
            tried.append(str(n_total))
        raise ValueError(
            "Sessantaquattro: could not identify the channel count. Tried totals "
            f"{', '.join(tried)} for {self._geo.n_bio} bioelectrical channels; none "
            "produced a monotonic sample counter in the last channel. Check that "
            "nch_mode/mode match the device configuration."
        )

    @staticmethod
    def _is_ramp(counter: np.ndarray) -> bool:
        steps = np.diff(counter.astype(np.int64))
        return bool(np.all(np.where(steps < 0, steps + _COUNTER_WRAP, steps) == 1))

    # --- loss accounting ----------------------------------------------------
    def _track_counter(self, counter: np.ndarray) -> None:
        """Accumulate samples the device sent that never reached us."""
        values = counter.astype(np.int64)
        steps = np.diff(values)
        if self._last_counter is not None:
            steps = np.concatenate([[values[0] - self._last_counter], steps])
        self._last_counter = int(values[-1])

        steps = np.where(steps < 0, steps + _COUNTER_WRAP, steps)
        gaps = steps[steps > 1]
        if gaps.size == 0:
            return
        self.dropped_samples += int(np.sum(gaps - 1))
        self.dropout_events += int(gaps.size)
        if not self._warned_dropout:
            self._warned_dropout = True
            _log.warning(
                "Sessantaquattro: dropped %d samples (device counter jumped by %d). "
                "The acquisition loop is not keeping up; further gaps are counted in "
                "dropped_samples.",
                int(np.sum(gaps - 1)),
                int(gaps.max()),
            )

    def disconnect(self) -> None:
        """Stop streaming and close the device + listening sockets."""
        super().disconnect()
        if self._server is not None:
            try:
                self._server.close()
            finally:
                self._server = None
