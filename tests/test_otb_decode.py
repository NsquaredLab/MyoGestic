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
