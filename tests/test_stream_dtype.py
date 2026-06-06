"""Dtype support for streams: validation, normalisation, and the guarantee
that the window handed to ``@pipeline.extract`` is always float32 even when the
stream buffers a compact dtype (e.g. int16 from a raw-ADC amp)."""

import numpy as np
import pytest

from myogestic.stream import SUPPORTED_DTYPES, Stream, StreamInfo


def test_streaminfo_default_is_float32():
    assert StreamInfo(n_channels=4, fs=1000).dtype == np.dtype(np.float32)


@pytest.mark.parametrize(
    "dt", ["int16", np.int16, np.dtype("int16"), "float16", "int8", "int32", "float64"]
)
def test_streaminfo_accepts_and_normalises_supported(dt):
    info = StreamInfo(n_channels=2, fs=100, dtype=dt)
    assert isinstance(info.dtype, np.dtype)
    assert info.dtype in SUPPORTED_DTYPES


@pytest.mark.parametrize("dt", ["uint8", "uint16", "complex64", "bool"])
def test_streaminfo_rejects_unsupported(dt):
    with pytest.raises(ValueError, match="Unsupported dtype"):
        StreamInfo(n_channels=2, fs=100, dtype=dt)


class _Int16Source:
    """Source-protocol stub emitting int16 chunks (a raw-ADC EMG amp)."""

    def __init__(self, n_channels: int = 2, fs: float = 1000.0) -> None:
        self._info = StreamInfo(n_channels=n_channels, fs=fs, dtype=np.dtype("int16"))

    def connect(self) -> StreamInfo:
        return self._info

    def read(self):
        n = 8
        data = np.full((n, self._info.n_channels), 1000, dtype=np.int16)
        ts = np.arange(n, dtype=np.float64)
        return data, ts

    def disconnect(self) -> None:
        pass


def test_get_window_is_float32_even_for_int16_stream():
    stream = Stream("emg", source=_Int16Source(), window_ms=10, buffer_ms=1000)
    stream._acquire_step()  # first step connects + allocates buffers
    for _ in range(5):
        stream._acquire_step()

    data, _ts = stream.get_window()

    # extract always sees float32, channels-first, with values preserved
    assert data.dtype == np.float32
    assert data.shape[0] == 2
    assert data.shape[1] > 0
    assert np.allclose(data, 1000.0)

    # ...while the buffers themselves stay compact int16 (half the memory)
    assert stream.info is not None and stream.info.dtype == np.dtype("int16")
    assert stream._win_d.dtype == np.dtype("int16")
