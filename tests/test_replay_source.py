"""Test ReplaySource: write a synthetic session to zarr, replay it, verify data matches."""

import json
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import zarr

from myogestic.session import Session
from myogestic.sources.replay import ReplaySource
from myogestic.stream import Stream, StreamInfo


def create_synthetic_session(path: Path, stream_name: str, n_channels: int, fs: float):
    """Write a minimal session on disk that ReplaySource can read."""
    # Clean slate — zarr v3 refuses to overwrite existing arrays
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

    n_samples = int(fs * 2)  # 2 seconds of data
    rng = np.random.default_rng(42)
    data = rng.standard_normal((n_samples, n_channels)).astype(np.float32)
    ts = np.arange(n_samples, dtype=np.float64) / fs

    zarr.save(str(path / f"{stream_name}.zarr"), data)
    zarr.save(str(path / f"{stream_name}_timestamps.zarr"), ts)

    meta = {
        "app_name": "test",
        "created": "2026-01-01T00:00:00",
        "predict_hz": 50,
        "streams": {
            stream_name: {
                "n_channels": n_channels,
                "fs": fs,
                "dtype": "float32",
            }
        },
    }
    (path / "meta.json").write_text(json.dumps(meta))
    (path / "labels.json").write_text("[]")

    return data, ts


def test_replay_source_connect():
    """connect() reads meta.json and returns correct StreamInfo."""
    session_path = Path("/tmp/myogestic_replay_test_connect")
    data, ts = create_synthetic_session(session_path, "emg", n_channels=8, fs=256)

    src = ReplaySource(str(session_path), "emg")
    info = src.connect()

    assert info.n_channels == 8
    assert info.fs == 256.0
    assert info.dtype == np.float32

    src.disconnect()
    shutil.rmtree(session_path)


def test_replay_source_reads_all_data():
    """Calling read() in a loop eventually returns all session data."""
    session_path = Path("/tmp/myogestic_replay_test_all")
    original_data, original_ts = create_synthetic_session(session_path, "emg", n_channels=4, fs=128)

    src = ReplaySource(str(session_path), "emg", speed=100.0)  # fast replay
    src.connect()

    collected_data = []
    collected_ts = []
    deadline = time.perf_counter() + 5.0

    while time.perf_counter() < deadline:
        d, t = src.read()
        if d is not None and len(d) > 0:
            collected_data.append(d)
            collected_ts.append(t)
            total = sum(len(c) for c in collected_data)
            if total >= len(original_data):
                break
        else:
            time.sleep(0.001)

    all_data = np.concatenate(collected_data)
    all_ts = np.concatenate(collected_ts)

    # Should have read exactly the full session (before looping)
    assert len(all_data) >= len(original_data)
    # Trim to original length and compare
    np.testing.assert_array_equal(all_data[: len(original_data)], original_data)
    np.testing.assert_array_equal(all_ts[: len(original_ts)], original_ts)

    src.disconnect()
    shutil.rmtree(session_path)


def test_replay_source_loops():
    """After reaching the end, ReplaySource resets to pos=0 and keeps going."""
    session_path = Path("/tmp/myogestic_replay_test_loop")
    # Short session: 0.5s at 64 Hz = 32 samples
    original_data, _ = create_synthetic_session(session_path, "sig", n_channels=2, fs=64)
    n_total = len(original_data)

    src = ReplaySource(str(session_path), "sig", speed=100.0)
    src.connect()

    total_read = 0
    deadline = time.perf_counter() + 5.0
    looped = False

    while time.perf_counter() < deadline:
        d, _ = src.read()
        if d is not None and len(d) > 0:
            total_read += len(d)
            # If we've read more than the session contains, it must have looped
            if total_read > n_total * 1.5:
                looped = True
                break
        else:
            time.sleep(0.001)

    assert looped, f"Only read {total_read} samples, expected >{n_total * 1.5}"

    src.disconnect()
    shutil.rmtree(session_path)


def test_replay_into_stream():
    """ReplaySource -> Stream -> get_window() returns correct shape."""
    session_path = Path("/tmp/myogestic_replay_test_stream")
    create_synthetic_session(session_path, "emg", n_channels=8, fs=256)

    stream = Stream(
        "emg",
        source=ReplaySource(str(session_path), "emg", speed=10.0),
        window_ms=500,
    )
    stream.start()
    time.sleep(1.5)  # let replay feed the buffer

    data, ts = stream.get_window()
    assert data.shape[0] == 8  # channels-first
    assert data.shape[1] > 0
    assert len(ts) == data.shape[1]

    stream.stop()
    shutil.rmtree(session_path)


def test_replay_source_closes_zip_on_disconnect():
    """Replaying a .session.zip must release the ZipStore on disconnect.

    An open ZipStore locks the archive on Windows, so a leaked handle would
    block deleting / re-recording the file (and trip the tempdir cleanup here).
    """
    with tempfile.TemporaryDirectory() as tmp:
        s = Session(base_path=tmp)
        s.init_stream("emg", StreamInfo(n_channels=2, fs=64.0, dtype=np.dtype("float32")))
        s.append("emg", np.ones((32, 2), np.float32), np.arange(32, dtype=np.float64))
        s.save_meta("Replay")
        zip_path = s.pack_to_zip()

        src = ReplaySource(str(zip_path), "emg", speed=100.0)
        src.connect()
        src.read()
        assert src._session is not None
        src.disconnect()
        assert src._session is None  # ZipStore released

        # Would raise PermissionError (WinError 32) if the handle leaked.
        zip_path.unlink()
        assert not zip_path.exists()
