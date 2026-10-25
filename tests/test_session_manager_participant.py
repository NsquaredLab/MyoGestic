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
        real_button = imgui.small_button

        def press(label):
            real_button(label)
            return scan and label.endswith("_scan")

        patch.setattr(imgui, "small_button", press)
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
    real_text = imgui.text_wrapped
    real_button = imgui.small_button

    def text(value):
        messages.append(value)
        real_text(value)

    def button(label):
        clicked = real_button(label)
        return label.startswith("Load files from") or clicked

    class PendingDialog:
        def ready(self):
            return False

    dialog = PendingDialog()
    monkeypatch.setattr(imgui, "text_wrapped", text)
    monkeypatch.setattr(imgui, "small_button", button)
    monkeypatch.setattr(module.pfd, "open_file", lambda *args: dialog)
    imgui_frame(lambda: manager.ui(participant="P-014"))
    assert "No takes for P-014 yet." in messages
    assert "Takes you record appear here, already ticked for training." in messages
    assert get_state(f"Sessions_{tmp_path}").folder_dialog is dialog


@pytest.mark.parametrize("participant", ["P-014", None, ""])
@pytest.mark.parametrize("has_takes", [False, True])
def test_participant_header_and_summary_stay_visible(
    tmp_path, imgui_frame, monkeypatch, participant, has_takes,
):
    manager = SessionManager(str(tmp_path))
    if has_takes:
        _take(tmp_path, participant or "", "existing")
        if not participant:
            _render(manager, participant, imgui_frame, monkeypatch, scan=True)
    labels, messages = [], []
    button, small_button, text = imgui.button, imgui.small_button, imgui.text_colored

    def track_button(label, *args):
        labels.append(label.split("##")[0])
        return button(label, *args)

    def track_small_button(label):
        labels.append(label.split("##")[0])
        return small_button(label)

    def track_text(color, label):
        messages.append(label)
        text(color, label)

    monkeypatch.setattr(imgui, "button", track_button)
    monkeypatch.setattr(imgui, "small_button", track_small_button)
    monkeypatch.setattr(imgui, "text_colored", track_text)
    imgui_frame(lambda: manager.ui(participant=participant))
    from imgui_bundle import icons_fontawesome_6 as fa

    assert any("selected" in message for message in messages)
    assert fa.ICON_FA_ARROWS_ROTATE in labels
    assert fa.ICON_FA_FOLDER_OPEN in labels
    assert fa.ICON_FA_BROOM in labels
    assert ("Load files from elsewhere…" in labels) == (bool(participant) and not has_takes)


@pytest.mark.parametrize("scale", [1., 2.])
@pytest.mark.parametrize("width", [320, 400])
def test_empty_participant_guidance_wraps_inside_its_card(
    tmp_path, imgui_frame, monkeypatch, scale, width,
):
    """Guidance fits the session column even with a wider platform font."""
    from myogestic import _scale, _theme

    manager = SessionManager(str(tmp_path))
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    imgui.get_io().display_size = imgui.ImVec2(1280 * scale, 828 * scale)
    bounds = []

    def draw():
        imgui.begin_child("empty-takes", imgui.ImVec2(width * scale, 260 * scale))
        manager.ui(participant="P-014")
        bounds.append((imgui.get_scroll_max_x(), imgui.get_scroll_max_y(),
                       imgui.get_item_rect_max().y, imgui.get_window_draw_list().get_clip_rect_max().y))
        imgui.end_child()

    for _ in range(4):
        imgui_frame(draw)
    horizontal, vertical, bottom, clip_bottom = bounds[-1]
    assert horizontal == vertical == 0, bounds
    assert bottom <= clip_bottom, bounds


def test_session_row_shows_recorded_seconds(tmp_path, imgui_frame, monkeypatch):
    from myogestic.widgets.training import session_manager as module

    path = tmp_path / "P-014" / "take"
    path.mkdir(parents=True)
    (path / "meta.json").write_text(json.dumps({
        "participant": "P-014", "name": "Practice", "duration_s": 74.0,
        "created": "2026-10-25T14:15:00",
        "class_names": ["Rest", "Fist"], "class_seconds": {"Rest": 14.0, "Fist": 60.0},
    }))
    labels, tooltips = [], []
    monkeypatch.setattr(imgui, "set_item_tooltip", tooltips.append)
    real_mono = module.__dict__.get("mono_text")

    def mono(value, color=None):
        labels.append(value)
        real_mono(value, color)

    assert real_mono is not None, "session names and durations should use the mono face"
    monkeypatch.setattr(module, "mono_text", mono)
    manager = SessionManager(str(tmp_path))
    imgui_frame(lambda: manager.ui(participant="P-014"))
    assert "1:14" in labels
    assert "14:15" in labels
    assert any("Practice" in tip for tip in tooltips)


def _dated_take(base, participant, name, created, *, seconds=None, labels=(0, 1)):
    path = base / participant / name
    path.mkdir(parents=True)
    (path / "meta.json").write_text(json.dumps({
        "participant": participant, "created": created, "class_names": ["Rest", "Fist"],
        "duration_s": 30.0, "class_seconds": seconds if seconds is not None else {"Rest": 10., "Fist": 20.},
    }))
    (path / "labels.json").write_text(json.dumps([{"class_index": ci} for ci in labels]))
    return str(path.resolve())


def test_takes_group_by_created_newest_first_with_external_files_separate(tmp_path):
    from datetime import date

    from myogestic.widgets.training._session_state import (
        group_sessions,
        load_session_files,
        scan_sessions,
    )

    base = tmp_path / "sessions"
    old = _dated_take(base, "P-014", "z-first-in-filename-order", "2026-10-23T09:00:00")
    yesterday = _dated_take(base, "P-014", "yesterday", "2026-10-24T13:00:00")
    morning = _dated_take(base, "P-014", "morning", "2026-10-25T08:00:00")
    latest = _dated_take(base, "P-014", "a-last-in-filename-order", "2026-10-25T14:15:00")
    external = _dated_take(tmp_path / "elsewhere", "P-014", "loaded", "2026-10-25T15:00:00")
    state = SessionWidgetState(sessions=scan_sessions(str(base / "P-014")))
    load_session_files(state, [external])
    groups = group_sessions(state.sessions, str(base / "P-014"), today=date(2026, 10, 25))
    assert [g.label for g in groups] == ["Today", "Yesterday", "Oct 23", "Loaded"]
    assert [[r["path"] for r in g.rows] for g in groups] == [[latest, morning], [yesterday], [old], [external]]
    assert [g.default_open for g in groups] == [True, False, False, False]


def test_selection_summary_tracks_takes_and_excluded_gestures(tmp_path):
    from myogestic.widgets.training._session_state import scan_sessions

    _dated_take(tmp_path, "", "one", "2026-10-25T08:00:00")
    _dated_take(tmp_path, "", "two", "2026-10-25T09:00:00", seconds={"Rest": 7., "Fist": 23.})
    manager = SessionManager(str(tmp_path), class_names=["Rest", "Fist"])
    state = get_state(manager._widget_id)
    state.sessions = scan_sessions(str(tmp_path))
    state.sessions[0]["selected"] = True
    summary = manager.selection()
    assert (summary.n_selected, summary.n_total) == (1, 2)
    assert summary.class_seconds == {"Rest": 7., "Fist": 23.}
    state.deactivated_classes.add(1)
    assert manager.selection().class_seconds == {"Rest": 7.}
    state.sessions[1]["selected"] = True
    assert manager.selection().class_seconds == {"Rest": 17.}
    # A public read is a snapshot, not a mutable handle into widget state.
    summary.class_seconds["Rest"] = 999
    assert manager.selection().class_seconds["Rest"] == 17.


def test_all_none_and_gesture_click_update_returned_data_in_same_frame(tmp_path, imgui_frame, monkeypatch):
    from myogestic.widgets.training._session_state import scan_sessions

    paths = {_dated_take(tmp_path, "", str(i), "2026-10-25T08:00:00") for i in range(3)}
    manager = SessionManager(str(tmp_path), class_names=["Rest", "Fist"])
    state = get_state(manager._widget_id)
    state.sessions = scan_sessions(str(tmp_path))
    click = {"label": "All"}
    button, small_button = imgui.button, imgui.small_button

    def press(label, *args):
        button(label, *args)
        return label.split("##")[0] == click["label"] or label.endswith(click["label"])

    def small_press(label):
        small_button(label)
        return label.split("##")[0] == click["label"]

    monkeypatch.setattr(imgui, "button", press)
    monkeypatch.setattr(imgui, "small_button", small_press)
    results = []
    imgui_frame(lambda: results.append(manager.ui()))
    assert set(results[-1].paths) == paths
    click["label"] = "_gesture1"
    imgui_frame(lambda: results.append(manager.ui()))
    assert results[-1].classes == {0}
    assert manager.selection().class_seconds == {"Rest": 30.}
    click["label"] = "None"
    imgui_frame(lambda: results.append(manager.ui()))
    assert results[-1].paths == [] and manager.selection().n_selected == 0
    click["label"] = "All"
    imgui_frame(lambda: results.append(manager.ui()))
    assert set(results[-1].paths) == paths and results[-1].classes == {0}


@pytest.mark.parametrize("scale", [1., 2.])
def test_many_takes_scroll_only_the_list_and_keep_rows_one_line(tmp_path, imgui_frame, monkeypatch, scale):
    from myogestic import _scale, _theme
    from myogestic.widgets.training._session_state import scan_sessions

    for i in range(36):
        _dated_take(tmp_path, "", f"take-{i}", f"2026-10-{25 - i // 12:02d}T08:{i:02d}:00")
    _dated_take(tmp_path, "", "unlabelled", "2026-10-25T09:00:00", seconds={}, labels=())
    _dated_take(tmp_path, "", "unknown", "2026-10-25T10:00:00", seconds={"Unfamiliar": 30.})
    manager = SessionManager(str(tmp_path), class_names=["Rest", "Fist"])
    get_state(manager._widget_id).sessions = scan_sessions(str(tmp_path))
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    imgui.get_io().display_size = imgui.ImVec2(1280 * scale, 828 * scale)
    end_child, checkbox = imgui.end_child, imgui.checkbox
    scrolls, rows = [], []

    def end():
        scrolls.append((imgui.get_window_size().y, imgui.get_scroll_max_y()))
        end_child()

    def check(label, checked):
        rows.append(imgui.get_cursor_pos_y())
        return checkbox(label, checked)

    monkeypatch.setattr(imgui, "end_child", end)
    monkeypatch.setattr(imgui, "checkbox", check)
    def draw():
        imgui.begin_child("takes-cell", imgui.ImVec2(400 * scale, 260 * scale))
        manager.ui()
        imgui.end_child()

    imgui_frame(draw)
    scrolls.clear()
    rows.clear()
    imgui_frame(draw)
    assert len(scrolls) == 2, "header, summary and chips must live outside the list child"
    assert scrolls[0][1] > 0 and scrolls[1][1] == 0, scrolls
    assert len(rows) == 14, "only the newest day starts expanded"
    assert max(b - a for a, b in zip(rows, rows[1:], strict=False)) <= 28 * scale


def test_collapsed_day_stays_collapsed_when_selection_changes(tmp_path, imgui_frame, monkeypatch):
    from myogestic.widgets.training._session_state import scan_sessions

    _dated_take(tmp_path, "", "one", "2026-10-25T08:00:00")
    manager = SessionManager(str(tmp_path))
    state = get_state(manager._widget_id)
    state.sessions = scan_sessions(str(tmp_path))
    header, checkbox = imgui.collapsing_header, imgui.checkbox
    clicks, drawn = [True], []

    def collapse(label, *args):
        if clicks:
            clicks.pop()
            imgui.set_next_item_open(False, imgui.Cond_.always)
        return header(label, *args)

    def check(label, value):
        drawn.append(label)
        return checkbox(label, value)

    monkeypatch.setattr(imgui, "collapsing_header", collapse)
    monkeypatch.setattr(imgui, "checkbox", check)
    imgui_frame(manager.ui)
    state.sessions[0]["selected"] = True
    imgui_frame(manager.ui)
    assert drawn == [], "changing counts must not replace the group's ImGui identity"


def test_row_chips_keep_raw_names_and_mute_excluded_gestures(tmp_path, imgui_frame, monkeypatch):
    from myogestic.widgets.common import muted
    from myogestic.widgets.training._session_state import scan_sessions

    _dated_take(tmp_path, "", "one", "2026-10-25T08:00:00", seconds={"Rest": 10., "Fist": 20., "Unknown gesture": 3.})
    manager = SessionManager(str(tmp_path), class_names=["Rest", "Fist"])
    state = get_state(manager._widget_id)
    state.sessions = scan_sessions(str(tmp_path))
    state.sessions[0]["selected"] = True
    state.deactivated_classes.add(1)
    get_draw_list = imgui.get_window_draw_list
    labels = []

    class DrawList:
        def __init__(self, draw):
            self.draw = draw

        def __getattr__(self, name):
            return getattr(self.draw, name)

        def add_text(self, pos, color, text):
            labels.append((text, color, imgui.get_color_u32(muted())))
            self.draw.add_text(pos, color, text)

    monkeypatch.setattr(imgui, "get_window_draw_list", lambda: DrawList(get_draw_list()))
    imgui_frame(manager.ui)
    assert any(name == "Unknown gesture" for name, _, _ in labels)
    assert any(name == "Fist" and color == muted_color for name, color, muted_color in labels)
    assert any(name == "Rest" and color != muted_color for name, color, muted_color in labels)


@pytest.mark.parametrize("scale", [1., 2.])
@pytest.mark.parametrize("labelled", [False, True])
def test_compact_take_row_alignment_and_clicks(tmp_path, imgui_frame, monkeypatch, scale, labelled):
    from myogestic import _scale, _theme
    from myogestic.widgets.common import ui_px
    from myogestic.widgets.training import session_manager as module
    from myogestic.widgets.training._session_state import scan_sessions

    _dated_take(tmp_path, "", "one", "2026-10-25T08:00:00",
                seconds={"Rest": 30.} if labelled else {}, labels=(0,) if labelled else ())
    row = scan_sessions(str(tmp_path))[0]
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    style = imgui.get_style()
    style.scale_all_sizes(scale)
    style.font_scale_main = scale
    imgui.get_io().display_size = imgui.ImVec2(1280 * scale, 828 * scale)
    padding = tuple(style.frame_padding)
    positions, heights = {}, []
    checkbox, mono, dummy = imgui.checkbox, module.mono_text, imgui.dummy

    def remember(key):
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        positions[key] = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2)

    def check(label, value):
        result = checkbox(label, value)
        remember("checkbox")
        return result

    def text(value, color=None):
        mono(value, color)
        remember(value)

    def chip(size):
        dummy(size)
        remember("chip")

    monkeypatch.setattr(imgui, "checkbox", check)
    monkeypatch.setattr(module, "mono_text", text)
    monkeypatch.setattr(imgui, "dummy", chip)

    def draw():
        top = imgui.get_cursor_pos_y()
        module._render_row("compact", row, set(), ["Rest", "Fist"])
        heights.append(imgui.get_cursor_pos_y() - top)
        assert tuple(style.frame_padding) == padding

    for _ in range(2):
        imgui_frame(draw)
    assert max(heights) <= ui_px(28)
    assert heights[-1] == pytest.approx(ui_px(26), abs=scale)
    assert all(pos[1] == pytest.approx(positions["checkbox"][1], abs=1) for pos in positions.values())

    def click(position):
        io = imgui.get_io()
        io.add_mouse_pos_event(*position)
        imgui_frame(draw)
        io.add_mouse_button_event(0, True)
        imgui_frame(draw)
        io.add_mouse_button_event(0, False)
        imgui_frame(draw)

    for target in ("checkbox", "checkbox", "08:00", "chip" if labelled else "0:30"):
        selected = row["selected"]
        click(positions[target])
        assert row["selected"] is not selected, target
