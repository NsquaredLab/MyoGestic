"""Recorded participants are discovered once, selected by ID and private by default."""

import json
import os
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from imgui_bundle import imgui

from myogestic import Context, _scale, _theme
from myogestic.widgets.panels import participant as api
from myogestic.widgets.training import _session_state as session_state


def _take(
    base, pid="P-003", *, stamp="2026-10-25T15:47:00", classes=("Rest", "Fist"), folder=False
):
    parent = base / pid
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"{pid}_{stamp.replace(':', '-')}"
    meta = dict(
        participant=pid,
        created=stamp,
        class_names=list(classes),
        duration_s=32,
        class_seconds={name: 16 for name in classes},
    )
    labels = [dict(class_index=i) for i in range(len(classes))]
    if folder:
        path.mkdir()
        (path / "meta.json").write_text(json.dumps(meta))
        (path / "labels.json").write_text(json.dumps(labels))
    else:
        path = path.with_name(path.name + ".session.zip")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("meta.json", json.dumps(meta))
            archive.writestr("labels.json", json.dumps(labels))
    return path


def _panel(tmp_path, **kwargs):
    return api.ParticipantPanel(
        key_file=tmp_path / "key.csv",
        sessions_dir=tmp_path / "sessions",
        widget_id=str(tmp_path),
        **kwargs,
    )


def _capture(monkeypatch):
    labels, clicks = [], set()
    button = imgui.button

    def press(label, *args, **kwargs):
        result = button(label, *args, **kwargs)
        visible = label.split("##")[0]
        labels.append(visible)
        return result or visible in clicks

    monkeypatch.setattr(imgui, "button", press)
    return labels, clicks


def test_listing_uses_readable_takes_and_skips_pending(tmp_path):
    base = tmp_path / "sessions"
    _take(base)
    _take(base, "P-004", stamp="2026-10-26T08:47:00", classes=())
    pending = _take(base, "P-005", folder=True)
    (base / "P-006").mkdir()
    (base / "P-006" / "meta.json").write_text("garbage")
    session_state.set_session_saving(pending, True)
    try:
        rows = api._recorded_participants(base, tmp_path / "missing.csv")
    finally:
        session_state.set_session_saving(pending, False)
    assert [row.pid for row in rows] == ["P-004", "P-003"]
    assert rows[0].class_names == []
    assert rows[1].class_names == ["Rest", "Fist"]
    assert rows[1].takes == 1 and rows[1].duration_s == 32
    assert all(not row.name for row in rows)


def test_search_names_only_when_revealed_and_ids_never_merge(tmp_path):
    base = tmp_path / "sessions"
    for pid in ("P-003", "P-004"):
        _take(base, pid)
        api._append(tmp_path / "key.csv", pid, "Jörg", "Müller")
    panel = _panel(tmp_path)
    panel._prepare()
    panel._state.search = "jorg"
    assert panel._filtered() == []
    panel._state.show_names = True
    assert {row.pid for row in panel._filtered()} == {"P-003", "P-004"}
    panel._state.show_names = False
    panel._state.search = "p-003"
    assert [row.pid for row in panel._filtered()] == ["P-003"]


def test_scan_once_per_open_and_names_reset_on_cancel(tmp_path, imgui_frame, monkeypatch):
    _take(tmp_path / "sessions")
    api._append(tmp_path / "key.csv", "P-003", "Jane", "Doe")
    panel, ctx = _panel(tmp_path), Context()
    reads, text = [], []
    real_read = session_state._read_session_metadata
    real_text = imgui.text_colored

    def read(path):
        reads.append(path)
        return real_read(path)

    def colored(color, value):
        text.append(value)
        real_text(color, value)

    monkeypatch.setattr(session_state, "_read_session_metadata", read)
    monkeypatch.setattr(imgui, "text_colored", colored)
    _, clicks = _capture(monkeypatch)
    panel.open()

    def draw():
        panel.ui(ctx)

    imgui_frame(draw)
    imgui_frame(draw)
    assert len(reads) == 1
    assert "•••••  •••••••" in text
    assert not any("Jane" in value for value in text)
    clicks.add("Show names")
    imgui_frame(draw)
    clicks.clear()
    imgui_frame(draw)
    assert "Jane Doe" in text
    clicks.add("Cancel")
    imgui_frame(draw)
    clicks.clear()
    assert not panel._state.show_names
    panel.open()
    text.clear()
    imgui_frame(draw)
    assert len(reads) == 2
    assert not any("Jane" in value for value in text)
    assert ctx.logs == [] and ctx.status_message == ""


@pytest.mark.parametrize("drive", [False, True])
def test_continue_and_drive_keep_key_unchanged(tmp_path, imgui_frame, monkeypatch, drive):
    _take(tmp_path / "sessions")
    key = tmp_path / "key.csv"
    api._append(key, "P-003", "Jane", "Doe")
    before = key.read_bytes()
    old = tmp_path / "sessions/P-003/old_model.joblib"
    new = old.with_name("new_model.joblib")
    old.touch()
    new.touch()
    os.utime(old, (1, 1))
    calls, ctx = [], Context()
    panel = _panel(tmp_path, on_drive=lambda pid, path: calls.append((ctx.participant, pid, path)))
    labels, clicks = _capture(monkeypatch)
    panel.open()

    def draw():
        panel.ui(ctx)

    imgui_frame(draw)
    assert "Drive with saved model" in labels
    clicks.add("Drive with saved model" if drive else "Continue with P-003")
    imgui_frame(draw)
    assert ctx.participant == "P-003"
    assert key.read_bytes() == before
    assert calls == ([("P-003", "P-003", new)] if drive else [])
    assert "Jane" not in repr(ctx) and "Doe" not in repr(ctx)


@pytest.mark.parametrize("busy", ["recording", "training", "predicting"])
def test_open_dialog_closes_and_hides_names_when_busy(tmp_path, imgui_frame, busy):
    _take(tmp_path / "sessions")
    panel, ctx = _panel(tmp_path), Context()
    panel.open()
    imgui_frame(lambda: panel.ui(ctx))
    panel._state.show_names = True
    ctx.state = busy
    imgui_frame(lambda: panel.ui(ctx))
    assert not panel._state.show_names
    assert ctx.participant == ""


def test_next_free_id_includes_recordings_without_key_rows(tmp_path):
    _take(tmp_path / "sessions", "P-014")
    panel = _panel(tmp_path)
    panel._prepare()
    assert panel._state.pid == "P-015"
    assert panel._state.tab == 0


@pytest.mark.parametrize("content", [None, "wrong,header\nP-003,Jane\n"])
def test_missing_or_edited_key_still_lists_ids(tmp_path, content):
    _take(tmp_path / "sessions")
    if content is not None:
        (tmp_path / "key.csv").write_text(content)
    panel = _panel(tmp_path)
    panel._prepare()
    assert [(row.pid, row.name) for row in panel._filtered()] == [("P-003", "")]


@pytest.mark.parametrize("callback,model", [(False, True), (True, False), (False, False)])
def test_drive_action_requires_both_callback_and_model(
    tmp_path, imgui_frame, monkeypatch, callback, model
):
    _take(tmp_path / "sessions")
    if model:
        (tmp_path / "sessions/P-003/a_model.joblib").touch()
    panel = _panel(tmp_path, on_drive=(lambda *_: None) if callback else None)
    labels, _ = _capture(monkeypatch)
    panel.open()
    imgui_frame(lambda: panel.ui(Context()))
    assert "Drive with saved model" not in labels


def test_empty_recorded_tab_points_to_new_participant(tmp_path, imgui_frame, monkeypatch):
    panel = _panel(tmp_path)
    panel.open()
    imgui_frame(lambda: panel.ui(Context()))
    assert panel._state.tab == 1
    panel._state.tab = 0
    labels, clicks = _capture(monkeypatch)
    clicks.add("New participant")
    imgui_frame(lambda: panel.ui(Context()))
    assert "New participant" in labels
    assert panel._state.tab == 1


def test_continue_uses_clicked_id_even_when_names_match(tmp_path, imgui_frame, monkeypatch):
    for pid in ("P-003", "P-004"):
        _take(tmp_path / "sessions", pid)
        api._append(tmp_path / "key.csv", pid, "Jane", "Doe")
    panel, ctx = _panel(tmp_path), Context()
    _, clicks = _capture(monkeypatch)
    button = imgui.button

    def select(label, *args, **kwargs):
        clicked = button(label, *args, **kwargs)
        return clicked or label == "##recorded:P-003"

    monkeypatch.setattr(imgui, "button", select)
    panel.open()
    imgui_frame(lambda: panel.ui(ctx))
    assert panel._state.selected == "P-003"
    clicks.add("Continue with P-003")
    imgui_frame(lambda: panel.ui(ctx))
    assert ctx.participant == "P-003"


def test_last_recorded_labels():
    today = datetime.now().replace(hour=8, minute=47)
    assert api._when(today) == "Today 08:47"
    assert api._when(today - timedelta(days=1)) == "Yesterday 08:47"
    assert api._when(today - timedelta(days=2)) == (today - timedelta(days=2)).strftime("%Y-%m-%d")


@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("width", [320, 700])
@pytest.mark.parametrize("height", [500, 900])
@pytest.mark.parametrize("tab", [0, 1])
def test_light_dialog_fits_narrow_viewport(
    tmp_path, imgui_frame, monkeypatch, scale, width, height, tab
):
    _take(tmp_path / "sessions")
    panel, ctx = _panel(tmp_path, on_drive=lambda *_: None), Context()
    (tmp_path / "sessions/P-003/a_model.joblib").touch()
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    font_path = Path(_theme.__file__).parent / "assets/fonts/IBMPlexMono-Regular.ttf"
    font = imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 13.0)
    monkeypatch.setattr(_theme, "_MONO_FONT", font)
    imgui.get_io().display_size = imgui.ImVec2(width * scale, height * scale)
    bounds = []
    button, input_text = imgui.button, imgui.input_text

    def measure():
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        bounds.append((lo.x, lo.y, hi.x, hi.y))

    def measured_button(*args, **kwargs):
        clicked = button(*args, **kwargs)
        if not args[0].endswith("###chip"):
            measure()
        return clicked

    def measured_input(*args, **kwargs):
        result = input_text(*args, **kwargs)
        measure()
        return result

    monkeypatch.setattr(imgui, "button", measured_button)
    monkeypatch.setattr(imgui, "input_text", measured_input)
    panel.open()

    def draw():
        panel.ui(ctx)

    imgui_frame(draw)
    panel._state.tab = tab
    imgui_frame(draw)
    bounds.clear()
    imgui_frame(draw)
    assert bounds
    assert all(0 <= left < right <= width * scale for left, _, right, _ in bounds), bounds
    assert all(0 <= top < bottom <= height * scale for _, top, _, bottom in bounds), bounds
