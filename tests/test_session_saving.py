"""A take stays trainable when its folder is replaced by the saved archive."""

import json
import shutil
import zipfile
from types import SimpleNamespace

import pytest
from imgui_bundle import imgui

from myogestic import App, _browser, core
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PipelinePanel
from myogestic.session import Session
from myogestic.widgets import SessionManager
from myogestic.widgets.common import muted
from myogestic.widgets.training import _session_state
from myogestic.widgets.training._session_state import get_state, scan_sessions


@pytest.fixture(autouse=True)
def isolated_sessions(monkeypatch):
    monkeypatch.setattr(_session_state, "_states", {})


@pytest.mark.parametrize("suffix", ["", "_Rest+Fist_Practice"])
@pytest.mark.parametrize("packing", [True, False])
def test_scan_hides_a_folder_with_a_packing_or_packed_sibling(tmp_path, suffix, packing):
    folder = tmp_path / "take"
    folder.mkdir()
    (folder / "meta.json").write_text("{}")
    archive = tmp_path / f"take{suffix}.session.zip"
    if packing:
        archive.with_suffix(".zip.tmp").touch()
        assert scan_sessions(str(tmp_path)) == []
    else:
        with zipfile.ZipFile(archive, "w") as saved:
            saved.writestr("meta.json", "{}")
        assert [row["path"] for row in scan_sessions(str(tmp_path))] == [str(archive.resolve())]


@pytest.mark.parametrize("read_summary_first", [True, False])
@pytest.mark.parametrize("selected", [True, False])
def test_selection_follows_a_folder_into_its_packed_archive(
    tmp_path,
    imgui_frame,
    read_summary_first,
    selected,
):
    session = Session(str(tmp_path))
    session.name = "Practice"
    session.add_label(0, timestamp=0.0)
    session.add_label(0, timestamp=10.0)
    session.save_meta("test", class_names=["Rest"])
    manager = SessionManager(str(tmp_path))
    state = get_state(manager._widget_id)
    state.sessions = scan_sessions(str(tmp_path))
    state.sessions[0]["selected"] = selected
    archive = session.pack_to_zip()

    if read_summary_first:
        summary = manager.selection()
        assert [row["path"] for row in state.sessions] == [str(archive.resolve())]
        assert summary.n_selected == int(selected)
    results = []
    imgui_frame(lambda: results.append(manager.ui()))
    assert results[0].paths == ([str(archive.resolve())] if selected else [])
    assert [row["path"] for row in state.sessions] == [str(archive.resolve())]
    assert len(state.sessions) == 1
    assert state.sessions[0]["selected"] is selected
    assert state.sessions[0]["session_name"] == "Practice"


@pytest.mark.parametrize("read_summary_first", [True, False])
def test_vanished_selection_without_a_replacement_drops_out(
    tmp_path,
    imgui_frame,
    read_summary_first,
):
    folder = tmp_path / "removed"
    folder.mkdir()
    (folder / "meta.json").write_text(json.dumps({"class_seconds": {"Rest": 10.0}}))
    manager = SessionManager(str(tmp_path))
    state = get_state(manager._widget_id)
    state.sessions = scan_sessions(str(tmp_path))
    state.sessions[0]["selected"] = True
    shutil.rmtree(folder)

    if read_summary_first:
        summary = manager.selection()
        assert summary.n_selected == summary.n_total == 0
        assert summary.class_seconds == {}
    results = []
    imgui_frame(lambda: results.append(manager.ui()))
    assert results[0].paths == []
    assert state.sessions == []


@pytest.fixture
def deferred_pack(monkeypatch):
    """Pause only thread scheduling; metadata and packing still run for real."""
    queued = []
    monkeypatch.setattr(_browser, "IS_BROWSER", False)
    thread = core.threading.Thread
    monkeypatch.setattr(
        core.threading,
        "Thread",
        lambda **kwargs: (
            thread(**kwargs)
            if "name" in kwargs
            else SimpleNamespace(
                start=lambda: queued.append(kwargs["target"]),
            )
        ),
    )
    return queued


@pytest.mark.parametrize("fails", [False, True])
def test_pending_save_covers_pack_and_clears_on_success_or_failure(
    tmp_path,
    monkeypatch,
    deferred_pack,
    fails,
):
    app = App("saving")
    app.start_recording(base_path=str(tmp_path))
    session = app.ctx.session
    pending_during_pack = []
    pack = session.pack_to_zip

    def finish():
        pending_during_pack.append(bool(getattr(app.ctx, "pending_saves", False)))
        if fails:
            raise OSError("disk unavailable")
        return pack()

    monkeypatch.setattr(session, "pack_to_zip", finish)
    app.stop_recording()
    try:
        assert app.ctx.state == "idle"
        assert getattr(app.ctx, "pending_saves", False)
    finally:
        deferred_pack.pop()()
    assert pending_during_pack == [True]
    assert not app.ctx.pending_saves
    assert ("Pack failed" in app.ctx.status_message) is fails
    assert [row["path"] for row in get_state("Sessions_sessions").sessions if row["selected"]] == [
        str(session.path.resolve())
    ]


def test_saving_stays_pending_until_all_packs_finish(tmp_path, deferred_pack):
    app = App("saving")
    app.start_recording(base_path=str(tmp_path))
    app.stop_recording()
    app.start_recording(base_path=str(tmp_path))
    app.stop_recording()
    first, second = deferred_pack
    deferred_pack.clear()
    try:
        first()
        assert getattr(app.ctx, "pending_saves", False)
    finally:
        second()
    assert not app.ctx.pending_saves


@pytest.mark.parametrize("fails", [False, True])
def test_session_manager_shows_saving_until_pack_finishes(
    tmp_path,
    monkeypatch,
    imgui_frame,
    deferred_pack,
    fails,
):
    app = App("saving")
    app.ctx.participant = "P-014"
    app.start_recording(base_path=str(tmp_path))
    if fails:

        def fail():
            raise OSError("disk unavailable")

        monkeypatch.setattr(app.ctx.session, "pack_to_zip", fail)
    manager = SessionManager(str(tmp_path))
    app.stop_recording()
    captions = []
    text = imgui.text_colored

    def capture(color, label):
        captions.append((label, tuple(color), tuple(muted())))
        text(color, label)

    monkeypatch.setattr(imgui, "text_colored", capture)
    try:
        imgui_frame(lambda: manager.ui(participant="P-014"))
        assert any(
            label == "Saving the last take…" and color == dim for label, color, dim in captions
        )
    finally:
        deferred_pack.pop()()
    captions.clear()
    imgui_frame(lambda: manager.ui(participant="P-014"))
    assert not any("Saving" in label for label, _, _ in captions)


@pytest.mark.parametrize("has_selection", [False, True])
def test_pipeline_panel_disables_train_with_saving_caption(
    tmp_path,
    monkeypatch,
    imgui_frame,
    deferred_pack,
    has_selection,
):
    from myogestic.contracts import TrainingData
    from myogestic.ml import widgets

    app = App("saving")
    pipeline = Pipeline(app)

    @pipeline.train
    def train(data):
        return object()

    if has_selection:
        pipeline.training_data = TrainingData(paths=["older.session.zip"])
    app.start_recording(base_path=str(tmp_path))
    app.stop_recording()
    finish = deferred_pack.pop()
    captions, disabled = [], []
    text = imgui.text_wrapped
    primary = widgets.primary_button

    def capture(label):
        captions.append(label)
        text(label)

    def click(label, *, size):
        primary(label, size=size)
        disabled.append(bool(imgui.get_item_flags() & imgui.ItemFlags_.disabled))
        return True

    monkeypatch.setattr(imgui, "text_wrapped", capture)
    monkeypatch.setattr(widgets, "primary_button", click)
    try:
        imgui_frame(PipelinePanel(pipeline).ui)
        assert disabled == [True]
        assert "Wait until the last take is saved to train." in captions
        assert app.ctx.state == "idle"
    finally:
        finish()


def test_train_follows_a_pack_that_finishes_after_this_frames_selection(
    tmp_path,
    monkeypatch,
    imgui_frame,
    deferred_pack,
):
    from myogestic.ml import widgets

    app = App("saving")
    pipeline = Pipeline(app)
    app.start_recording(base_path=str(tmp_path))
    session = app.ctx.session
    session.save_meta("saving")
    manager = SessionManager(str(tmp_path))
    state = get_state(manager._widget_id)
    state.sessions = scan_sessions(str(tmp_path))
    state.sessions[0]["selected"] = True
    app.stop_recording()
    data = []
    imgui_frame(lambda: data.append(manager.ui()))
    pipeline.training_data = data[0]
    finish = deferred_pack.pop()
    finish()
    assert not app.ctx.pending_saves
    trained_paths = []

    @pipeline.train
    def train(data):
        trained_paths.extend(data.paths)
        return object()

    primary = widgets.primary_button

    def click(label, *, size):
        primary(label, size=size)
        return True

    monkeypatch.setattr(widgets, "primary_button", click)
    imgui_frame(PipelinePanel(pipeline).ui)
    deferred_pack.pop()()
    assert trained_paths == [str(session.path.resolve())]
    assert pipeline.model is not None


def test_stop_then_train_before_metadata_is_written(
    tmp_path,
    monkeypatch,
    imgui_frame,
    deferred_pack,
):
    """A zarr-only pending take stays hidden until it is registered once, ticked."""
    from myogestic.ml import widgets
    from myogestic.stream import StreamInfo

    monkeypatch.setattr(_session_state, "_pending_packs", set())
    monkeypatch.chdir(tmp_path)
    app = App("save and train")
    app.ctx.participant = "P-014"
    pipeline = Pipeline(app)
    manager = SessionManager()
    app.start_recording()
    session = app.ctx.session
    session.init_stream("emg", StreamInfo(n_channels=2, fs=100.0))
    app.stop_recording()
    finish = deferred_pack.pop()
    folder = session.path
    assert (folder / "emg.zarr").exists()
    assert not (folder / "meta.json").exists()
    assert not list(folder.parent.glob("*.session.zip"))
    assert scan_sessions(str(folder.parent)) == []
    assert manager.selection().n_total == 0
    captions = []
    colored, wrapped = imgui.text_colored, imgui.text_wrapped

    def capture(color, text):
        captions.append(text)
        colored(color, text)

    def caption(text):
        captions.append(text)
        wrapped(text)

    monkeypatch.setattr(imgui, "text_colored", capture)
    monkeypatch.setattr(imgui, "text_wrapped", caption)
    started = []
    monkeypatch.setattr(pipeline, "start_training", lambda: started.append(True))
    primary = widgets.primary_button

    def click(label, *, size):
        primary(label, size=size)
        return True

    monkeypatch.setattr(widgets, "primary_button", click)
    pipeline.on_train = lambda data: object()
    try:
        imgui_frame(lambda: manager.ui(participant="P-014"))
        imgui_frame(PipelinePanel(pipeline).ui)
        assert "Saving the last take…" in captions
        assert "Wait until the last take is saved to train." in captions
        assert started == []
        assert get_state(manager._widget_id).sessions == []
    finally:
        finish()
    state = get_state(manager._widget_id)
    imgui_frame(lambda: manager.ui(participant="P-014"))
    assert len(state.sessions) == 1
    assert state.sessions[0]["selected"] is True
    assert state.sessions[0]["path"] == str(session.path.resolve())
    assert manager.selection().n_selected == 1
    assert not app.ctx.pending_saves
