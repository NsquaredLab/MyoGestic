import threading
import time

import numpy as np
from mne_lsl.lsl import StreamInfo, StreamOutlet

from myogestic.sources.lsl import LSLSource
from myogestic.stream import Stream


def start_synthetic_stream(name="TestEMG_unit", n_channels=64, fs=2048):
    """Start a fake LSL stream in a background thread. Returns stop function."""
    info = StreamInfo(name, "EMG", n_channels, fs, "float32", "")
    outlet = StreamOutlet(info)
    running = [True]

    def _push():
        chunk_size = 64
        interval = chunk_size / fs
        while running[0]:
            chunk = np.random.randn(chunk_size, n_channels).astype(np.float32) * 100
            for sample in chunk:
                outlet.push_sample(sample)
            time.sleep(interval)

    t = threading.Thread(target=_push, daemon=True)
    t.start()
    return lambda: running.__setitem__(0, False)


def test_stream_roundtrip():
    """Verify data flows from synthetic LSL through Stream."""
    stop = start_synthetic_stream("TestEMG_unit", n_channels=8, fs=256)
    time.sleep(0.5)  # let stream start

    stream = Stream("test", source=LSLSource("TestEMG_unit"), window_seconds=0.5)
    stream.start()
    time.sleep(2.0)  # collect data

    data, ts = stream.get_window()
    # data is channels-first: shape == (n_channels, n_samples)
    assert data.shape[0] == 8, f"Expected 8 channels, got {data.shape[0]}"
    assert data.shape[1] > 0, "No samples collected"
    assert len(ts) == data.shape[1], "Timestamp count mismatch"
    assert ts[-1] > ts[0], "Timestamps not monotonic"

    # Window should be ~0.5s worth = ~128 samples at 256 Hz
    expected = int(0.5 * 256)
    assert data.shape[1] == expected, f"Expected {expected} samples, got {data.shape[1]}"

    stream.stop()
    stop()


def test_stream_reconnect_swaps_buffers_atomically():
    """reconnect() must hold _lock for the whole swap so concurrent acquire
    reads can't observe a half-torn buffer state."""
    stop = start_synthetic_stream("ReconA", n_channels=4, fs=128)
    time.sleep(0.4)

    stream = Stream("test", source=LSLSource("ReconA"), window_seconds=0.3)
    stream.start()
    time.sleep(1.0)

    # Verify connected
    assert stream.info is not None
    assert stream.info.n_channels == 4
    initial_data = stream._data
    assert initial_data is not None

    # Stop the original synthetic stream and start a new one with different shape
    stop()
    time.sleep(0.3)
    stop2 = start_synthetic_stream("ReconA", n_channels=2, fs=128)
    time.sleep(0.4)

    # reconnect() under load — acquire loop is hammering read()
    ok = stream.reconnect()
    assert ok, f"reconnect failed: {stream.last_error}"
    # After reconnect, info reflects the new shape
    assert stream.info is not None
    assert stream.info.n_channels == 2
    # Buffers were re-allocated (new RingBuffer instance)
    assert stream._data is not None
    assert stream._data is not initial_data

    time.sleep(0.5)  # let acquire fill new buffers
    data, _ = stream.get_window()
    # Some data should have arrived through the new schema
    assert data.shape[0] == 2

    stream.stop()
    stop2()


def test_stream_reconnect_clears_m4_scratch():
    """_allocate_buffers must reset M4 scratch — otherwise a reconnect to a
    different dtype could silently cast through stale buffers."""
    stop = start_synthetic_stream("M4Recon", n_channels=4, fs=128)
    time.sleep(0.4)

    stream = Stream("test", source=LSLSource("M4Recon"), window_seconds=0.2)
    stream.start()
    time.sleep(0.5)

    # Trigger M4 path
    stream._update_m4_snapshot()
    assert (
        stream._m4_work_col is not None
        or stream._display_n < 2
        or stream._m4_n == stream._display_n
    )

    # Reconnect — M4 scratch must be invalidated
    stream.reconnect()
    assert stream._m4_downsampler is None
    assert stream._m4_work_col is None
    assert stream._m4_work_idx is None
    assert stream._m4_work_d is None
    assert stream._m4_work_t is None

    stream.stop()
    stop()
    stop()
