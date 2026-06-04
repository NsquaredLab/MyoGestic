"""Round-trip test: write Session → pack to .session.zip → read via open_session_store."""

import shutil
import tempfile

import numpy as np

from myogestic.session import (
    Session,
    iter_aligned_windows,
    iter_labeled_windows,
    open_session_store,
)
from myogestic.stream import StreamInfo


def test_pack_to_zip_roundtrip():
    """Write a session as folder zarr, pack to .session.zip, verify the
    folder is gone and the zip is readable with the same data."""
    with tempfile.TemporaryDirectory() as tmp:
        session = Session(base_path=tmp)
        info = StreamInfo(n_channels=4, fs=128.0, dtype=np.dtype("float32"))
        session.init_stream("emg", info)

        # Append some data
        rng = np.random.default_rng(seed=42)
        chunk = rng.normal(size=(64, 4)).astype(np.float32)
        ts = np.arange(64, dtype=np.float64)
        session.append("emg", chunk, ts)
        session.add_label(0, timestamp=0.5)
        session.add_label(1, timestamp=2.0)

        # Save + pack
        original_folder = session.path
        assert original_folder.is_dir()
        session.save_meta("PackRoundTrip")
        zip_path = session.pack_to_zip()

        # Folder gone, zip exists
        assert zip_path.exists()
        assert zip_path.suffix == ".zip"
        assert zip_path.name.endswith(".session.zip")
        assert not original_folder.exists()
        assert session.path == zip_path

        # Reopen via the read API
        loaded = open_session_store(zip_path)
        assert "emg" in loaded.stores
        emg_back = np.array(loaded.stores["emg"])
        assert emg_back.shape == (64, 4)
        assert np.allclose(emg_back, chunk)

        # Labels survived
        assert len(loaded.label_track) == 2
        assert loaded.label_track[0].class_index == 0
        assert loaded.label_track[1].class_index == 1


def test_pack_to_zip_failure_keeps_folder():
    """If pack fails (we simulate by writing to a read-only target), the
    original folder should remain so the user doesn't lose data."""
    with tempfile.TemporaryDirectory() as tmp:
        session = Session(base_path=tmp)
        info = StreamInfo(n_channels=2, fs=64.0, dtype=np.dtype("float32"))
        session.init_stream("sig", info)
        session.append("sig", np.ones((16, 2), dtype=np.float32), np.arange(16, dtype=np.float64))
        session.save_meta("PackFail")
        original_folder = session.path

        # Make the parent read-only to force the zip write to fail
        import os
        parent = original_folder.parent
        original_mode = os.stat(parent).st_mode
        os.chmod(parent, 0o555)
        try:
            try:
                session.pack_to_zip()
            except Exception:
                pass  # expected
            # Folder still exists (data preserved)
            assert original_folder.exists()
        finally:
            os.chmod(parent, original_mode)
            shutil.rmtree(original_folder, ignore_errors=True)


def test_iter_labeled_windows_basic():
    """Walk a multi-class session, yield fixed-size windows with class index."""
    with tempfile.TemporaryDirectory() as tmp:
        session = Session(base_path=tmp)
        info = StreamInfo(n_channels=2, fs=100.0, dtype=np.dtype("float32"))
        session.init_stream("emg", info)

        # 200 samples = 2s at 100Hz. Two trials: [0, 1s) Rest, [1s, 2s) Fist.
        data = np.arange(200 * 2, dtype=np.float32).reshape(200, 2)
        ts = np.linspace(0.0, 2.0, 200, endpoint=False)
        session.append("emg", data, ts)
        session.add_label(0, timestamp=0.0)   # Rest
        session.add_label(1, timestamp=1.0)   # Fist
        session.save_meta("IterTest")
        zip_path = session.pack_to_zip()

        windows = list(iter_labeled_windows(
            [str(zip_path)], "emg", win_seconds=0.2, hop_seconds=0.1,
        ))

    # 0.2s windows, 0.1s hop, 1s segment = 100 samples, win = 20 samples.
    # Starts: 0, 10, 20, …, 80 → 9 windows per segment (inclusive of the
    # final fitting start at idx_end - win_samples).
    rest = [w for w, _ts, ci in windows if ci == 0]
    fist = [w for w, _ts, ci in windows if ci == 1]
    assert len(rest) == 9
    assert len(fist) == 9
    # window is channels-first: shape == (n_channels, n_samples)
    for w, t, _ci in windows:
        assert w.shape == (2, 20)
        assert t.shape == (20,)


def test_iter_labeled_windows_yields_aligned_timestamps():
    """The yielded `ts` array matches the slice of the session's timestamp
    array — needed for cross-stream alignment downstream."""
    with tempfile.TemporaryDirectory() as tmp:
        session = Session(base_path=tmp)
        info = StreamInfo(n_channels=1, fs=100.0, dtype=np.dtype("float32"))
        session.init_stream("emg", info)
        ts_full = np.linspace(0.0, 2.0, 200, endpoint=False)
        session.append("emg", np.zeros((200, 1), dtype=np.float32), ts_full)
        session.add_label(0, timestamp=0.0)
        session.save_meta("TS")
        path = session.path

        first = next(iter_labeled_windows([str(path)], "emg", 0.2, 0.1))
        shutil.rmtree(path, ignore_errors=True)

    _w, t, _ci = first
    # First window starts at idx 0, span 20 samples → ts[:20] = [0.00, 0.01, …, 0.19]
    assert np.allclose(t, ts_full[:20])


def test_iter_labeled_windows_rejects_bad_args():
    """win_seconds <= 0 and hop_seconds <= 0 must raise (no silent coercion)."""
    import pytest
    with pytest.raises(ValueError, match="win_seconds"):
        list(iter_labeled_windows([], "emg", win_seconds=0.0, hop_seconds=0.1))
    with pytest.raises(ValueError, match="hop_seconds"):
        list(iter_labeled_windows([], "emg", win_seconds=0.2, hop_seconds=0.0))
    with pytest.raises(ValueError, match="hop_seconds"):
        list(iter_labeled_windows([], "emg", win_seconds=0.2, hop_seconds=-0.5))


def test_iter_labeled_windows_class_filter():
    """`classes` arg restricts which class_index values are yielded."""
    with tempfile.TemporaryDirectory() as tmp:
        session = Session(base_path=tmp)
        info = StreamInfo(n_channels=1, fs=100.0, dtype=np.dtype("float32"))
        session.init_stream("emg", info)
        session.append("emg", np.zeros((300, 1), dtype=np.float32),
                       np.linspace(0.0, 3.0, 300, endpoint=False))
        session.add_label(0, timestamp=0.0)   # Rest
        session.add_label(1, timestamp=1.0)   # Index
        session.add_label(2, timestamp=2.0)   # Middle
        session.save_meta("FilterTest")
        path = session.path

        windows_all = list(iter_labeled_windows(
            [str(path)], "emg", 0.2, 0.2,
        ))
        windows_filt = list(iter_labeled_windows(
            [str(path)], "emg", 0.2, 0.2, classes={0, 2},  # skip Index
        ))
        shutil.rmtree(path, ignore_errors=True)

    assert len(windows_all) > 0
    # Filtered: only class 0 and 2, no class 1
    classes = {ci for _w, _t, ci in windows_filt}
    assert classes == {0, 2}
    assert len(windows_filt) < len(windows_all)


def test_iter_aligned_windows_basic():
    """For each EMG window, fetch the kinematics value at the midpoint timestamp."""
    with tempfile.TemporaryDirectory() as tmp:
        session = Session(base_path=tmp)
        # Two streams at different rates: emg @ 100Hz, kin @ 50Hz
        emg_info = StreamInfo(n_channels=2, fs=100.0, dtype=np.dtype("float32"))
        kin_info = StreamInfo(n_channels=3, fs=50.0, dtype=np.dtype("float32"))
        session.init_stream("emg", emg_info)
        session.init_stream("kin", kin_info)

        # 1s of data: 100 emg samples, 50 kin samples
        emg = np.arange(100 * 2, dtype=np.float32).reshape(100, 2)
        emg_ts = np.linspace(0.0, 1.0, 100, endpoint=False)
        kin = np.arange(50 * 3, dtype=np.float32).reshape(50, 3)
        kin_ts = np.linspace(0.0, 1.0, 50, endpoint=False)
        session.append("emg", emg, emg_ts)
        session.append("kin", kin, kin_ts)
        session.save_meta("AlignedTest")
        path = session.path

        # 0.2s windows, 0.2s hop, no overlap → 5 windows
        windows = list(iter_aligned_windows(
            [str(path)], "emg", ["kin"], 0.2, 0.2, align_window_samples=1,
        ))
        shutil.rmtree(path, ignore_errors=True)

    assert len(windows) == 5
    for emg_w, aligned, t in windows:
        # window is channels-first: shape == (n_channels, win_samples)
        assert emg_w.shape == (2, 20)
        assert t.shape == (20,)
        assert "kin" in aligned
        assert aligned["kin"].shape == (3,)  # averaged → 1-D over channels


def test_iter_aligned_windows_skips_session_missing_stream():
    """If a session lacks an aligned stream, the whole session is skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        # Session with only emg, no kin
        session = Session(base_path=tmp)
        session.init_stream("emg", StreamInfo(n_channels=1, fs=100.0, dtype=np.dtype("float32")))
        session.append("emg", np.zeros((100, 1), dtype=np.float32),
                       np.linspace(0.0, 1.0, 100, endpoint=False))
        session.save_meta("MissingKin")
        path = session.path

        windows = list(iter_aligned_windows(
            [str(path)], "emg", ["kin"], 0.2, 0.2,
        ))
        shutil.rmtree(path, ignore_errors=True)

    assert windows == []


def test_iter_aligned_windows_rejects_bad_args():
    import pytest
    with pytest.raises(ValueError, match="win_seconds"):
        list(iter_aligned_windows([], "a", ["b"], 0.0, 0.1))
    with pytest.raises(ValueError, match="hop_seconds"):
        list(iter_aligned_windows([], "a", ["b"], 0.2, 0.0))
    with pytest.raises(ValueError, match="align_window_samples"):
        list(iter_aligned_windows([], "a", ["b"], 0.2, 0.1, align_window_samples=0))


def test_iter_aligned_windows_averages_exactly_N_samples():
    """`align_window_samples=N` averages exactly N samples (not N+1).

    Verified by giving kin a unit ramp and checking the mean equals the
    arithmetic mean of N consecutive integers around the midpoint.
    """
    with tempfile.TemporaryDirectory() as tmp:
        session = Session(base_path=tmp)
        session.init_stream("emg", StreamInfo(n_channels=1, fs=100.0, dtype=np.dtype("float32")))
        session.init_stream("kin", StreamInfo(n_channels=1, fs=100.0, dtype=np.dtype("float32")))
        # Aligned timestamps so primary[i] and kin[i] match exactly.
        ts = np.linspace(0.0, 1.0, 100, endpoint=False)
        session.append("emg", np.zeros((100, 1), dtype=np.float32), ts)
        # kin[i] = i (a ramp). Easy to verify the average.
        session.append("kin", np.arange(100, dtype=np.float32).reshape(100, 1), ts)
        session.save_meta("AvgN")
        path = session.path

        # win=0.2s @ 100Hz = 20 samples. First window midpoint at i=10.
        # N=10 → samples [5..15) (n_left=5, n_right=5) → mean = 9.5
        first_n10 = next(iter_aligned_windows(
            [str(path)], "emg", ["kin"], 0.2, 0.2, align_window_samples=10,
        ))
        # N=11 → samples [5..16) → mean = 10.0
        first_n11 = next(iter_aligned_windows(
            [str(path)], "emg", ["kin"], 0.2, 0.2, align_window_samples=11,
        ))
        shutil.rmtree(path, ignore_errors=True)

    _w, aligned10, _t = first_n10
    _w, aligned11, _t = first_n11
    assert aligned10["kin"].shape == (1,)
    # N=10: mean of [5,6,...,14] = 9.5
    assert np.isclose(aligned10["kin"][0], 9.5)
    # N=11: mean of [5,6,...,15] = 10.0
    assert np.isclose(aligned11["kin"][0], 10.0)


def test_save_meta_persists_class_names():
    """class_names passed to save_meta land in meta.json and round-trip via
    open_session_store — old sessions become self-describing."""
    with tempfile.TemporaryDirectory() as tmp:
        session = Session(base_path=tmp)
        session.init_stream("emg", StreamInfo(n_channels=1, fs=100.0, dtype=np.dtype("float32")))
        session.append("emg", np.zeros((10, 1), dtype=np.float32),
                       np.linspace(0.0, 0.1, 10, endpoint=False))
        session.save_meta("Persisted", class_names=["Rest", "Fist", "Pinch"])
        path = session.path

        # Read back via open_session_store
        loaded = open_session_store(path)
        assert loaded.class_names == ["Rest", "Fist", "Pinch"]

        shutil.rmtree(path, ignore_errors=True)


def test_save_meta_omits_class_names_when_none():
    """No class_names → the meta.json key is absent (not an empty list)."""
    import json
    with tempfile.TemporaryDirectory() as tmp:
        session = Session(base_path=tmp)
        session.init_stream("emg", StreamInfo(n_channels=1, fs=50.0, dtype=np.dtype("float32")))
        session.append("emg", np.zeros((5, 1), dtype=np.float32),
                       np.array([0.0, 0.02, 0.04, 0.06, 0.08]))
        session.save_meta("NoNames")  # no class_names arg
        meta = json.loads((session.path / "meta.json").read_text())
        assert "class_names" not in meta
        loaded = open_session_store(session.path)
        assert loaded.class_names == []
        shutil.rmtree(session.path, ignore_errors=True)


def test_sessions_in_same_second_get_distinct_folders(monkeypatch):
    """Two sessions created within the same wall-clock second must not share a
    folder — otherwise the first session's pack_to_zip() (which rmtree's its
    own folder on a daemon thread) can wipe the second recording's data."""
    import myogestic.session._core as sc

    monkeypatch.setattr(sc.time, "strftime", lambda *a, **k: "2026-06-03_14-30-05")
    with tempfile.TemporaryDirectory() as tmp:
        s1 = Session(base_path=tmp)
        s2 = Session(base_path=tmp)
        assert s1.path != s2.path
        assert s1.path.exists() and s2.path.exists()


def test_pack_does_not_delete_a_concurrent_same_second_session(monkeypatch):
    """Reproduce the Stop-then-immediately-Record data-loss scenario: with a
    shared (second-resolution) folder name, s1.pack_to_zip() deleted s2's data.
    Distinct folders keep s2 intact."""
    import myogestic.session._core as sc

    monkeypatch.setattr(sc.time, "strftime", lambda *a, **k: "2026-06-03_14-30-05")
    with tempfile.TemporaryDirectory() as tmp:
        info = StreamInfo(n_channels=2, fs=64.0, dtype=np.dtype("float32"))

        s1 = Session(base_path=tmp)
        s1.init_stream("emg", info)
        s1.append("emg", np.ones((8, 2), np.float32), np.arange(8, dtype=np.float64))
        s1.save_meta("FirstSession")

        s2 = Session(base_path=tmp)
        s2.init_stream("emg", info)
        s2.append("emg", np.full((8, 2), 2.0, np.float32), np.arange(8, dtype=np.float64))

        # s1 finalises (rmtree's s1.path). s2 must be untouched.
        s1.pack_to_zip()

        assert s2.path.exists()
        assert np.array(s2.stores["emg"]).shape == (8, 2)
        assert np.allclose(np.array(s2.stores["emg"]), 2.0)
