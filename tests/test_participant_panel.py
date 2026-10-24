"""Participant selection keeps names local and cannot change an active take."""

import csv
import json
import time
import zipfile
from datetime import date

import numpy as np
import pytest
from imgui_bundle import imgui

from myogestic import App, Context, Stream
from myogestic.session._core import _slug
from myogestic.stream import StreamInfo


def _api():
    from myogestic.widgets.panels import participant

    return participant


def _rows(key):
    with key.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _panel(tmp_path, widget_id="test-participant"):
    return _api().ParticipantPanel(key_file=tmp_path / "key.csv", widget_id=widget_id)


def _buttons(monkeypatch):
    positions = {}
    button = imgui.button

    def capture(label, *args):
        clicked = button(label, *args)
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        positions[label.split("##")[0]] = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2)
        return clicked

    monkeypatch.setattr(imgui, "button", capture)
    return positions


def _click(frame, draw, position):
    io = imgui.get_io()
    io.add_mouse_pos_event(*position)
    frame(draw)
    io.add_mouse_button_event(0, True)
    frame(draw)
    io.add_mouse_button_event(0, False)
    frame(draw)


def test_next_id_and_append(tmp_path):
    api, key = _api(), tmp_path / "private" / "key.csv"
    assert api._next_id(key) == "P-001"
    assert not key.exists()
    api._append(key, "P-014", "Jane", "Doe")
    assert api._next_id(key) == "P-015"
    assert _rows(key) == [
        dict(id="P-014", first_name="Jane", family_name="Doe", created=date.today().isoformat())
    ]
    api._append(key, "P-003", "A, B", 'C "D"')
    assert api._next_id(key) == "P-015"
    assert _rows(key)[1]["first_name"] == "A, B"
    assert _rows(key)[1]["family_name"] == 'C "D"'


def test_lookup_folds_case_and_accents(tmp_path):
    api, key = _api(), tmp_path / "key.csv"
    api._append(key, "P-007", "Jörg", "Müller")
    assert api._lookup(key, "jorg", "MULLER") == "P-007"
    assert api._lookup(key, "  JORG ", " muller ") == "P-007"
    assert api._lookup(key, "different", "MULLER") is None


@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        "id,first_name,family_name,created\nP-999,Short\ncustom,A,B,2026-10-24\n",
        "wrong,header\nP-999,Jane\n",
        'id,first_name,family_name,created\n"unfinished',
    ],
)
def test_key_file_tolerates_missing_and_malformed(tmp_path, content):
    api, key = _api(), tmp_path / "key.csv"
    if content is not None:
        key.write_text(content, encoding="utf-8")
    assert api._lookup(key, "Short", "") is None
    assert api._next_id(key) == "P-001"


def test_append_to_empty_file_writes_header(tmp_path):
    api, key = _api(), tmp_path / "key.csv"
    key.touch()
    api._append(key, "P-001", "Jane", "Doe")
    assert _rows(key)[0]["id"] == "P-001"


class _Source:
    def connect(self):
        return StreamInfo(n_channels=2, fs=100.0)

    def read(self):
        return None, None

    def disconnect(self):
        pass


def test_start_sets_participant_and_writes_key_only(tmp_path, imgui_frame):
    panel = _panel(tmp_path, "privacy")
    app = App("test")
    stream = Stream("emg", source=_Source(), window_ms=100)
    app.streams(stream)
    assert stream.reconnect()
    panel._start(app.ctx, "P-014", "Jane", "Doe")
    assert app.ctx.participant == "P-014"
    assert _rows(tmp_path / "key.csv")[0]["id"] == "P-014"
    imgui_frame(lambda: panel.ui(app.ctx))

    sessions = tmp_path / "sessions"
    app.start_recording(str(sessions))
    app.ctx.session.append("emg", np.zeros((4, 2), dtype=np.float32), np.arange(4.0))
    app.stop_recording()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not list(sessions.rglob("*.session.zip")):
        time.sleep(0.01)
    archives = list(sessions.rglob("*.session.zip"))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as archive:
        assert json.loads(archive.read("meta.json"))["participant"] == "P-014"
        for name in archive.namelist():
            assert "Jane" not in name and "Doe" not in name
            assert b"Jane" not in archive.read(name) and b"Doe" not in archive.read(name)
    for path in sessions.rglob("*"):
        assert "Jane" not in str(path) and "Doe" not in str(path)
        if path.is_file():
            assert b"Jane" not in path.read_bytes() and b"Doe" not in path.read_bytes()
    assert all("Jane" not in line and "Doe" not in line for line in app.ctx.logs)
    assert "Jane" not in repr(app.ctx) and "Doe" not in repr(app.ctx)


@pytest.mark.parametrize("state", ["recording", "training", "predicting"])
def test_chip_disabled_while_recording(tmp_path, imgui_frame, monkeypatch, state):
    panel, ctx = _panel(tmp_path, f"busy:{state}"), Context(state=state)
    positions = _buttons(monkeypatch)

    def draw():
        panel.ui(ctx)

    imgui_frame(draw)
    imgui_frame(draw)
    _click(imgui_frame, draw, positions["Set participant"])
    assert "Start session" not in positions
    ctx.state = "idle"
    _click(imgui_frame, draw, positions["Set participant"])
    assert "Start session" in positions


def test_panel_renders(tmp_path, imgui_frame):
    panel, ctx = _panel(tmp_path, "render"), Context()
    imgui_frame(lambda: panel.ui(ctx))
    ctx.participant = "P-014"
    imgui_frame(lambda: panel.ui(ctx))
    assert not (tmp_path / "key.csv").exists()


@pytest.mark.parametrize("typed", [" p/014 ", "../x", "Jörg"])
def test_start_uses_the_shared_slug(tmp_path, typed):
    panel, ctx = _panel(tmp_path, f"slug:{typed}"), Context()
    panel._start(ctx, typed, "", "")
    assert ctx.participant == _slug(typed)
    assert not (tmp_path / "key.csv").exists()


@pytest.mark.parametrize("state,pid", [("recording", "P-014"), ("idle", " ... / ")])
def test_start_refuses_busy_or_empty_id(tmp_path, state, pid):
    panel, ctx = _panel(tmp_path, "refused"), Context(state=state)
    panel._start(ctx, pid, "Jane", "Doe")
    assert ctx.participant == ""
    assert not (tmp_path / "key.csv").exists()


def test_returning_participant_is_not_duplicated(tmp_path):
    panel, ctx = _panel(tmp_path, "returning"), Context()
    panel._start(ctx, "P-007", "Jörg", "Müller")
    panel._start(ctx, "P-007", "jorg", "MULLER")
    assert len(_rows(tmp_path / "key.csv")) == 1


def test_modal_uses_returning_id_and_shared_preview(tmp_path, imgui_frame, monkeypatch):
    api = _api()
    api._append(tmp_path / "key.csv", "P-007", "Jörg", "Müller")
    panel, ctx = _panel(tmp_path, "modal"), Context()
    positions = _buttons(monkeypatch)
    inputs, text = {}, []
    input_text, text_colored = imgui.input_text, imgui.text_colored

    def type_names(label, value, *args, **kwargs):
        changed, typed = input_text(label, value, *args, **kwargs)
        inputs[label] = value
        if label in ("First name", "Family name"):
            return True, "jorg" if label == "First name" else "MULLER"
        return changed, typed

    def capture_text(color, value):
        text.append(value)
        text_colored(color, value)

    monkeypatch.setattr(imgui, "input_text", type_names)
    monkeypatch.setattr(imgui, "text_colored", capture_text)

    def draw():
        panel.ui(ctx)

    imgui_frame(draw)
    imgui_frame(draw)
    _click(imgui_frame, draw, positions["Set participant"])
    imgui_frame(draw)
    assert inputs["Participant ID"] == "P-007"
    assert "Returning participant" in text
    assert any("sessions/P-007/P-007_" in line for line in text)
    _click(imgui_frame, draw, positions["Start session"])
    assert ctx.participant == "P-007"
    assert len(_rows(tmp_path / "key.csv")) == 1


def test_cancel_does_not_change_participant_or_write_key(tmp_path, imgui_frame, monkeypatch):
    panel, ctx = _panel(tmp_path, "cancel"), Context(participant="P-014")
    positions = _buttons(monkeypatch)

    def draw():
        panel.ui(ctx)

    imgui_frame(draw)
    imgui_frame(draw)
    _click(imgui_frame, draw, positions["P-014"])
    imgui_frame(draw)  # Let the auto-sized modal settle before targeting Cancel.
    _click(imgui_frame, draw, positions["Cancel"])
    positions.clear()
    imgui_frame(draw)
    assert "Start session" not in positions
    assert ctx.participant == "P-014"
    assert not (tmp_path / "key.csv").exists()


def test_modal_refuses_a_slug_empty_id(tmp_path, imgui_frame, monkeypatch):
    panel, ctx = _panel(tmp_path, "empty-modal"), Context()
    positions = _buttons(monkeypatch)
    input_text = imgui.input_text

    def type_empty(label, value, *args, **kwargs):
        changed, typed = input_text(label, value, *args, **kwargs)
        return (True, " ... / ") if label == "Participant ID" else (changed, typed)

    monkeypatch.setattr(imgui, "input_text", type_empty)

    def draw():
        panel.ui(ctx)

    imgui_frame(draw)
    imgui_frame(draw)
    _click(imgui_frame, draw, positions["Set participant"])
    imgui_frame(draw)
    _click(imgui_frame, draw, positions["Start session"])
    assert ctx.participant == ""
    assert not (tmp_path / "key.csv").exists()


def test_popup_state_is_per_widget_id(tmp_path, imgui_frame, monkeypatch):
    first, second = _panel(tmp_path, "identity-a"), _panel(tmp_path, "identity-b")
    contexts = [Context(participant="P-014"), Context(participant="P-015")]
    positions = _buttons(monkeypatch)
    input_text = imgui.input_text
    edits = []

    def type_id(label, value, *args, **kwargs):
        changed, typed = input_text(label, value, *args, **kwargs)
        if label == "Participant ID":
            edits.append(value)
            return True, "P-020"
        return changed, typed

    monkeypatch.setattr(imgui, "input_text", type_id)

    def draw():
        first.ui(contexts[0])
        second.ui(contexts[1])

    imgui_frame(draw)
    imgui_frame(draw)
    _click(imgui_frame, draw, positions["P-014"])
    first = _panel(tmp_path, "identity-a")
    imgui_frame(draw)
    assert edits[-1] == "P-020"
    _click(imgui_frame, draw, positions["Start session"])
    assert [ctx.participant for ctx in contexts] == ["P-020", "P-015"]


def test_key_write_failure_preserves_selection_without_logging_names(tmp_path, monkeypatch):
    api = _api()
    panel, ctx = _panel(tmp_path, "write-failure"), Context(participant="P-007")

    def fail(*args):
        raise OSError("Jane Doe cannot be written")

    monkeypatch.setattr(api, "_append", fail)
    panel._start(ctx, "P-014", "Jane", "Doe")
    assert ctx.participant == "P-007"
    assert not (tmp_path / "key.csv").exists()
    assert "Jane" not in repr(ctx) and "Doe" not in repr(ctx)


def test_default_key_is_outside_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    panel, ctx = _api().ParticipantPanel(widget_id="default-key"), Context()
    panel._start(ctx, "P-014", "Jane", "Doe")
    assert (tmp_path / "myogestic" / "participant-key.csv").exists()
    assert not (tmp_path / "sessions").exists()
