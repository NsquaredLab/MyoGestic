"""The training selection follows the participant without changing widget identity."""

import json
import zipfile

import pytest
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


def test_autoscan_follows_participant(tmp_path, imgui_frame, monkeypatch):
    first = {_take(tmp_path, "P-014", "one"), _take(tmp_path, "P-014", "two")}
    second = _take(tmp_path, "P-015", "three")
    manager = SessionManager(str(tmp_path))
    state = get_state(f"Sessions_{tmp_path}")

    _render(manager, "P-014", imgui_frame, monkeypatch)
    assert {s["path"] for s in state.sessions} == first
    assert not any(s["selected"] for s in state.sessions)
    for row in state.sessions:
        row["selected"] = True
    state.deactivated_classes.add(0)

    data = _render(manager, "P-015", imgui_frame, monkeypatch)
    assert data.paths == []
    assert [s["path"] for s in state.sessions] == [second]
    assert not state.sessions[0]["selected"]
    assert state.deactivated_classes == set()
    assert state.last_load_msg == ""
    assert get_state(f"Sessions_{tmp_path}") is state
    _render(manager, "P-015", imgui_frame, monkeypatch, scan=True)
    assert [s["path"] for s in state.sessions] == [second]


def test_no_participant_stays_empty_until_scan(tmp_path, imgui_frame, monkeypatch):
    path = _take(tmp_path, "", "legacy")
    manager = SessionManager(str(tmp_path))
    state = get_state(f"Sessions_{tmp_path}")
    _render(manager, None, imgui_frame, monkeypatch)
    assert state.sessions == []
    _render(manager, None, imgui_frame, monkeypatch, scan=True)
    assert [s["path"] for s in state.sessions] == [path]
    assert not state.sessions[0]["selected"]


def test_recording_refreshes_participant_without_selecting_other_takes(
    tmp_path, imgui_frame, monkeypatch,
):
    previous = _take(tmp_path, "P-014", "previous")
    manager = SessionManager(str(tmp_path))
    _render(manager, "P-014", imgui_frame, monkeypatch)
    state = get_state(f"Sessions_{tmp_path}")
    state.sessions[0]["selected"] = True
    elsewhere = _take(tmp_path, "P-014", "elsewhere")
    fresh = _take(tmp_path, "P-014", "fresh")
    add_recorded_session(fresh, base_path=str(tmp_path))
    data = _render(manager, "P-014", imgui_frame, monkeypatch)
    assert set(data.paths) == {previous, fresh}
    assert {s["path"] for s in state.sessions} == {previous, elsewhere, fresh}
    assert not next(s for s in state.sessions if s["path"] == elsewhere)["selected"]


def test_recording_refresh_replaces_a_packed_folder(tmp_path, imgui_frame, monkeypatch):
    folder = tmp_path / "P-014" / "packing"
    folder.mkdir(parents=True)
    meta = folder / "meta.json"
    meta.write_text(json.dumps({"participant": "P-014"}))
    manager = SessionManager(str(tmp_path))
    _render(manager, "P-014", imgui_frame, monkeypatch)
    state = get_state(f"Sessions_{tmp_path}")
    assert len(state.sessions) == 1
    meta.unlink()
    folder.rmdir()
    packed = _take(tmp_path, "P-014", "packing")
    add_recorded_session(packed, base_path=str(tmp_path))
    data = _render(manager, "P-014", imgui_frame, monkeypatch)
    assert data.paths == [packed]
    assert [s["path"] for s in state.sessions] == [packed]


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


def test_empty_participant_offers_file_picker(tmp_path, imgui_frame, monkeypatch):
    from myogestic.widgets.training import session_manager as module

    manager = SessionManager(str(tmp_path))
    messages = []
    real_text = imgui.text_colored
    real_button = imgui.small_button

    def text(color, value):
        messages.append(value)
        real_text(color, value)

    def button(label):
        clicked = real_button(label)
        return label.startswith("Load files from") or clicked

    class PendingDialog:
        def ready(self):
            return False

    dialog = PendingDialog()
    monkeypatch.setattr(imgui, "text_colored", text)
    monkeypatch.setattr(imgui, "small_button", button)
    monkeypatch.setattr(module.pfd, "open_file", lambda *args: dialog)
    imgui_frame(lambda: manager.ui(participant="P-014"))
    assert "No takes for P-014 yet." in messages
    assert "Takes you record appear here, already ticked for training." in messages
    assert get_state(f"Sessions_{tmp_path}").folder_dialog is dialog


@pytest.mark.parametrize("participant", ["P-014", None, ""])
@pytest.mark.parametrize("has_takes", [False, True])
def test_participant_summary_only_with_takes(
    tmp_path, imgui_frame, monkeypatch, participant, has_takes,
):
    manager = SessionManager(str(tmp_path))
    if has_takes:
        _take(tmp_path, participant or "", "existing")
        if not participant:
            _render(manager, participant, imgui_frame, monkeypatch, scan=True)
    labels, messages = [], []
    button, small_button, text = imgui.button, imgui.small_button, imgui.text

    def track_button(label, *args):
        labels.append(label.split("##")[0])
        return button(label, *args)

    def track_small_button(label):
        labels.append(label.split("##")[0])
        return small_button(label)

    def track_text(label):
        messages.append(label)
        text(label)

    monkeypatch.setattr(imgui, "button", track_button)
    monkeypatch.setattr(imgui, "small_button", track_small_button)
    monkeypatch.setattr(imgui, "text", track_text)
    imgui_frame(lambda: manager.ui(participant=participant))
    summary_visible = not participant or has_takes
    assert any("selected" in message for message in messages) == summary_visible
    assert ("Scan folder" in labels) == summary_visible
    assert ("Load Files..." in labels) == summary_visible
    assert ("Load files from elsewhere…" in labels) == (bool(participant) and not has_takes)


def test_session_row_shows_recorded_seconds(tmp_path, imgui_frame, monkeypatch):
    from myogestic.widgets.training import session_manager as module

    path = tmp_path / "P-014" / "take"
    path.mkdir(parents=True)
    (path / "meta.json").write_text(json.dumps({
        "participant": "P-014", "name": "Practice", "duration_s": 74.0,
        "class_names": ["Rest", "Fist"], "class_seconds": {"Rest": 14.0, "Fist": 60.0},
    }))
    labels = []
    real_mono = module.__dict__.get("mono_text")

    def mono(value, color=None):
        labels.append(value)
        real_mono(value, color)

    assert real_mono is not None, "session names and durations should use the mono face"
    monkeypatch.setattr(module, "mono_text", mono)
    manager = SessionManager(str(tmp_path))
    imgui_frame(lambda: manager.ui(participant="P-014"))
    assert "1:14" in labels
    assert any("Practice" in label for label in labels)
