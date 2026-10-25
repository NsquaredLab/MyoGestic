"""Sample-clock durations, backwards-compatible totals, and recording layout."""

import json
import zipfile
from dataclasses import FrozenInstanceError

import numpy as np
import pytest
from imgui_bundle import imgui

from myogestic.core import App, Context
from myogestic.session import Session, iter_labeled_windows
from myogestic.stream import StreamInfo
from myogestic.widgets import RecordingControls
from myogestic.widgets.common import ui_px
from myogestic.widgets.training._session_state import scan_sessions


def _session(tmp_path, timestamps=(10.0, 12.0, 20.0)):
    session = Session(str(tmp_path))
    session.init_stream("emg", StreamInfo(n_channels=1, fs=10.0))
    if timestamps:
        session.append("emg", np.zeros((len(timestamps), 1)), np.array(timestamps))
    return session


def test_meta_has_duration_and_class_seconds(tmp_path, monkeypatch):
    # Use the synchronous finalizer to inspect the archive deterministically.
    monkeypatch.setattr("myogestic._browser.IS_BROWSER", True)
    session = _session(tmp_path)
    session.add_label(0, timestamp=10.0)
    session.add_label(1, timestamp=14.0)
    app = App("timing")
    app.ctx.session = session
    app.ctx.class_names = ["Rest", "Fist"]
    app.ctx.state = "recording"
    app.stop_recording()
    with zipfile.ZipFile(session.path) as archive:
        meta = json.loads(archive.read("meta.json"))
    assert meta["duration_s"] == 10.0
    assert isinstance(meta["duration_s"], float)
    assert meta["class_seconds"] == {"Rest": 4.0, "Fist": 6.0}
    assert meta["schema_version"] == 3


@pytest.mark.parametrize(
    ("labels", "names", "timestamps", "expected"),
    [
        ([], ["Rest", "Fist"], (10.0, 20.0), None),
        ([(0, 5.0), (1, 14.0)], ["Rest", "Fist"], (10.0, 20.0), {"Rest": 4.0, "Fist": 6.0}),
        ([(0, 5.0), (-1, 12.0), (1, 18.0)], ["Rest", "Fist"], (10.0, 20.0), {"Rest": 2.0, "Fist": 2.0}),
        ([(0, 2.0), (-1, 5.0), (1, 25.0)], ["Rest", "Fist"], (10.0, 20.0), {}),
        ([(0, 10.0)], [], (10.0, 20.0), None),
        ([(0, 10.0)], ["Rest"], (), {}),
        ([(0, 10.0)], ["Rest"], (10.0,), {}),
        ([(7, 10.0)], ["Rest"], (10.0, 20.0), {}),
        ([(0.0, 10.0)], ["Rest"], (10.0, 20.0), {"Rest": 10.0}),
        ([(0.5, 10.0)], ["Rest"], (10.0, 20.0), {}),
    ],
)
def test_class_seconds_edge_cases(tmp_path, labels, names, timestamps, expected):
    with _session(tmp_path, timestamps) as session:
        for index, timestamp in labels:
            session.add_label(index, timestamp=timestamp)
        session.save_meta("edge-cases", class_names=names)
        meta = json.loads((session.path / "meta.json").read_text())
    assert meta["duration_s"] == (timestamps[-1] - timestamps[0] if timestamps else 0.0)
    if expected is None:
        assert "class_seconds" not in meta
    else:
        assert meta["class_seconds"] == expected


def test_duration_uses_first_stream_with_samples(tmp_path):
    with _session(tmp_path, ()) as session:
        for name, timestamps in [("second", [10.0, 13.0]), ("third", [0.0, 100.0])]:
            session.init_stream(name, StreamInfo(n_channels=1, fs=10.0))
            session.append(name, np.zeros((2, 1)), np.array(timestamps))
        session.save_meta("streams")
        assert json.loads((session.path / "meta.json").read_text())["duration_s"] == 3.0


def test_recorded_time_sums_folder(tmp_path):
    from myogestic.session import RecordedTime, recorded_time

    for packed in (False, True):
        with _session(tmp_path) as session:
            session.add_label(0, timestamp=10.0)
            session.add_label(1, timestamp=14.0)
            session.save_meta("totals", class_names=["Rest", "Fist"])
            if packed:
                session.pack_to_zip().rename(tmp_path / "renamed.zip")
    # A nested participant and unrelated/corrupt files are not direct takes.
    with _session(tmp_path / "nested") as nested:
        nested.save_meta("nested")
    (tmp_path / "broken.zip").write_text("not an archive")
    (tmp_path / "notes.txt").write_text("not a session")
    assert recorded_time(tmp_path) == RecordedTime(2, 20.0, {"Rest": 8.0, "Fist": 12.0})
    assert recorded_time(str(tmp_path)) == recorded_time(tmp_path)
    assert recorded_time(tmp_path / "missing") == RecordedTime(0, 0.0, {})
    with pytest.raises(FrozenInstanceError):
        recorded_time(tmp_path).takes = 0


def test_old_session_without_seconds(tmp_path):
    from myogestic.session import RecordedTime, recorded_time

    with _session(tmp_path, tuple(np.arange(10.0, 20.0, 0.1))) as session:
        # A legacy metadata file has no duration fields; the arrays still train.
        (session.path / "meta.json").write_text(json.dumps({
            "streams": {"emg": {"n_channels": 1, "fs": 10.0, "dtype": "float32"}},
            "class_names": ["Rest"],
        }))
        (session.path / "labels.json").write_text(json.dumps([
            {"timestamp": 10.0, "class_index": 0},
        ]))
        rows = scan_sessions(str(tmp_path))
        assert len(rows) == 1
        assert rows[0]["duration_s"] == 0.0
        assert rows[0]["class_seconds"] == {}
        assert recorded_time(tmp_path) == RecordedTime(1, 0.0, {})
        assert list(iter_labeled_windows([str(session.path)], "emg", window_ms=200, hop_ms=100))


@pytest.mark.parametrize(("width", "n_gestures", "n_cols"), [(700, 4, 4), (380, 2, 2), (300, 4, 2)])
@pytest.mark.parametrize("state", ["idle", "recording"])
def test_recording_controls_layout(imgui_frame, monkeypatch, width, n_gestures, n_cols, state):
    ctx = Context(state=state)
    controls = RecordingControls(["Rest", "Fist", "Open", "Pinch"][:n_gestures],
                                 on_record=lambda: None, on_stop=lambda: None)
    real_button = imgui.button
    boxes = {}
    available = []

    def button(label, size=imgui.ImVec2(0, 0)):
        clicked = real_button(label, size)
        if "##rec_" in label:
            lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            boxes[label.split("##")[1]] = (lo.x, lo.y, hi.x, hi.y)
        return clicked

    monkeypatch.setattr(imgui, "button", button)

    def draw():
        imgui.begin_child("layout", imgui.ImVec2(width, 400))
        available.append(imgui.get_content_region_avail().x)
        controls.ui(ctx)
        imgui.end_child()

    imgui_frame(draw)
    gestures = [boxes[f"rec_gesture{i}"] for i in range(n_gestures)]
    assert len({box[1] for box in gestures}) == n_gestures // n_cols
    assert len({box[0] for box in gestures}) == n_cols
    for start in range(0, n_gestures, n_cols):
        row = gestures[start:start + n_cols]
        assert len({box[1] for box in row}) == 1
        assert row[-1][2] - row[0][0] == pytest.approx(available[0], abs=1)
    widths = [box[2] - box[0] for box in gestures]
    assert widths == pytest.approx([widths[0]] * n_gestures)
    for box in gestures:
        assert box[3] - box[1] == pytest.approx(ui_px(44))
    action = boxes["rec_btn"]
    if state == "idle":
        assert action[3] - action[1] == pytest.approx(ui_px(52))
        assert action[2] - action[0] == pytest.approx(available[0], abs=1)
    else:
        # Stop is right-aligned within the full-width status row.
        assert action[2] <= gestures[-1][2]
        assert action[0] >= gestures[-1][0]
