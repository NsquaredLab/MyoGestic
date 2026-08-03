"""Regression tests for bounded live reads from long acquisition buffers."""

from __future__ import annotations

import numpy as np

import myogestic.stream as stream_module
from myogestic.stream import Stream, StreamInfo


class _CountingSource:
    def __init__(self, *, fs: float = 100.0, chunk: int = 4, n_channels: int = 2) -> None:
        self.info = StreamInfo(n_channels=n_channels, fs=fs, dtype=np.float32)
        self.chunk = chunk
        self.next_sample = 0

    def connect(self) -> StreamInfo:
        return self.info

    def read(self) -> tuple[np.ndarray, np.ndarray]:
        sample = np.arange(self.next_sample, self.next_sample + self.chunk, dtype=np.float32)
        self.next_sample += self.chunk
        data = sample[:, None] + 1000 * np.arange(self.info.n_channels, dtype=np.float32)
        timestamps = 1.0 + sample.astype(np.float64) / self.info.fs
        return data, timestamps

    def disconnect(self) -> None:
        pass


def _filled_stream(*, steps: int = 40) -> Stream:
    stream = Stream(
        "emg",
        source=_CountingSource(),
        window_ms=100,
        buffer_ms=1000,
    )
    assert stream.reconnect()
    for _ in range(steps):
        stream._acquire_step()
    return stream


def test_acquisition_never_refreshes_the_growing_full_snapshot(monkeypatch) -> None:
    stream = _filled_stream(steps=1)

    def fail() -> None:
        raise AssertionError("acquisition copied the full display history")

    monkeypatch.setattr(stream, "_update_raw_snapshot", fail)
    for _ in range(50):
        stream._acquire_step()

    # The compatibility snapshot remains untouched until a caller explicitly
    # requests it; acquisition work therefore cannot grow with buffer fill.
    assert stream._display_n == 0


def test_prediction_and_viewer_copy_only_the_requested_tail(monkeypatch) -> None:
    stream = _filled_stream()
    copied_counts: list[int] = []
    original = stream_module._copy_ring_tail_into

    def observed(rb, out, count, cap):
        copied_counts.append(count)
        return original(rb, out, count, cap)

    monkeypatch.setattr(stream_module, "_copy_ring_tail_into", observed)

    data, timestamps = stream.get_window()
    epoch, end_seq, fs, stable_ts, stable_data = stream.get_raw_snapshot_stable(0.2)

    assert data.shape == (2, 10)
    np.testing.assert_array_equal(data[0], np.arange(150, 160, dtype=np.float32))
    np.testing.assert_array_equal(timestamps, 1.0 + np.arange(150, 160) / 100.0)
    assert epoch == stream.epoch
    assert end_seq == 160
    assert fs == 100.0
    # Stable snapshots keep four guard samples, matching the historical API.
    assert stable_data.shape == (24, 2)
    np.testing.assert_array_equal(stable_data[:, 0], np.arange(136, 160, dtype=np.float32))
    np.testing.assert_array_equal(stable_ts, 1.0 + np.arange(136, 160) / 100.0)
    assert copied_counts == [10, 10, 24, 24]
    assert max(copied_counts) < stream._cap


def test_on_demand_full_snapshot_preserves_chronology_after_wrap() -> None:
    stream = _filled_stream()

    snapshot = stream.get_raw_snapshot()

    assert snapshot is not None
    timestamps, data = snapshot
    assert stream._display_n == stream._cap == 100
    np.testing.assert_array_equal(data[:, 0], np.arange(60, 160, dtype=np.float32))
    np.testing.assert_array_equal(timestamps, 1.0 + np.arange(60, 160) / 100.0)
    assert stream.last_timestamp() == timestamps[-1]


def test_tail_reads_return_all_available_samples_before_window_fills() -> None:
    stream = _filled_stream(steps=2)

    data, timestamps = stream.get_window()

    assert data.shape == (2, 8)
    np.testing.assert_array_equal(data[0], np.arange(8, dtype=np.float32))
    np.testing.assert_array_equal(timestamps, 1.0 + np.arange(8) / 100.0)
