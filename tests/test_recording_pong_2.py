"""Recording and Pong use the 2.0 state rows at narrow widths and both scales."""

from contextlib import contextmanager

import numpy as np
import pytest
from imgui_bundle import imgui

from myogestic import _scale, _theme
from myogestic.core import AppState, Context
from myogestic.session import Session
from myogestic.stream import StreamInfo
from myogestic.widgets import common, pong
from myogestic.widgets.panels import recording


def _theme_at(monkeypatch, scale, dark=False):
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale


def _observe(monkeypatch, module):
    rows, texts, buttons = [], [], []
    row = common.tinted_row
    mono = module.mono_text
    button = imgui.button

    @contextmanager
    def capture_row(tone=None, **kwargs):
        rows.append(tone)
        with row(tone, **kwargs) as width:
            yield width

    def capture_mono(text, *args):
        texts.append(text)
        mono(text, *args)

    def capture_button(label, *args):
        color = tuple(imgui.get_style().color_(imgui.Col_.button))
        border = imgui.get_style().frame_border_size
        clicked = button(label, *args)
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        buttons.append((label, color, border, (lo.x, lo.y, hi.x, hi.y)))
        return clicked

    monkeypatch.setattr(module, "tinted_row", capture_row, raising=False)
    monkeypatch.setattr(module, "mono_text", capture_mono)
    monkeypatch.setattr(imgui, "button", capture_button)
    return rows, texts, buttons


@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("dark", [False, True])
def test_record_idle_is_red_full_width_and_explains_participant_gate(
    imgui_frame, monkeypatch, scale, dark,
):
    _theme_at(monkeypatch, scale, dark)
    _, _, buttons = _observe(monkeypatch, recording)
    ctx = Context(require_participant=True)
    recorder = recording.RecordButton(on_record=lambda: None, on_stop=lambda: None)
    captions, bounds = [], []
    wrapped = imgui.text_wrapped

    def caption(text):
        captions.append(text)
        wrapped(text)

    monkeypatch.setattr(imgui, "text_wrapped", caption)

    def draw():
        imgui.begin_child("narrow", imgui.ImVec2(320, 400))
        left = imgui.get_cursor_screen_pos().x
        bounds.append((left, left + imgui.get_content_region_avail().x))
        recorder.ui(ctx)
        imgui.end_child()

    imgui_frame(draw)
    record = next(b for b in buttons if "  Record" in b[0])
    assert record[1] == pytest.approx(tuple(common.DANGER))
    assert record[3][0] == pytest.approx(bounds[0][0])
    assert record[3][2] == pytest.approx(bounds[0][1], abs=1)
    assert record[3][3] - record[3][1] >= common.ui_px(52)
    assert "Set a participant first — recordings are saved under their ID." in captions


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_recording_row_has_elapsed_clock_and_stop_inside_narrow_cell(
    imgui_frame, monkeypatch, scale,
):
    _theme_at(monkeypatch, scale)
    rows, texts, buttons = _observe(monkeypatch, recording)
    monkeypatch.setattr(recording.time, "monotonic", lambda: 42.7)
    recorder = recording.RecordButton(on_record=lambda: None, on_stop=lambda: None)
    recorder._started = 0.0
    bounds = []

    def draw():
        imgui.begin_child("narrow", imgui.ImVec2(320, 400))
        bounds.append(imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x)
        recorder.ui(Context(state=AppState.RECORDING))
        imgui.end_child()

    imgui_frame(draw)
    assert rows == [common.DANGER]
    assert any(text.startswith("0:42.7") for text in texts)
    stop = next(b for b in buttons if "Stop" in b[0])
    assert stop[3][2] <= bounds[0]


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_naming_dialog_previews_safe_stem_and_offers_primary_save_and_outlined_discard(
    imgui_frame, monkeypatch, tmp_path, scale,
):
    _theme_at(monkeypatch, scale)
    rows, texts, buttons = _observe(monkeypatch, recording)
    session = Session(str(tmp_path))
    ctx = Context(state=AppState.RECORDING, session=session)
    recorder = recording.RecordButton(
        on_record=lambda: None, on_stop=lambda: None, on_discard=lambda: None,
    )
    recorder._naming = True
    recorder._captured = 42.7
    recorder._name = "../../day 2"
    captions, fields = [], []
    text = imgui.text_unformatted
    input_text = imgui.input_text_with_hint

    def caption(value):
        captions.append(value)
        text(value)

    def field(*args):
        width = imgui.get_content_region_avail().x
        result = input_text(*args)
        fields.append((imgui.get_item_rect_size().x, width))
        return result

    monkeypatch.setattr(imgui, "text_unformatted", caption)
    monkeypatch.setattr(imgui, "input_text_with_hint", field)
    imgui_frame(lambda: recorder.ui(ctx))
    imgui_frame(lambda: recorder.ui(ctx))
    assert rows == [None, None]
    assert any(t.startswith("naming · 0:42.7") for t in texts)
    assert "Name (optional)" in captions
    assert any(session.path.name + "_day-2" in t for t in texts)
    assert session.name == "", "preview must not rename or finalise the take"
    assert fields[-1][0] == pytest.approx(fields[-1][1], abs=1)
    save = next(b for b in buttons if "Save" in b[0])
    discard = next(b for b in buttons if "Discard" in b[0])
    assert save[1] == pytest.approx(tuple(common.PRIMARY_FILL))
    assert "Discard 0:42.7" in discard[0]
    assert discard[1] != pytest.approx(tuple(common.DANGER))
    assert discard[2] == pytest.approx(common.ui_px(1))


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_pong_serve_is_primary_in_court_and_header_stop_fits(
    imgui_frame, monkeypatch, scale,
):
    _theme_at(monkeypatch, scale)
    rows, texts, buttons = _observe(monkeypatch, pong)
    task = pong.PongTask(court_height=0)
    bounds = []

    def draw():
        imgui.begin_child("narrow", imgui.ImVec2(320, 400))
        bounds.append(imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x)
        task.ui(0.0)
        imgui.end_child()

    imgui_frame(draw)
    serve = next(b for b in buttons if "Serve" in b[0])
    assert serve[1] == pytest.approx(tuple(common.PRIMARY_FILL))
    task._serve()
    imgui_frame(draw)
    assert rows == []
    assert any("rally" in t for t in texts)
    stop = next(b for b in buttons if "pong_stop" in b[0])
    assert stop[3][2] <= bounds[-1]


def test_pong_score_is_measured_and_drawn_in_display_font(imgui_frame, monkeypatch):
    font = imgui.get_io().fonts.add_font_default()
    monkeypatch.setattr(pong, "display_font", lambda: font)
    used = []
    push = imgui.push_font

    def track_font(value, *args):
        used.append(value)
        push(value, *args)

    monkeypatch.setattr(imgui, "push_font", track_font)
    task = pong.PongTask()
    imgui_frame(lambda: task._court_ui(None))
    assert font in used


def test_pong_fixed_court_height_follows_live_scale(imgui_frame, monkeypatch):
    task = pong.PongTask(court_height=120)
    heights = []

    def draw():
        task._court_ui(None)
        heights.append(imgui.get_item_rect_size().y)

    for scale in (1.0, 2.0):
        monkeypatch.setattr(_scale, "_current", scale)
        imgui_frame(draw)
    assert heights == pytest.approx([120, 240])


@pytest.mark.parametrize("kind", ["recording", "pong"])
def test_shortened_readouts_show_ellipsis_and_keep_the_full_tooltip(imgui_frame, monkeypatch, kind):
    texts, tips, widths = [], [], []
    module = recording if kind == "recording" else pong
    mono = module.mono_text

    def capture(text, *args):
        texts.append(text)
        mono(text, *args)
        widths.append(imgui.get_item_rect_size().x)

    monkeypatch.setattr(module, "mono_text", capture)
    monkeypatch.setattr(imgui, "set_item_tooltip", tips.append)
    task = pong.PongTask()
    full = "naming · 0:42.7 captured" if kind == "recording" else task._detail(0.4)
    imgui_frame(lambda: recording.RecordButton._mono_detail(full, 70) if kind == "recording"
                else task._detail_ui(0.4, 70))
    assert texts[0].endswith("…")
    assert widths[0] <= 70
    assert tips == [full]


def test_status_pill_scales_padding_indicator_and_label_offset(imgui_frame, monkeypatch):
    boxes, texts, sizes = [], [], []

    class DrawList:
        def add_rect_filled(self, lo, hi, color, rounding):
            boxes.append((lo.x, lo.y, hi.x, hi.y, rounding))

        def add_text(self, pos, color, label):
            texts.append((pos.x, pos.y))

    monkeypatch.setattr(imgui, "get_window_draw_list", lambda: DrawList())
    monkeypatch.setattr(imgui, "calc_text_size", lambda label: imgui.ImVec2(50, 20))

    def draw():
        common.status_pill("IDLE", common.IDLE)
        sizes.append(imgui.get_item_rect_size().x)

    for scale in (1.0, 2.0):
        monkeypatch.setattr(_scale, "_current", scale)
        imgui_frame(draw)
    assert sizes == pytest.approx([82, 114])
    first, second = boxes[1], boxes[3]
    assert second[2] - second[0] == pytest.approx(2 * (first[2] - first[0]))
    assert second[4] == pytest.approx(2 * first[4])
    assert texts[1][0] - boxes[2][0] == pytest.approx(2 * (texts[0][0] - boxes[0][0]))


@pytest.mark.parametrize("classes", [["Fist", "Open hand"], ["F" * 30, "O" * 30]])
def test_filename_preview_matches_archive_including_recorded_labels(tmp_path, classes):
    session = Session(str(tmp_path))
    session.init_stream("emg", StreamInfo(n_channels=1, fs=100))
    session.append("emg", np.zeros((3, 1), dtype=np.float32), np.array([1.0, 2.0, 3.0]))
    session.add_label(1, timestamp=1.0)
    session.add_label(0, timestamp=2.0)
    ctx = Context(state=AppState.RECORDING, session=session, class_names=classes)
    recorder = recording.RecordButton(on_record=lambda: None, on_stop=lambda: None)
    recorder._name = "../day 2"
    preview = recorder._file_stem(ctx)
    session.name = recorder._name
    session.save_meta("test", classes)
    assert session.pack_to_zip().name == preview + ".session.zip"
