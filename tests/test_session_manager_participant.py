"""The training selection follows the participant without changing widget identity."""

import json
import zipfile

from imgui_bundle import imgui

from myogestic.widgets import SessionManager
from myogestic.widgets.training._session_state import (
    SessionWidgetState,
    _states,
    add_recorded_session,
    get_state,
)


def _take(base, participant, name):
    path = base / participant / f"{name}.session.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("meta.json", json.dumps({"participant": participant}))
        archive.writestr("labels.json", json.dumps([{"class_index": 0}]))
    return str(path.resolve())


def _render(manager, participant, frame, monkeypatch, *, scan=False):
    with monkeypatch.context() as patch:
        patch.setattr(imgui, "button", lambda label: scan and label.startswith("Scan folder##"))
        result = []
        frame(lambda: result.append(manager.ui(participant=participant)))
        return result[0]


def test_switching_participant_clears_the_list(tmp_path, imgui_frame, monkeypatch):
    first = {_take(tmp_path, "P-014", "one"), _take(tmp_path, "P-014", "two")}
    second = _take(tmp_path, "P-015", "three")
    manager = SessionManager(str(tmp_path))
    state = get_state(f"Sessions_{tmp_path}")

    _render(manager, "P-014", imgui_frame, monkeypatch)
    assert state.sessions == []
    _render(manager, "P-014", imgui_frame, monkeypatch, scan=True)
    assert {s["path"] for s in state.sessions} == first
    for row in state.sessions:
        row["selected"] = True
    state.deactivated_classes.add(0)

    data = _render(manager, "P-015", imgui_frame, monkeypatch)
    assert data.paths == []
    assert state.sessions == []
    assert state.deactivated_classes == set()
    assert state.last_load_msg == ""
    assert get_state(f"Sessions_{tmp_path}") is state
    _render(manager, "P-015", imgui_frame, monkeypatch, scan=True)
    assert [s["path"] for s in state.sessions] == [second]


def test_recorded_take_registers_under_participant(tmp_path, imgui_frame, monkeypatch):
    path = _take(tmp_path / "sessions", "P-014", "recorded")
    monkeypatch.chdir(tmp_path)
    # Exercise the default identity used by App.stop_recording as well as a
    # participant subfolder, with no custom registration arguments.
    manager = SessionManager()
    state = SessionWidgetState()
    monkeypatch.setitem(_states, "Sessions_sessions", state)
    _render(manager, "P-014", imgui_frame, monkeypatch)

    add_recorded_session(path)
    data = _render(manager, "P-014", imgui_frame, monkeypatch)
    assert data.paths == [path]
    assert data.classes == {0}
    assert state.sessions[0]["selected"] is True


def test_participant_scan_uses_the_labelled_folder(tmp_path, imgui_frame, monkeypatch):
    path = _take(tmp_path, "p-014", "recorded")
    manager = SessionManager(str(tmp_path))

    _render(manager, " p/014 ", imgui_frame, monkeypatch, scan=True)

    state = get_state(f"Sessions_{tmp_path}")
    assert [s["path"] for s in state.sessions] == [path]


def test_switching_to_unfiltered_scans_the_base(tmp_path, imgui_frame, monkeypatch):
    _take(tmp_path, "P-014", "participant")
    legacy = _take(tmp_path, "", "legacy")
    manager = SessionManager(str(tmp_path))
    _render(manager, "P-014", imgui_frame, monkeypatch, scan=True)

    _render(manager, None, imgui_frame, monkeypatch, scan=True)

    state = get_state(f"Sessions_{tmp_path}")
    assert [s["path"] for s in state.sessions] == [legacy]


def test_switching_participant_discards_pending_file_selection(tmp_path, imgui_frame, monkeypatch):
    path = _take(tmp_path, "P-014", "old")
    manager = SessionManager(str(tmp_path))
    _render(manager, "P-014", imgui_frame, monkeypatch)

    class FinishedDialog:
        def ready(self):
            return True

        def result(self):
            return [path]

    state = get_state(f"Sessions_{tmp_path}")
    state.folder_dialog = FinishedDialog()
    _render(manager, "P-015", imgui_frame, monkeypatch)

    assert state.sessions == []
    assert state.folder_dialog is None


def test_late_recording_does_not_repopulate_another_participant(tmp_path, imgui_frame, monkeypatch):
    path = _take(tmp_path, "P-014", "still-packing")
    current = _take(tmp_path, "P-015", "current")
    manager = SessionManager(str(tmp_path))
    _render(manager, "P-014", imgui_frame, monkeypatch)
    _render(manager, "P-015", imgui_frame, monkeypatch)

    add_recorded_session(path, base_path=str(tmp_path))
    add_recorded_session(current, base_path=str(tmp_path))

    data = _render(manager, "P-015", imgui_frame, monkeypatch)
    assert data.paths == [current]
