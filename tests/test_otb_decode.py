import socket
import time

import numpy as np
import pytest

from myogestic.sources.otb._decode import decode_be_int16, decode_be_int24


def _be_int16_bytes(values):
    out = bytearray()
    for v in values:
        out += int(v & 0xFFFF).to_bytes(2, "big", signed=False)
    return bytes(out)


def _be_int24_bytes(values):
    out = bytearray()
    for v in values:
        out += int(v & 0xFFFFFF).to_bytes(3, "big", signed=False)
    return bytes(out)


def test_decode_be_int16_shape_and_order():
    # 3 channels, 2 samples. Wire order is channels-contiguous per sample:
    # [c0t0, c1t0, c2t0, c0t1, c1t1, c2t1]
    raw = _be_int16_bytes([10, 20, 30, 11, 21, 31])
    out = decode_be_int16(raw, n_channels=3)
    assert out.shape == (2, 3)              # sample-major
    assert out.dtype == np.float32
    np.testing.assert_array_equal(out[0], [10, 20, 30])
    np.testing.assert_array_equal(out[1], [11, 21, 31])


def test_decode_be_int16_twos_complement():
    raw = _be_int16_bytes([-1, -32768, 32767])
    out = decode_be_int16(raw, n_channels=3)
    np.testing.assert_array_equal(out[0], [-1, -32768, 32767])


def test_decode_be_int24_twos_complement():
    raw = _be_int24_bytes([-1, 8388607, -8388608])
    out = decode_be_int24(raw, n_channels=3)
    assert out.shape == (1, 3)
    np.testing.assert_array_equal(out[0], [-1, 8388607, -8388608])


# Task 3: constants tests
from myogestic.sources.otb import _constants as C


def test_muovi_control_byte_matches_matlab():
    # Read_muovi.m: Command = EMG*8 + Mode*2 + 1
    assert C.muovi_control_byte(emg=True, mode=0, go=True) == 0x09
    assert C.muovi_control_byte(emg=True, mode=1, go=True) == 0x0B
    assert C.muovi_control_byte(emg=False, mode=0, go=True) == 0x01
    # stop = clear GO bit
    assert C.muovi_control_byte(emg=True, mode=0, go=False) == 0x08


def test_muovi_geometry_mode0():
    geo = C.muovi_geometry(plus=False, emg=True, mode=0)
    assert geo.n_total == 38        # 32 bio + 6 aux
    assert geo.n_bio == 32
    assert geo.fs == 2000.0
    assert geo.bytes_per_sample == 2


def test_muovi_geometry_plus_eeg():
    geo = C.muovi_geometry(plus=True, emg=False, mode=0)
    assert geo.n_total == 70        # 64 bio + 6 aux
    assert geo.n_bio == 64
    assert geo.fs == 500.0
    assert geo.bytes_per_sample == 3


def test_muovi_conversion_factor_gain8_mv():
    assert C.MUOVI_CONV_FACTOR_MV == 0.000286


# Task 4: _OTBSource base tests
from myogestic.sources.otb._base import _OTBSource
from myogestic.stream import StreamInfo


class _FakeOTB(_OTBSource):
    """Drives the base buffering/decoding without a real socket."""
    def __init__(self):
        super().__init__()
        self._info = StreamInfo(n_channels=2, fs=4.0)
        self._frame_nbytes = 2 * 2  # 2 channels x 1 sample x int16

    def _open(self):
        return self._info

    def _send_start(self):  # no-op for the fake
        pass

    def _send_stop(self):
        pass

    def _decode(self, frame: bytes):
        return decode_be_int16(frame, n_channels=2)

    # test helper: push bytes into the accumulator as if recv'd
    def feed(self, raw: bytes):
        self._buf.extend(raw)


def test_base_drain_returns_complete_frames_only():
    src = _FakeOTB()
    src.connect()
    # one and a half frames -> only the complete frame comes out
    src.feed(_be_int16_bytes([5, 6]) + _be_int16_bytes([7])[:2])
    data, ts = src._drain()
    assert data.shape == (1, 2)
    np.testing.assert_array_equal(data[0], [5, 6])
    assert ts.shape == (1,)
    # leftover (partial frame) stays buffered
    assert len(src._buf) == 2


def test_base_read_returns_none_when_empty():
    src = _FakeOTB()
    src.connect()
    assert src.read() == (None, None)


# Task 7: decode_le_int16
from myogestic.sources.otb._decode import decode_le_int16


def _le_int16_bytes(values):
    out = bytearray()
    for v in values:
        out += int(v & 0xFFFF).to_bytes(2, "little", signed=False)
    return bytes(out)


def test_decode_le_int16_shape_order_and_sign():
    raw = _le_int16_bytes([1, 2, 3, -1, -2, -3])  # 3 ch, 2 samples
    out = decode_le_int16(raw, n_channels=3)
    assert out.shape == (2, 3)
    assert out.dtype == np.float32
    np.testing.assert_array_equal(out[0], [1, 2, 3])
    np.testing.assert_array_equal(out[1], [-1, -2, -3])


# Task 8: Quattrocento config builder
def test_quattro_channel_counts_and_factors():
    assert C.QUATTRO_NCH_BY_MODE == {0: 120, 1: 216, 2: 312, 3: 408}
    assert C.QUATTRO_FS_BY_MODE == {0: 512.0, 1: 2048.0, 2: 5120.0, 3: 10240.0}
    assert abs(C.QUATTRO_CONV_FACTOR_MV - (5 / 2 ** 16 / 150 * 1000)) < 1e-12


def test_quattro_config_is_40_bytes_with_valid_crc():
    cfg = C.quattro_config(fs_mode=1, nch_mode=3, acq_on=True)
    assert len(cfg) == 40
    # byte0 = 0x80 | fsamp(01<<3=8) | nch(11<<1=6) | acq_on(1) = 0x80|8|6|1
    assert cfg[0] == (0x80 | 8 | 6 | 1)
    # CRC trailer is valid over the first 39 bytes
    assert cfg[39] == C.crc8(cfg[:39])


def test_quattro_stop_config_byte0():
    # Stop preserves the configured fs/nch/filters and clears only the GO bit.
    start = C.quattro_config(fs_mode=1, nch_mode=3, acq_on=True)
    stop = C.quattro_config(fs_mode=1, nch_mode=3, acq_on=False)
    assert stop[0] == start[0] & ~0x01
    assert stop[0] == (0x80 | 8 | 6)  # 0x8E: fs/nch preserved, GO cleared


def test_base_read_flushes_then_signals_on_peer_close():
    """Empty recv (peer closed) must flush buffered frames first, then raise so
    the Stream marks the source disconnected instead of idling as connected."""
    a, b = socket.socketpair()
    src = _FakeOTB()
    src.connect()          # sets _info + frame_nbytes; _sock starts None
    a.setblocking(False)
    src._sock = a
    b.sendall(_be_int16_bytes([5, 6]))  # one complete frame (2ch x 1 sample)
    b.close()
    time.sleep(0.05)

    data, ts = src.read()               # drains the buffered frame (EOF not yet seen)
    assert data is not None and data.shape == (1, 2)
    np.testing.assert_array_equal(data[0], [5, 6])

    with pytest.raises(ConnectionError):
        src.read()                      # recv now returns EOF -> drop + signal
    assert src._sock is None
    a.close()


def test_base_connect_cleans_up_socket_when_start_fails():
    """If _send_start raises, connect() must not leak the opened socket."""

    class _FailStart(_FakeOTB):
        def _open(self):
            self._a, self._b = socket.socketpair()
            self._sock = self._a
            self._frame_nbytes = 4
            return self._info

        def _send_start(self):
            raise OSError("boom")

    src = _FailStart()
    with pytest.raises(OSError):
        src.connect()
    assert src._sock is None
    src._b.close()


def test_quattro_default_bio_partition_and_aux_scaling():
    """Default bio excludes the 16 AUX IN + 8 accessory; AUX scaled to V,
    accessory raw (Codex-flagged: AUX was previously scaled as bio)."""
    from myogestic.sources.otb.quattrocento import QuattrocentoSource

    src = QuattrocentoSource(nch_mode=0, include_aux=True)  # 120 total
    assert src._wire_bio == 96  # 120 - 16 AUX - 8 accessory
    out = src._decode(_le_int16_bytes(list(range(120))))
    assert out.shape == (1, 120)
    np.testing.assert_allclose(out[0, 10], 10 * C.QUATTRO_CONV_FACTOR_MV, rtol=1e-5)
    np.testing.assert_allclose(out[0, 96], 96 * C.QUATTRO_AUX_FACTOR_V, rtol=1e-5)
    np.testing.assert_allclose(out[0, 119], 119.0, rtol=1e-6)  # accessory raw


def test_quattro_default_bio_excludes_aux_when_biosignal_only():
    from myogestic.sources.otb.quattrocento import QuattrocentoSource

    src = QuattrocentoSource(nch_mode=1)  # 216 total, biosignal-only
    assert src._wire_bio == 192
    out = src._decode(_le_int16_bytes(list(range(216))))
    assert out.shape == (1, 192)


def test_base_read_raises_and_drops_socket_on_oserror():
    """A recv() OSError (device reset) drops the socket and raises so the Stream
    marks it disconnected instead of polling a dead connection forever."""

    class _BoomRecv:
        def recv(self, _n):
            raise OSError("connection reset")

        def close(self):
            pass

    src = _FakeOTB()
    src.connect()
    src._sock = _BoomRecv()
    with pytest.raises(ConnectionError):
        src.read()
    assert src._sock is None


# A5: timestamps stay strictly increasing across batches
def test_drain_timestamps_clamp_to_monotonic():
    from mne_lsl.lsl import local_clock

    src = _FakeOTB()  # fs = 4.0
    src.connect()
    base = local_clock() + 100.0  # pretend the previous batch ended in the future
    src._last_ts = base
    src.feed(_be_int16_bytes([1, 2]) + _be_int16_bytes([3, 4]))  # 2 frames
    data, ts = src._drain()
    assert data.shape == (2, 2)
    # clamped to _last_ts + 1/fs, then 1/fs spacing within the batch
    np.testing.assert_allclose(ts, [base + 0.25, base + 0.5])
    assert np.all(np.diff(ts) > 0)
    assert src._last_ts == ts[-1]


def test_drain_timestamps_increase_across_batches():
    src = _FakeOTB()
    src.connect()
    src.feed(_be_int16_bytes([1, 2]))
    _d1, t1 = src._drain()
    src.feed(_be_int16_bytes([3, 4]))
    _d2, t2 = src._drain()
    assert t2[0] > t1[-1]


# A4: reconnect re-runs the connect lifecycle and can retarget
def test_reconnect_reopens_and_can_retarget():
    events = []

    class _Recon(_FakeOTB):
        def _open(self):
            events.append("open")
            self._frame_nbytes = 4
            return self._info

        def _send_start(self):
            events.append("start")

        def _apply_target(self, target):
            events.append(f"target:{target}")

    src = _Recon()
    src.connect()
    events.clear()
    info = src.reconnect(target="1.2.3.4")
    assert isinstance(info, StreamInfo)
    assert events == ["target:1.2.3.4", "open", "start"]


def test_quattro_apply_target_sets_device_ip():
    from myogestic.sources.otb.quattrocento import QuattrocentoSource

    src = QuattrocentoSource(nch_mode=0)
    src._apply_target("169.254.1.99")
    assert src._device_ip == "169.254.1.99"
