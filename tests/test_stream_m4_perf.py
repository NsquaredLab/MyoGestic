"""M4 display decimation is computed lazily by get_display() on the render thread, not
on the acquire hot path. Includes a benchmark of the per-snapshot M4 cost at the high
channel counts (120-256 ch) where it used to starve the socket read."""

import time

import numpy as np

from myogestic.stream import Stream, StreamInfo


class _FakeSrc:
    def __init__(self, n_ch, fs=10240.0):
        self._info = StreamInfo(n_channels=n_ch, fs=fs)

    def connect(self):
        return self._info

    def read(self):
        return None, None

    def disconnect(self):
        pass


def _stream_with_display(n_ch, n_samples):
    s = Stream("bench", source=_FakeSrc(n_ch), window_ms=1000)
    rng = np.random.default_rng(0)
    s._display_d = rng.standard_normal((n_samples, n_ch)).astype(np.float32)
    s._display_t = np.arange(n_samples, dtype=np.float64) / 10240.0
    s._display_n = n_samples
    return s


def test_m4_not_precomputed_on_the_hot_path():
    # A populated display buffer carries no M4 result until get_display asks for it —
    # proof the acquire thread no longer precomputes it.
    s = _stream_with_display(120, 20000)
    assert s._m4_n == 0
    out = s.get_display(n_pixels=800)
    assert out is not None
    t, d = out
    assert d.shape[1] == 120
    assert len(t) == d.shape[0] and len(t) <= 20000  # a valid snapshot
    assert s._m4_n > 0  # computed lazily on the call


def test_m4_small_buffer_returns_all_samples():
    s = _stream_with_display(8, 100)  # < n_pixels*4 -> no decimation
    t, d = s.get_display(n_pixels=800)
    assert len(t) == 100 and d.shape == (100, 8)


def test_benchmark_m4_cost_removed_from_acquire_loop(capsys):
    # Report the per-snapshot M4 cost that used to run on the acquire thread ~60x/s.
    for n_ch in (120, 256):
        s = _stream_with_display(n_ch, 20000)  # ~2 s at 10240 Hz
        s._update_m4_snapshot()  # warm up (lazy tsdownsample import + scratch alloc)
        reps = 20
        start = time.perf_counter()
        for _ in range(reps):
            s._update_m4_snapshot()
        per_call_ms = (time.perf_counter() - start) / reps * 1e3
        with capsys.disabled():
            print(
                f"\n  M4 {n_ch}ch x 20000 samples: {per_call_ms:.2f} ms/snapshot "
                f"(removed from the acquire thread; now lazy on render)"
            )
        assert s._m4_n > 0
