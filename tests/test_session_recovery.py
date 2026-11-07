"""A process killed before Stop leaves a readable, packable take on disk."""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

from myogestic import App
from myogestic.session import Session, open_session_store
from myogestic.stream import StreamInfo
from myogestic.widgets import SessionManager


def test_crashed_take_recovers_packs_and_reads_in_session_manager(tmp_path, imgui_frame):
    """No stop, freeze or finalizer runs in the recording process."""
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
import sys
import numpy as np
from myogestic import App
from myogestic.session._core import EVENT_CHUNK_ROWS
from myogestic.sources import SyntheticSource
from myogestic.stream import Stream

app = App("crashed-app")
app.ctx.participant = "P-001"
app.ctx.class_names = ["Rest", "Fist"]
stream = Stream("emg", source=SyntheticSource(n_channels=2, fs=100), window_ms=100)
stream.reconnect()
app.streams(stream)
app.start_recording(base_path=sys.argv[1])
session = app.ctx.session
session.append("emg", np.arange(40, dtype=np.float32).reshape(20, 2), np.arange(20) / 100)
for i in range(EVENT_CHUNK_ROWS):
    session.append_event("prediction.class", [1], i / 10, channel_names=["class"])
session.append_event("prediction.class", [2], 999)  # still only in RAM
os._exit(0)
""",
            str(tmp_path),
        ],
        check=True,
        timeout=30,
    )
    (folder,) = (tmp_path / "P-001" / "recordings").iterdir()
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["finished"] is False
    assert meta["app_name"] == "crashed-app"
    assert meta["class_names"] == ["Rest", "Fist"]
    assert meta["event_streams"] == ["prediction.class"]
    expected = np.arange(40, dtype=np.float32).reshape(20, 2)
    with open_session_store(folder) as loaded:
        np.testing.assert_array_equal(loaded.stores["emg"][:], expected)
        assert loaded.stream_info("emg").fs == 100

    manager = SessionManager(str(tmp_path))

    def selected_path():
        manager.select_all("P-001")
        selections = []
        imgui_frame(lambda: selections.append(manager.ui(participant="P-001")))
        return selections[0].paths

    assert selected_path() == [str(folder.resolve())]
    from myogestic.session import recover_session
    from myogestic.session._core import EVENT_CHUNK_ROWS

    archive = recover_session(folder)
    assert archive.name.endswith(".mg.zip")
    assert not folder.exists()
    assert selected_path() == [str(archive.resolve())]
    with zipfile.ZipFile(archive) as packed:
        saved_meta = json.loads(packed.read("meta.json"))
    assert saved_meta["finished"] is False  # packing cannot make a crashed take complete
    assert saved_meta["duration_s"] == pytest.approx(0.19)
    assert manager.selection().n_selected == 1
    with open_session_store(archive) as loaded:
        np.testing.assert_array_equal(loaded.stores["emg"][:], expected)
        np.testing.assert_array_equal(loaded.ts_stores["emg"][:], np.arange(20) / 100)
        assert loaded.event_streams == ("prediction.class",)
        np.testing.assert_array_equal(
            loaded.stores["prediction.class"][:], np.ones((EVENT_CHUNK_ROWS, 1))
        )


def test_low_level_take_checkpoints_metadata_before_stop(tmp_path):
    session = Session(str(tmp_path), participant="P-002")
    assert json.loads((session.path / "meta.json").read_text())["finished"] is False
    session.init_stream("emg", StreamInfo(n_channels=2, fs=100))
    session.append("emg", np.ones((2, 2)), np.array([1.0, 2.0]))
    with open_session_store(session.path) as loaded:
        np.testing.assert_array_equal(loaded.stores["emg"][:], np.ones((2, 2)))


def test_stop_marks_take_finished_and_updates_metadata(tmp_path):
    app = App("finished-app")
    app.ctx.class_names = ["Rest"]
    app.start_recording(base_path=str(tmp_path))
    session = app.ctx.session
    assert json.loads((session.path / "meta.json").read_text())["finished"] is False
    session.init_stream("emg", StreamInfo(n_channels=1, fs=10))
    session.append("emg", np.ones((2, 1)), np.array([1.0, 2.0]))
    session.add_label(0, timestamp=1.0)
    app.stop_recording(wait=True)
    with zipfile.ZipFile(session.path) as packed:
        meta = json.loads(packed.read("meta.json"))
    assert meta["finished"] is True
    assert meta["duration_s"] == 1
    assert meta["class_seconds"] == {"Rest": 1}


def test_appends_and_event_flushes_do_not_write_metadata(tmp_path, monkeypatch):
    from myogestic.session._core import EVENT_CHUNK_ROWS

    session = Session(str(tmp_path))
    session.init_stream("emg", StreamInfo(n_channels=1, fs=100))
    session.append_event("prediction", [1], 0)  # declaration may checkpoint once
    metadata_writes = []
    write_text = Path.write_text

    def capture(path, *args, **kwargs):
        if path.name.startswith(("meta.json", "labels.json")):
            metadata_writes.append(path)
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", capture)
    for _ in range(3):
        session.append("emg", np.ones((2, 1)), np.array([1.0, 2.0]))
    for i in range(EVENT_CHUNK_ROWS):
        session.append_event("prediction", [1], i + 1)
    assert metadata_writes == []


def test_recovery_keeps_take_context_and_folder_on_pack_failure(tmp_path, monkeypatch):
    from myogestic.session import recover_session

    session = Session(str(tmp_path), participant="P-003")
    session.name = "Interrupted"
    session.extras["calibration"] = {"mvc": 42}
    session.init_stream("emg", StreamInfo(n_channels=1, fs=10))
    session.append("emg", np.ones((2, 1)), np.array([1.0, 2.0]))
    session.add_label(0, timestamp=1.0)
    session.save_meta(
        "context-app", class_names=["Rest"], class_codes={"Rest": "R"}, finished=False
    )
    folder = session.path
    session.close()  # release handles without stop, freeze, or packing
    pack = Session.pack_to_zip

    def fail(_session):
        raise OSError("disk unavailable")

    monkeypatch.setattr(Session, "pack_to_zip", fail)
    with pytest.raises(OSError, match="disk unavailable"):
        recover_session(folder)
    assert folder.is_dir()
    with open_session_store(folder) as loaded:
        np.testing.assert_array_equal(loaded.stores["emg"][:], np.ones((2, 1)))

    monkeypatch.setattr(Session, "pack_to_zip", pack)
    archive = recover_session(folder)
    with zipfile.ZipFile(archive) as packed:
        meta = json.loads(packed.read("meta.json"))
    assert meta["finished"] is False
    assert meta["class_codes"] == {"Rest": "R"}
    assert meta["class_seconds"] == {"Rest": 1}
    assert archive.name.endswith("_R_Interrupted.mg.zip")
    with open_session_store(archive) as loaded:
        assert loaded.participant == "P-003"
        assert loaded.name == "Interrupted"
        assert loaded.extras == {"calibration": {"mvc": 42}}
        assert loaded.class_names == ["Rest"]
        assert len(loaded.label_track) == 1
    with pytest.raises(ValueError, match="unpacked session folder"):
        recover_session(archive)


def test_interrupted_metadata_checkpoint_leaves_previous_json_readable(tmp_path, monkeypatch):
    from myogestic.session import _core

    session = Session(str(tmp_path))
    session.init_stream("emg", StreamInfo(n_channels=1, fs=10))
    session.append("emg", np.ones((2, 1)), np.array([1.0, 2.0]))
    previous = (session.path / "meta.json").read_bytes()
    replace = _core.os.replace

    def fail_before_commit(source, target):
        if Path(target).name == "meta.json":
            raise OSError("interrupted checkpoint")
        replace(source, target)

    monkeypatch.setattr(_core.os, "replace", fail_before_commit)
    with pytest.raises(OSError, match="interrupted checkpoint"):
        session.save_meta("crashed", finished=False)
    assert (session.path / "meta.json").read_bytes() == previous
    with open_session_store(session.path) as loaded:
        np.testing.assert_array_equal(loaded.stores["emg"][:], np.ones((2, 1)))


@pytest.mark.parametrize("convention", [None, "legacy-unsigned"])
def test_packing_an_older_folder_preserves_its_pose_convention(tmp_path, convention):
    from myogestic.session import recover_session

    session = Session(str(tmp_path))
    session.init_stream("emg", StreamInfo(n_channels=1, fs=10))
    session.append("emg", np.ones((2, 1)), np.array([1.0, 2.0]))
    session.save_meta("older-app")
    folder = session.path
    session.close()
    meta = json.loads((folder / "meta.json").read_text())
    meta.pop("schema_version")
    meta.pop("finished")
    if convention is None:
        meta.pop("pose_convention")
    else:
        meta["pose_convention"] = convention
    (folder / "meta.json").write_text(json.dumps(meta))

    with zipfile.ZipFile(recover_session(folder)) as packed:
        recovered = json.loads(packed.read("meta.json"))
    assert recovered.get("pose_convention") == convention
    assert ("pose_convention" in recovered) is (convention is not None)
