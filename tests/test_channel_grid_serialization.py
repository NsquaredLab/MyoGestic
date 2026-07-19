"""Round-trip StreamInfo.channel_grids (+ channel_names) through session save/load."""

import json

import numpy as np

from myogestic.session import Session, open_session_store
from myogestic.stream import ChannelGrid, StreamInfo


def test_channel_grids_round_trip(tmp_path):
    """A populated channel_grids survives save_meta -> pack -> open_session_store."""
    info = StreamInfo(n_channels=4, fs=8.0, channel_grids=[ChannelGrid("IN1", [[0, 1], [2, 3]])])
    s = Session(base_path=str(tmp_path))
    s.init_stream("emg", info)
    s.append("emg", np.zeros((2, 4), np.float32), np.arange(2, dtype=np.float64))
    s.save_meta(app_name="t")
    zip_path = s.pack_to_zip()
    s.close()

    with open_session_store(zip_path) as back_session:
        back = back_session.stream_info("emg")
        assert back.channel_grids == info.channel_grids  # frozen dataclass equality
        assert back.channel_names is None  # existing field still round-trips


def test_channel_names_round_trip(tmp_path):
    """channel_names now round-trips too (save_meta previously omitted it)."""
    info = StreamInfo(n_channels=2, fs=8.0, channel_names=["a", "b"])
    s = Session(base_path=str(tmp_path))
    s.init_stream("emg", info)
    s.append("emg", np.zeros((2, 2), np.float32), np.arange(2, dtype=np.float64))
    s.save_meta(app_name="t")
    zip_path = s.pack_to_zip()
    s.close()

    with open_session_store(zip_path) as back_session:
        back = back_session.stream_info("emg")
        assert back.channel_names == ["a", "b"]


def test_old_session_without_grids_loads_as_none(tmp_path):
    """A session whose meta.json predates channel_grids still loads (None)."""
    s = Session(base_path=str(tmp_path))
    info = StreamInfo(n_channels=2, fs=8.0)
    s.init_stream("emg", info)
    s.append("emg", np.zeros((2, 2), np.float32), np.arange(2, dtype=np.float64))
    s.save_meta(app_name="t")

    # Overwrite meta.json to look like an old, pre-channel_grids session: the
    # per-stream dict has no "channel_grids" (and no "channel_names") key at all.
    meta_path = s.path / "meta.json"
    meta = json.loads(meta_path.read_text())
    stream_meta = meta["streams"]["emg"]
    stream_meta.pop("channel_grids", None)
    stream_meta.pop("channel_names", None)
    meta_path.write_text(json.dumps(meta))
    session_path = s.path
    s.close()

    with open_session_store(session_path) as back_session:
        back = back_session.stream_info("emg")
        assert back.channel_grids is None
        assert back.channel_names is None


def test_tolerant_decode_missing_channel_grids_key(tmp_path):
    """open_session_store decodes a streams-entry lacking channel_grids as None
    directly (the tolerant `info.get("channel_grids")` path), independent of
    save_meta ever having omitted it."""
    session_dir = tmp_path / "raw_session"
    session_dir.mkdir()
    meta = {
        "app_name": "t",
        "created": "2026-01-01T00:00:00",
        "streams": {
            "emg": {"n_channels": 2, "fs": 8.0, "dtype": "float32"},
        },
    }
    (session_dir / "meta.json").write_text(json.dumps(meta))

    import zarr

    zarr.open_array(
        str(session_dir / "emg.zarr"), mode="w", shape=(0, 2), chunks=(8, 2), dtype="float32"
    )
    zarr.open_array(
        str(session_dir / "emg_timestamps.zarr"), mode="w", shape=(0,), chunks=(8,), dtype="float64"
    )

    with open_session_store(session_dir) as back_session:
        back = back_session.stream_info("emg")
        assert back.channel_grids is None
