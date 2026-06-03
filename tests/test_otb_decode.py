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
