"""End-to-end validation of the M4 fix with synthetic data (no hardware, no LSL).

Drives the REAL acquire loop (`Stream._acquire_step`) with a high-channel-count synthetic
source and proves: (1) the M4 decimation is never computed on the acquire path, (2) the
loop keeps up (fills a full window), (3) no acquire step pays the ~30-70 ms M4 cost. Also
guards that the signal viewer's own decimation path still returns valid data.
"""

import time

import numpy as np

from myogestic.stream import Stream, StreamInfo


class _SynthSource:
    """In-process synthetic EMG source: read() hands out a fixed-size chunk with a
    monotonic timebase and counts what it emitted. Matches the Source protocol."""

    def __init__(self, n_channels=256, fs=2048.0, chunk=64):
        self._info = StreamInfo(n_channels=n_channels, fs=fs)
        self._n_ch = n_channels
        self._fs = fs
        self._chunk = chunk
        self._rng = np.random.default_rng(0)
        self.samples_emitted = 0

    def connect(self) -> StreamInfo:
        return self._info

    def read(self):
        data = self._rng.standard_normal((self._chunk, self._n_ch)).astype(np.float32)
        ts = (self.samples_emitted + np.arange(self._chunk)) / self._fs
        self.samples_emitted += self._chunk
        return data, ts

    def disconnect(self) -> None:
        pass


def test_acquire_loop_never_runs_m4_and_keeps_up(capsys):
    fs, n_ch = 2048.0, 256
    src = _SynthSource(n_channels=n_ch, fs=fs, chunk=64)
    stream = Stream("emg", source=src, window_ms=1000, buffer_ms=3000)

    # Spy on the M4 computation: it must never be called from the acquire path.
    calls = {"m4": 0}
    real_m4 = stream._update_m4_snapshot

    def _spy():
        calls["m4"] += 1
        return real_m4()

    stream._update_m4_snapshot = _spy

    stream._acquire_step()  # first step connects + allocates, no read
    step_times = []
    for _ in range(300):  # 300 * 64 = 19200 samples > 3 s buffer (6144)
        t0 = time.perf_counter()
        stream._acquire_step()
        step_times.append(time.perf_counter() - t0)

    max_ms = max(step_times) * 1e3
    mean_ms = sum(step_times) / len(step_times) * 1e3
    with capsys.disabled():
        print(
            f"\n  acquire step @ {n_ch}ch: mean {mean_ms:.3f} ms, max {max_ms:.3f} ms "
            f"(M4 snapshot, now off this path, was ~29-71 ms)"
        )

    # (1) M4 is never computed on the acquire path — the airtight proof.
    assert calls["m4"] == 0
    # (2) the loop kept up: connected, no error, a full window is available.
    assert stream.status == "connected" and stream.last_error == ""
    data, ts = stream.get_window()
    assert data.shape == (n_ch, int(1.0 * fs))  # channels-first, full 1 s window
    # (3) no step paid the M4 cost (generous bound; still well under the 29 ms M4 floor).
    assert max(step_times) < 0.015


def test_viewer_decimation_path_still_valid():
    from myogestic.widgets.signals._state import ViewerState, _m4_decimate_visible_window

    src = _SynthSource(n_channels=64, fs=2048.0, chunk=64)
    stream = Stream("emg", source=src, window_ms=1000, buffer_ms=3000)
    stream._acquire_step()
    for _ in range(200):
        stream._acquire_step()

    snap = stream.get_raw_snapshot()
    assert snap is not None
    ts_raw, data_raw = snap
    assert data_raw.shape[1] == 64

    v = ViewerState(n_pixels=500)  # n_out = 2000 < ~6144 buffered -> decimation runs
    n_out = max(1, v.n_pixels) * 4
    ts, data = _m4_decimate_visible_window(ts_raw, data_raw, n_out, v)
    assert np.all(np.diff(ts) > 0)  # strictly increasing time
    assert data.shape[1] == 64  # full channel width preserved
    assert len(ts) == data.shape[0] <= len(ts_raw)
