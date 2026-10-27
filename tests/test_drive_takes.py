"""Prediction provenance identifies drive takes without filename conventions."""

import json

import pytest
from imgui_bundle import imgui

from myogestic.session import Session
from myogestic.widgets import SessionManager
from myogestic.widgets.training import _session_state


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.setattr(_session_state, "_states", {})


def _take(tmp_path, *, drive):
    session = Session(str(tmp_path), participant="P-014")
    if drive:
        session.extras["pipeline"] = {"model": "model.joblib"}
    session.save_meta("take")
    return session.pack_to_zip()


def test_drive_registration_is_unticked_and_can_be_selected(tmp_path, imgui_frame, monkeypatch):
    path = _take(tmp_path, drive=True)
    manager = SessionManager(str(tmp_path))
    state = _session_state.get_state(manager._widget_id)
    manager.select_all("P-014")
    assert len(state.sessions) == 1
    assert state.sessions[0]["drive"] is True
    assert manager.selection().n_selected == 0
    _session_state.add_recorded_session(str(path), str(tmp_path))
    assert len(state.sessions) == 1
    assert not state.sessions[0]["selected"]
    texts = []
    colored = imgui.text_colored

    def capture(color, text):
        texts.append(text)
        colored(color, text)

    monkeypatch.setattr(imgui, "text_colored", capture)
    imgui_frame(lambda: manager.ui(participant="P-014"))
    assert "Drive" in texts
    assert "Drive runs are not ticked for training." in texts
    checkbox = imgui.checkbox

    def click(label, selected):
        changed, value = checkbox(label, selected)
        return (True, True) if str(path.resolve()) in label else (changed, value)

    monkeypatch.setattr(imgui, "checkbox", click)
    results = []
    imgui_frame(lambda: results.append(manager.ui(participant="P-014")))
    assert results[0].paths == [str(path.resolve())]


def test_select_all_skips_only_pipeline_provenance(tmp_path):
    ordinary = _take(tmp_path, drive=False)
    drive = _take(tmp_path, drive=True)
    # A suggestive name has no meaning; only extras.pipeline identifies Drive.
    renamed = ordinary.with_name("Drive.session.zip")
    ordinary.rename(renamed)
    manager = SessionManager(str(tmp_path))
    manager.select_all("P-014")
    rows = _session_state.get_state(manager._widget_id).sessions
    assert {row["path"] for row in rows if row["selected"]} == {str(renamed.resolve())}
    assert {row["path"] for row in rows if row["drive"]} == {str(drive.resolve())}


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("guided", [False, True])
def test_class_chip_counts_drive_time_only_when_ticked(imgui_frame, monkeypatch, selected, guided):
    from myogestic.widgets.training.session_manager import render_class_buttons

    state = _session_state.SessionWidgetState(
        sessions=[
            {"class_seconds": {"Rest": 4.0}, "selected": True},
            {"class_seconds": {"Fist": 4.0}, "selected": False, "drive": False},
            {
                "class_seconds": {"Rest": 8.0, "Fist": 8.0},
                "selected": selected,
                "drive": True,
                "guided": guided,
            },
        ]
    )
    labels = []
    button = imgui.button

    def capture(label, *args):
        labels.append(label.split("##")[0].strip())
        return button(label, *args)

    monkeypatch.setattr(imgui, "button", capture)
    imgui_frame(lambda: render_class_buttons("drive-counts", state, ["Rest", "Fist"]))
    seconds = "0:12" if selected else "0:04"
    assert labels == [f"Rest {seconds}", f"Fist {seconds}"]


def test_pending_zarr_without_meta_never_reaches_metadata_reader(tmp_path, monkeypatch):
    folder = tmp_path / "pending"
    (folder / "emg.zarr").mkdir(parents=True)
    (folder / "emg.zarr" / "zarr.json").write_text(json.dumps({"zarr_format": 3}))
    _session_state.set_session_saving(folder, True)
    monkeypatch.setattr(_session_state, "_session_row", lambda path: pytest.fail(str(path)))
    try:
        assert _session_state.scan_sessions(str(tmp_path)) == []
    finally:
        _session_state.set_session_saving(folder, False)
