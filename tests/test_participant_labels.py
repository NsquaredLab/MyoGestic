"""Participant labels stay safe, survive packing, and gate recording when requested."""

import json
import re
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
from imgui_bundle import imgui

import myogestic.session as session_api
import myogestic.session._core as session_core
from myogestic import App, Context
from myogestic.session import Session, open_session_store
from myogestic.stream import Stream, StreamInfo
from myogestic.widgets import RecordButton, RecordingControls

_TIMESTAMP = "2026-10-24_15-12-03"


@pytest.fixture
def frozen_clock(monkeypatch):
    """Keep every take in the same wall-clock second."""
    monkeypatch.setattr(session_core.time, "strftime", lambda *args: _TIMESTAMP)


class _Source:
    """A connected stream without a background acquisition thread."""

    def connect(self):
        return StreamInfo(n_channels=2, fs=100.0)

    def read(self):
        return None, None

    def disconnect(self):
        pass


def _connect(app):
    stream = Stream("emg", source=_Source(), window_ms=100)
    app.streams(stream)
    assert stream.reconnect()
    return stream


def test_labelled_path_with_and_without_id(tmp_path, frozen_clock):
    assert session_api.labelled_path("sessions", "P-014") == Path(
        "sessions/P-014/P-014_2026-10-24_15-12-03"
    )
    assert session_api.labelled_path("sessions", "P-014", suffix="model.joblib") == Path(
        "sessions/P-014/P-014_2026-10-24_15-12-03_model.joblib"
    )
    assert session_api.labelled_path("sessions") == Path("sessions/2026-10-24_15-12-03")
    assert session_api.labelled_path("sessions", suffix="model.joblib") == Path(
        "sessions/2026-10-24_15-12-03_model.joblib"
    )
    session_api.labelled_path(tmp_path / "preview", "P-014")
    assert list(tmp_path.iterdir()) == [], "a preview must not reserve a folder"


@pytest.mark.parametrize(
    ("typed", "slug"), [(" p/014 ", "p-014"), ("../x", "x"), ("Jörg", "J-rg")]
)
def test_labelled_path_slugs_the_id(typed, slug, frozen_clock):
    path = session_api.labelled_path("sessions", typed)
    assert path == Path("sessions") / slug / f"{slug}_{_TIMESTAMP}"
    assert len(path.parent.relative_to("sessions").parts) == 1
    assert all(fragment not in path.parent.name for fragment in ("/", "\\", ".."))


@pytest.mark.parametrize("participant", ["", " ... / "])
def test_session_without_participant_keeps_legacy_layout(tmp_path, participant):
    session = Session(str(tmp_path), participant=participant) if participant else Session(str(tmp_path))
    assert session.path.parent == tmp_path
    assert re.fullmatch(r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d_[0-9a-f]{8}", session.path.name)


def test_session_with_participant_nests_and_labels(tmp_path, frozen_clock):
    session = Session(str(tmp_path), participant="P-014")
    assert session.path == tmp_path / "P-014" / f"P-014_{_TIMESTAMP}"
    assert session.participant == "P-014"
    assert session.path.is_dir()


def test_session_persists_the_slugged_id(tmp_path, frozen_clock):
    session = Session(str(tmp_path), participant=" ../p/014 ")
    assert session.participant == "p-014"
    assert session.path == tmp_path / "p-014" / f"p-014_{_TIMESTAMP}"
    session.save_meta("test")
    assert json.loads((session.path / "meta.json").read_text())["participant"] == "p-014"


@pytest.mark.parametrize("name", ["", "fist day 2"])
def test_same_second_takes_do_not_collide(tmp_path, frozen_clock, name):
    first = Session(str(tmp_path), participant="P-014")
    first.name = name
    first.save_meta("first")
    second = Session(str(tmp_path), participant="P-014")
    assert first.path.name == f"P-014_{_TIMESTAMP}"
    assert second.path.name == f"P-014_{_TIMESTAMP}-2"
    second.init_stream("emg", StreamInfo(n_channels=2, fs=100.0))
    second.append("emg", np.ones((4, 2), dtype=np.float32), np.arange(4.0))
    second.save_meta("second")

    first_folder = first.path
    first_zip = first.pack_to_zip()
    assert not first_folder.exists()
    assert second.path.is_dir(), "an old pack must never delete the next take"
    np.testing.assert_array_equal(np.asarray(second.stores["emg"]), np.ones((4, 2)))
    third = Session(str(tmp_path), participant="P-014")
    assert third.path.name == f"P-014_{_TIMESTAMP}-3"
    third.save_meta("third")
    archives = [first_zip, second.pack_to_zip(), third.pack_to_zip()]
    assert len(set(archives)) == 3
    assert all(path.exists() for path in archives)


def test_session_retries_a_racing_folder_creation(tmp_path, frozen_clock, monkeypatch):
    """Another recorder can reserve a candidate between the check and mkdir."""
    candidate = tmp_path / "P-014" / f"P-014_{_TIMESTAMP}"
    mkdir = Path.mkdir
    raced = False

    def competing_mkdir(path, *args, **kwargs):
        nonlocal raced
        if path == candidate and not raced:
            raced = True
            mkdir(path)
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", competing_mkdir)
    session = Session(str(tmp_path), participant="P-014")
    assert raced
    assert session.path.name == f"P-014_{_TIMESTAMP}-2"
    assert candidate.is_dir()


def test_meta_records_participant_not_names(tmp_path, monkeypatch):
    home = tmp_path / "home"
    key = home / "myogestic" / "participant-key.csv"
    key.parent.mkdir(parents=True)
    key.write_text("id,first_name,family_name,created\nP-014,Jane,Doe,2026-10-24\n")
    monkeypatch.setattr(Path, "home", lambda: home)
    app = App("test")
    stream = _connect(app)
    app.ctx.participant = "P-014"
    base = tmp_path / "sessions"
    app.start_recording(str(base))
    app.ctx.session.append("emg", np.zeros((4, 2), dtype=np.float32), np.arange(4.0))
    app.stop_recording()
    deadline = time.monotonic() + 10
    archives = list(base.rglob("*.session.zip"))
    while not archives and time.monotonic() < deadline:
        time.sleep(0.01)
        archives = list(base.rglob("*.session.zip"))
    assert len(archives) == 1, "recording was never packed"
    assert stream._session is None
    with zipfile.ZipFile(archives[0]) as archive:
        assert json.loads(archive.read("meta.json"))["participant"] == "P-014"
        for name in archive.namelist():
            assert "Jane" not in name and "Doe" not in name
            assert b"Jane" not in archive.read(name) and b"Doe" not in archive.read(name)
    assert all("Jane" not in str(path) and "Doe" not in str(path) for path in base.rglob("*"))
    with open_session_store(archives[0]) as loaded:
        assert loaded.participant == "P-014"

    legacy = Session(str(base))
    legacy.init_stream("emg", StreamInfo(n_channels=2, fs=100.0))
    legacy.save_meta("old")
    assert "participant" not in json.loads((legacy.path / "meta.json").read_text())
    with open_session_store(legacy.path) as loaded:
        assert loaded.participant == ""
    with open_session_store(legacy.pack_to_zip()) as loaded:
        assert loaded.participant == ""


def test_require_participant_refuses_without_id(tmp_path):
    app = App("t", require_participant=True)
    stream = _connect(app)
    assert app.ctx.require_participant is True
    assert app.ctx.participant == ""
    app.start_recording(str(tmp_path))
    assert app.ctx.state == "idle"
    assert app.ctx.session is None and stream._session is None
    assert list(tmp_path.iterdir()) == []
    assert app.ctx.status_message == "Set a participant ID before recording."
    assert any("participant ID" in line for line in app.ctx.logs)

    app.ctx.participant = "P-014"
    app.start_recording(str(tmp_path))
    assert app.ctx.state == "recording"
    assert app.ctx.session.path.parent == tmp_path / "P-014"
    assert stream._session is app.ctx.session
    app.discard_recording()


@pytest.mark.parametrize("widget_class", [RecordButton, RecordingControls])
def test_record_button_disabled_when_gated(imgui_frame, monkeypatch, widget_class):
    """Real mouse clicks cannot activate gated Record, and work once an ID is set."""
    ctx = Context()
    ctx.require_participant = True
    ctx.participant = ""
    calls = []
    widget = widget_class(on_record=lambda: calls.append("record"), on_stop=lambda: None)
    record_center = []
    button = imgui.button

    def capture_button(label, *args):
        clicked = button(label, *args)
        if "  Record" in label:
            lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            record_center[:] = [(lo.x + hi.x) / 2, (lo.y + hi.y) / 2]
        return clicked

    monkeypatch.setattr(imgui, "button", capture_button)
    def draw():
        widget.ui(ctx)

    imgui_frame(draw)
    imgui_frame(draw)
    io = imgui.get_io()

    def click():
        io.add_mouse_pos_event(*record_center)
        imgui_frame(draw)
        io.add_mouse_button_event(0, True)
        imgui_frame(draw)
        io.add_mouse_button_event(0, False)
        imgui_frame(draw)

    click()
    assert calls == []
    ctx.participant = "P-014"
    click()
    assert calls == ["record"]
