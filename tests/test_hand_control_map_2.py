"""Hand chips and map cards: interaction and scaled layout contracts."""

from contextlib import contextmanager

import pytest
from imgui_bundle import imgui

from myogestic.widgets import ControlMapEditor
from myogestic.widgets import control_map_editor as maps
from myogestic.widgets.common import IDLE, SUCCESS
from myogestic.widgets.vhi import palette


def _editor(tmp_path):
    path = tmp_path / "controls.toml"
    path.write_text('[dofs]\nclose = "vhi.prediction.index"\n')
    editor = ControlMapEditor(path)
    editor.load()
    return editor


def _buttons(monkeypatch, click=""):
    seen = []
    for name in ("button", "small_button"):
        original = getattr(imgui, name)

        def spy(label, *args, _original=original, **kwargs):
            result = _original(label, *args, **kwargs)
            seen.append(label)
            return label.split("##")[0] == click or result

        monkeypatch.setattr(imgui, name, spy)
    return seen


@pytest.mark.parametrize("connected,tone", [(False, IDLE), (True, SUCCESS)])
def test_hand_header_and_idle_refresh(imgui_frame, monkeypatch, connected, tone):
    headers = []
    original = palette.panel_header
    monkeypatch.setattr(
        palette, "panel_header",
        lambda *a, **kw: (headers.append((a, kw)), original(*a, **kw))[1],
    )
    seen = _buttons(monkeypatch, "Refresh")
    refreshed = []
    imgui_frame(lambda: palette.vhi_movement_palette(
        ["Rest", "Fist"], connected=connected, on_movement=lambda _: None,
        on_refresh=lambda: refreshed.append(True),
    ))
    assert headers[0][0][0] == "Hand movements"
    assert headers[0][1]["status"] == tone
    assert refreshed == ([] if connected else [True])
    assert not any("Refresh from VHI" in label for label in seen)


def test_movement_chips_fit_their_names(imgui_frame, monkeypatch):
    widths = []
    original = imgui.button

    def spy(label, *args, **kwargs):
        result = original(label, *args, **kwargs)
        if "vhi_mv" in label:
            widths.append(imgui.get_item_rect_size().x)
        return label.startswith("Fist##") or result

    monkeypatch.setattr(imgui, "button", spy)
    picked = []
    imgui_frame(lambda: palette.vhi_movement_palette(
        ["Rest", "ThreeFingerPinch", "Fist"], connected=True,
        current_movement="Fist", on_movement=picked.append,
    ))
    assert picked == ["Fist"]
    assert widths[0] < widths[1]


def test_one_save_applies_visible_toml(imgui_frame, monkeypatch, tmp_path):
    editor = _editor(tmp_path)
    editor._raw_open = True
    editor._raw = '[dofs]\nopen = "vhi.prediction.thumb"\n'
    seen = _buttons(monkeypatch, "Save")
    changed = []
    imgui_frame(lambda: changed.append(editor.ui()))
    assert changed == [True]
    assert 'open = "vhi.prediction.thumb"' in editor.path.read_text()
    assert sum(label.split("##")[0] == "Save" for label in seen) == 1
    assert "Apply and save" not in seen
    assert not editor._dirty()


def test_invalid_toml_cannot_save_fields_in_its_place(imgui_frame, monkeypatch, tmp_path):
    editor = _editor(tmp_path)
    before = editor.path.read_text()
    editor._raw_open = True
    editor._raw = "[broken"
    _buttons(monkeypatch, "Save")
    imgui_frame(editor.ui)
    assert editor.path.read_text() == before
    assert editor._raw_error


def test_saving_repaired_toml_clears_the_load_error(imgui_frame, monkeypatch, tmp_path):
    editor = _editor(tmp_path)
    editor.path.write_text("[broken")
    editor.load()
    editor._raw_open = True
    editor._raw = '[dofs]\nfixed = "vhi.prediction.index"\n'
    _buttons(monkeypatch, "Save")
    imgui_frame(editor.ui)
    assert not editor._error
    assert editor._status()[0] == IDLE


def test_hidden_toml_edits_survive_reopening_and_block_disk_reload(tmp_path):
    editor = _editor(tmp_path)
    editor._sync_raw()
    editor._raw = '[dofs]\nother = "vhi.prediction.thumb"\n'
    editor._raw_open = False
    editor.path.write_text('[dofs]\nexternal = "vhi.prediction.index"\n')
    assert not editor.poll_disk()
    assert editor._conflict
    assert "other" in editor._raw
    assert editor.take_disk_version()
    assert not editor._dirty()


def test_field_edits_keep_the_open_toml_preview_in_step(imgui_frame, monkeypatch, tmp_path):
    editor = _editor(tmp_path)
    editor._raw_open = True
    editor._sync_raw()
    original = imgui.input_text

    def rename(label, value, *a, **kw):
        result = original(label, value, *a, **kw)
        return (True, "renamed") if label == "##name" else result

    monkeypatch.setattr(imgui, "input_text", rename)
    imgui_frame(editor.ui)
    assert 'renamed = "vhi.prediction.index"' in editor._raw
    assert not editor._raw_pending()


def test_two_editors_of_one_file_have_independent_input_ids(imgui_frame, monkeypatch, tmp_path):
    first = _editor(tmp_path)
    second = ControlMapEditor(first.path)
    seen = []
    original = imgui.input_text

    def spy(label, *a, **kw):
        if label == "##name":
            seen.append(imgui.get_id(label))
        return original(label, *a, **kw)

    monkeypatch.setattr(imgui, "input_text", spy)
    imgui_frame(lambda: (first.ui(), second.ui()))
    assert len(seen) == len(set(seen)) == 2


def test_dirty_count_includes_invalid_edits_and_removals(tmp_path):
    editor = _editor(tmp_path)
    editor._draft[0]["alias"] = ""
    assert editor._edited_count() == 1
    editor._draft.clear()
    assert editor._edited_count() == 1
    editor.add_control("other", "vhi.prediction.thumb")
    assert editor._edited_count() == 1


def test_cards_have_no_nested_headers(imgui_frame, monkeypatch, tmp_path):
    editor = _editor(tmp_path)
    editor._raw_open = True
    editor._raw = editor.raw_text()
    editor._draft[0]["threshold_fraction"] = 0.5
    for name in ("separator_text", "collapsing_header", "checkbox"):
        monkeypatch.setattr(imgui, name, lambda *a, **k: pytest.fail("nested section"))
    imgui_frame(editor.ui)


@pytest.mark.parametrize("initial", [None, 0.5])
def test_probability_click_balances_selection(imgui_frame, monkeypatch, tmp_path, initial):
    editor = _editor(tmp_path)
    entry = editor._draft[0]
    entry["threshold_fraction"] = initial
    _buttons(monkeypatch, "Treat as probability")
    imgui_frame(editor.ui)
    assert entry["threshold_fraction"] == (0.5 if initial is None else None)


@pytest.mark.parametrize("width", [320, 1600])
def test_toml_columns_and_activation_reflow(imgui_frame, monkeypatch, tmp_path, width):
    editor = _editor(tmp_path)
    editor._raw_open = True
    editor._raw = editor.raw_text()
    rects = {}
    for name in ("input_text", "input_text_multiline", "slider_float"):
        original = getattr(imgui, name)

        def spy(label, *a, _original=original, **kw):
            result = _original(label, *a, **kw)
            rects[label] = (imgui.get_item_rect_min(), imgui.get_item_rect_max())
            return result

        monkeypatch.setattr(imgui, name, spy)

    def draw():
        imgui.begin_child("sized", imgui.ImVec2(width, 400))
        editor.ui()
        imgui.end_child()

    imgui.get_io().display_size = imgui.ImVec2(2000, 1000)
    imgui_frame(draw)
    name, raw = rects["##name"][0], rects["##raw"][0]
    assert (raw.x > name.x) if width == 1600 else (raw.y > name.y)


def test_conflict_and_problems_use_danger_rows(imgui_frame, monkeypatch, tmp_path):
    editor = _editor(tmp_path)
    editor._conflict = True
    editor._draft[0]["alias"] = ""
    tones = []
    original = getattr(maps, "tinted_row", None)

    @contextmanager
    def spy(tone=None, **kw):
        tones.append(tone)
        with original(tone, **kw) as width:
            yield width

    monkeypatch.setattr(maps, "tinted_row", spy, raising=False)
    imgui_frame(editor.ui)
    assert sum(tone == maps.DANGER for tone in tones if tone is not None) >= 2


def test_state_actions_stay_in_their_tinted_rows(imgui_frame, monkeypatch, tmp_path):
    editor = _editor(tmp_path)
    editor._draft[0]["alias"] = "edited"
    editor._conflict = True
    tone = None
    seen = {}
    original_row = maps.tinted_row
    original_button = imgui.button

    @contextmanager
    def row(color=None, **kw):
        nonlocal tone
        tone = color
        with original_row(color, **kw) as width:
            yield width
        tone = None

    def button(label, *a, **kw):
        seen[label] = tone
        return original_button(label, *a, **kw)

    monkeypatch.setattr(maps, "tinted_row", row)
    monkeypatch.setattr(imgui, "button", button)
    imgui_frame(editor.ui)
    assert seen["Save"] is maps.WARNING
    assert seen["Reload from disk"] is maps.DANGER
    assert seen["Keep my edits"] is maps.DANGER


@pytest.mark.parametrize("width", [320, 960, 1800])
@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("state", ["edited", "conflict", "invalid"])
def test_scaled_widgets_keep_controls_inside_their_cells(
    imgui_frame, monkeypatch, tmp_path, width, scale, dark, raw, state,
):
    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_override", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    editor = _editor(tmp_path)
    editor._draft[0]["threshold_fraction"] = 0.5
    editor._draft[0]["debounce_s"] = 0.2
    editor._raw_open = raw
    editor._sync_raw()
    editor._conflict = state == "conflict"
    if state == "invalid":
        editor._draft[0]["alias"] = ""
    overhang = []
    for method in ("button", "small_button", "input_text", "input_text_multiline", "slider_float"):
        original = getattr(imgui, method)

        def spy(label, *a, _original=original, **kw):
            edge = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            result = _original(label, *a, **kw)
            overhang.append((label, imgui.get_item_rect_max().x - edge))
            return result

        monkeypatch.setattr(imgui, method, spy)

    io = imgui.get_io()
    io.display_size = imgui.ImVec2(2000, 2200)
    for _ in range(3):
        overhang.clear()
        imgui.new_frame()
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 2100))
        imgui.begin("scaled", None, imgui.WindowFlags_.no_saved_settings)
        editor.ui()
        palette.vhi_movement_palette(
            ["Rest", "ThreeFingerPinch", "A very long movement name that needs truncating"],
            connected=True, on_movement=lambda _: None, on_refresh=lambda: None,
        )
        imgui.end()
        imgui.end_frame()
    assert not [(label, n) for label, n in overhang if n > 1.0]
