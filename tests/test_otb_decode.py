import numpy as np

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
