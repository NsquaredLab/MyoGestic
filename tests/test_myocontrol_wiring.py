"""What `examples/start_here/myocontrol.py` claims on a fresh launch.

The load-bearing one is `test_predict_uses_the_models_mode_not_the_switch`. Everything
else here is a smoke check; that one pins a design decision that a plausible-looking
one-line edit would undo, and it fails loudly when it does.
"""

import ast
import inspect
import json
import runpy
from pathlib import Path

import numpy as np
import pytest

import myogestic.core
import myogestic.remote
import myogestic.stream
from myogestic.controls import ControlLink

_APP = Path(__file__).resolve().parent.parent / "examples" / "start_here" / "myocontrol.py"


@pytest.fixture
def app_module(monkeypatch):
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    # `launchable()` swallows the FileNotFoundError, so this only spares a dev box
    # without VHI installed a pointless env probe at import.
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    monkeypatch.syspath_prepend(str(_APP.parent))
    return runpy.run_path(str(_APP), run_name="__main__")


class OnlyPredictProba:
    """A classifier. Asking it for `.predict` is the bug this stub detects."""

    def predict_proba(self, x):
        return np.array([[0.1, 0.9]])


def test_myocontrol_requires_participant(app_module):
    assert app_module["app"].ctx.require_participant is True


def test_myocontrol_opens_timed_at_five_seconds_with_two_second_warmup(app_module):
    controls = app_module["recording"]
    assert controls._timed is True
    assert controls._take_lengths == (3.0, 5.0, 10.0)
    assert controls._warmups == (0.0, 1.0, 2.0, 3.0)
    assert controls._take_lengths[controls._length_index] == 5.0
    assert controls._warmups[controls._warmup_index] == 2.0


@pytest.mark.parametrize("phase", ["idle", "warmup", "recording", "saved", "early", "manual"])
@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("dark", [False, True])
def test_timed_record_fits_real_step(app_module, monkeypatch, implot_frame, phase, scale, dark):
    from types import SimpleNamespace

    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    size = imgui.ImVec2(1280 * scale, 828 * scale)
    imgui.get_io().display_size = size
    ctx, controls = app_module["app"].ctx, app_module["recording"]
    ctx.participant, ctx.current_label = "P-014", 1
    app_module["steps"].active = 1
    now = [0.0]
    controls._machine._clock = lambda: now[0]
    controls._timed = phase != "manual"

    def start():
        ctx.state = "recording"
        ctx.session = SimpleNamespace(add_label=lambda i: None)

    controls._on_record = start
    controls._machine._on_stop = lambda: setattr(ctx, "state", "idle")
    if phase != "idle":
        controls._start(ctx)
        if phase != "warmup":
            now[0] = 2.0
            controls._sync(ctx)
            now[0] = 3.4 if phase in ("recording", "early", "manual") else 7.0
            controls._sync(ctx)
            if phase == "early":
                controls._machine.stop()
    measurements, overlays = [], []
    render = app_module["record_ui"]

    def tracked(ctx):
        render(ctx)
        measurements.append((imgui.get_cursor_pos_y(), imgui.get_window_size().y, imgui.get_scroll_max_y()))

    monkeypatch.setitem(app_module["myocontrol_ui"].__globals__, "record_ui", tracked)
    overlay = app_module["_take_overlay"]

    def tracked_overlay(take):
        overlays.append(take.phase)
        overlay(take)

    monkeypatch.setitem(app_module["myocontrol_ui"].__globals__, "_take_overlay", tracked_overlay)

    def draw():
        imgui.set_next_window_size(size)
        imgui.begin("timed-workflow")
        app_module["myocontrol_ui"](ctx)
        imgui.end()

    for _ in range(3):
        implot_frame(draw)
    cursor, height, scroll = measurements[-1]
    assert cursor <= height and scroll == 0, measurements
    assert overlays[-1] == controls.take.phase


def test_timed_take_stops_when_another_step_is_open(app_module, monkeypatch, implot_frame):
    from types import SimpleNamespace

    controls, ctx = app_module["recording"], app_module["app"].ctx
    ctx.participant, ctx.current_label = "P-014", 1
    controls._timed = True
    now, calls = [0.0], []
    controls._machine._clock = lambda: now[0]

    def start():
        calls.append("record")
        ctx.state = "recording"
        ctx.session = SimpleNamespace(add_label=lambda i: None)

    def stop():
        calls.append("stop")
        ctx.state = "idle"

    controls._on_record = start
    controls._machine._on_stop = stop
    controls._start(ctx)
    app_module["steps"].active = 3
    now[0] = 2.0
    implot_frame(lambda: app_module["myocontrol_ui"](ctx))
    now[0] = 7.0
    implot_frame(lambda: app_module["myocontrol_ui"](ctx))
    assert calls == ["record", "stop"]
    assert controls.take.phase == "saved"


def test_myocontrol_autosaves_models(app_module):
    from myogestic.ml import save_pickle

    assert app_module["pipeline"].autosave_dir == "sessions"
    assert app_module["pipeline"].save_model is save_pickle


def test_pushed_rows_name_alias_target_and_signed_value(app_module, monkeypatch):
    from myogestic.controls import load_control_map

    pushed = app_module["_pushed"]
    assert pushed() == []
    mapping = load_control_map({"dofs": {"grip": "vhi.prediction.index", "mode": "hand.mode"}})
    monkeypatch.setitem(pushed.__globals__, "CONTROL_MAP", mapping)
    app_module["pipeline"].predictions = {"controls": {"grip": -0.25, "mode": "rest"}}
    assert pushed() == [("grip → vhi.prediction.index", "-0.25"), ("mode → hand.mode", "rest")]


def test_drive_uses_compact_smoothing_and_sent_card(app_module, monkeypatch, imgui_frame):
    from imgui_bundle import imgui

    assert app_module["output_filter"]._compact is True
    texts, headers = [], []
    monkeypatch.setattr(imgui, "text_unformatted", texts.append)
    monkeypatch.setattr(imgui, "text_colored", lambda color, text: texts.append(text))
    monkeypatch.setitem(app_module["drive_ui"].__globals__, "panel_header",
                        lambda title, *a, **k: headers.append(title))
    imgui_frame(app_module["drive_ui"])
    assert headers == ["Sent to the hand"]
    assert "nothing sent yet" in texts


@pytest.mark.parametrize("scale,size", [(1.0, (1280, 828)), (2.0, (2560, 1656))])
@pytest.mark.parametrize("predicting", [False, True])
def test_drive_fits_real_light_step_layout(app_module, monkeypatch, implot_frame, scale, size, predicting):
    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    imgui.get_io().display_size = imgui.ImVec2(*size)
    app_module["steps"].active = 3
    if predicting:
        app_module["app"].ctx.state = "predicting"
        app_module["pipeline"].model = object()
        app_module["pipeline"].predictions = {
            "class": 1, "proba": [0.2, 0.8], "controls": {"prediction": 0.8, "control": 0.0}
        }
    render = app_module["drive_ui"]
    measurements = []
    actions = []
    button = imgui.button

    def action(label, *args):
        available = imgui.get_content_region_avail().x
        result = button(label, *args)
        if label in ("Start predicting", "Stop predicting"):
            actions.append((imgui.get_item_rect_size().x, available))
        return result

    monkeypatch.setattr(imgui, "button", action)

    def tracked():
        render()
        measurements.append((imgui.get_cursor_pos_y(), imgui.get_window_size().y, imgui.get_scroll_max_y()))

    monkeypatch.setitem(app_module["myocontrol_ui"].__globals__, "drive_ui", tracked)

    def draw():
        imgui.set_next_window_size(imgui.ImVec2(*size))
        imgui.begin("drive-workflow")
        app_module["myocontrol_ui"](app_module["app"].ctx)
        imgui.end()

    # Auto-height cards and their parent each settle from the previous frame.
    for _ in range(3):
        implot_frame(draw)
    cursor, height, scroll = measurements[-1]
    assert cursor <= height and scroll == 0, measurements
    assert actions and all(abs(width - available) <= 1 for width, available in actions), actions


def test_myocontrol_steps(app_module):
    assert app_module["steps"].steps == ["Connect", "Record", "Train", "Drive"]


def test_header_is_one_bare_area(app_module):
    from myogestic import Px

    layout = app_module["layout"]
    assert not {"title", "steps", "participant", "state"} & layout.panel_names
    for grid in (layout._wide, layout._narrow):
        assert "header" in grid._bare
        assert grid._areas["header"] == (0, 1, 0, grid.cols)
        assert grid._row_tracks[0] == Px(52)


def test_status_is_one_bare_area(app_module):
    from myogestic import Px

    layout = app_module["layout"]
    for grid in (layout._wide, layout._narrow):
        assert "status" in grid._bare
        assert grid._areas["status"] == (grid.rows - 1, grid.rows, 0, grid.cols)
        assert grid._row_tracks[-1] == Px(26)


@pytest.mark.parametrize("width", [1280, 900])
def test_myocontrol_root_has_no_vertical_scroll(app_module, monkeypatch, implot_frame, width):
    from imgui_bundle import imgui

    from myogestic import _theme

    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: True)
    _theme.apply_theme()
    imgui.get_io().display_size = imgui.ImVec2(width, 828)
    scroll = []

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 828))
        imgui.begin("myocontrol-root", flags=imgui.WindowFlags_.no_title_bar)
        app_module["myocontrol_ui"](app_module["app"].ctx)
        scroll.append(imgui.get_scroll_max_y())
        imgui.end()

    implot_frame(draw)
    # ImGui computes scroll limits on Begin from the preceding frame's content.
    implot_frame(draw)
    assert scroll[-1] == 0


def test_myocontrol_record_has_one_header(app_module, monkeypatch, imgui_frame):
    from myogestic.widgets.panels import recording

    headers = []
    monkeypatch.setattr(recording, "panel_header", lambda title, *a, **k: headers.append(title))
    ctx = app_module["app"].ctx
    ctx.participant = "P-014"
    imgui_frame(lambda: app_module["record_ui"](ctx))
    assert headers == []


def test_record_locked_without_participant(app_module, monkeypatch, imgui_frame):
    from imgui_bundle import imgui

    render = app_module.get("record_ui")
    assert callable(render), "Record needs a participant-aware panel"
    ctx = app_module["app"].ctx
    opened, controls, messages = [], [], []
    monkeypatch.setattr(app_module["participant"], "open", lambda: opened.append(True))
    monkeypatch.setattr(app_module["recording"], "ui", controls.append)
    text = imgui.text_unformatted

    def remember(label):
        messages.append(label)
        text(label)

    monkeypatch.setattr(imgui, "text_unformatted", remember)
    button = render.__globals__["primary_button"]

    def click(label):
        button(label)
        return label == "Set participant"

    monkeypatch.setitem(render.__globals__, "primary_button", click)
    imgui_frame(lambda: render(ctx))
    assert opened == [True]
    assert controls == []
    assert "Set a participant to record" in messages


def test_recorded_block_reads_disk(app_module, tmp_path, monkeypatch, imgui_frame):
    from imgui_bundle import imgui

    from myogestic.session import recorded_time

    render = app_module.get("record_ui")
    assert callable(render), "Record needs a recorded-time summary"
    monkeypatch.chdir(tmp_path)
    ctx = app_module["app"].ctx
    ctx.participant = "P-014"
    take = tmp_path / "sessions" / ctx.participant / "take"
    take.mkdir(parents=True)
    meta = take / "meta.json"
    meta.write_text(json.dumps({"duration_s": 74.0, "class_seconds": {"Rest": 60, "Fist": 14}}))
    reads, messages, bars = [], [], []
    read = recorded_time
    text, colored, bar = imgui.text_unformatted, imgui.text_colored, imgui.progress_bar

    def read_disk(folder):
        reads.append(Path(folder))
        return read(folder)

    def remember(label):
        messages.append(label)
        text(label)

    def remember_colored(color, label):
        messages.append(label)
        colored(color, label)

    def remember_bar(fraction, size, overlay):
        bars.append(fraction)
        bar(fraction, size, overlay)

    monkeypatch.setitem(render.__globals__, "recorded_time", read_disk)
    monkeypatch.setattr(imgui, "text_unformatted", remember)
    monkeypatch.setattr(imgui, "text_colored", remember_colored)
    monkeypatch.setattr(imgui, "progress_bar", remember_bar)
    imgui_frame(lambda: render(ctx))
    assert reads == [Path("sessions/P-014")]
    assert {"1 takes · 1:14", "Rest", "Fist", "1:00", "0:14"} <= set(messages)
    assert len(bars) == 2
    imgui_frame(lambda: render(ctx))
    assert len(reads) == 1, "Do not rescan disk every frame"

    ctx.state = "recording"
    imgui_frame(lambda: render(ctx))
    meta.write_text(json.dumps({"duration_s": 90.0, "class_seconds": {"Rest": 60, "Fist": 30}}))
    ctx.state = "idle"
    messages.clear()
    imgui_frame(lambda: render(ctx))
    assert len(reads) == 2
    assert "1 takes · 1:30" in messages
    ctx.participant = "P-015"
    messages.clear()
    imgui_frame(lambda: render(ctx))
    assert reads[-1] == Path("sessions/P-015")
    assert "Nothing yet. Each gesture's recorded time shows here as you go." in messages


def test_empty_recorded_block_keeps_whole_guidance(app_module, monkeypatch, imgui_frame):
    from imgui_bundle import imgui

    from myogestic.session import RecordedTime

    messages, bounds = [], []
    text = imgui.text_colored
    ctx = app_module["app"].ctx
    ctx.participant = "P-014"

    def remember(color, label):
        text(color, label)
        if label.startswith("Nothing yet."):
            messages.append(label)
            hi = imgui.get_item_rect_max()
            origin, size = imgui.get_window_pos(), imgui.get_window_size()
            bounds.append((hi.x <= origin.x + size.x, hi.y <= origin.y + size.y))

    def draw():
        imgui.begin_child("side-panel", imgui.ImVec2(400, 300))
        app_module["_recorded_block"](ctx, RecordedTime(0, 0.0, {}))
        imgui.end_child()

    monkeypatch.setattr(imgui, "text_colored", remember)
    imgui_frame(draw)
    assert messages == ["Nothing yet. Each gesture's recorded time shows here as you go."]
    assert all(x and y for x, y in bounds)


@pytest.mark.parametrize(
    ("panel", "reason"),
    [
        ("model_ui", "Record a take or select takes below first."),
        ("drive_ui", "No model yet — train or load a model first."),
    ],
)
def test_disabled_forward_action_explains_why(app_module, monkeypatch, imgui_frame, panel, reason):
    from imgui_bundle import imgui

    messages = []
    text = imgui.text_colored

    def remember(color, label):
        messages.append(label)
        text(color, label)

    monkeypatch.setattr(imgui, "text_colored", remember)
    imgui_frame(app_module[panel])
    assert reason in messages


def test_status_stays_one_line_with_a_long_model_name(app_module, monkeypatch, imgui_frame):
    from imgui_bundle import imgui

    ctx = app_module["app"].ctx
    ctx.participant = "P-014"
    app_module["pipeline"].model = object()
    app_module["pipeline"].last_saved_model = "sessions/P-014/" + "a_very_long_name_" * 20 + ".joblib"
    items = []
    text = imgui.text_colored

    def remember(color, label):
        text(color, label)
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        right = imgui.get_window_pos().x + imgui.get_window_size().x - imgui.get_style().window_padding.x
        items.append((label, lo.y, hi.x <= right + 1))

    monkeypatch.setattr(imgui, "text_colored", remember)
    imgui_frame(lambda: app_module["status_ui"](ctx))
    assert len(items) == 3
    assert len({y for _, y, _ in items}) == 1
    assert all(fits for _, _, fits in items)
    assert items[-1][0].startswith("Model: ") and items[-1][0].endswith("…")


def test_myocontrol_uses_no_private_imports():
    tree = ast.parse(_APP.read_text())
    private = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            private.extend(name.name for name in node.names if name.name.startswith("_"))
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            private.append(node.attr)
    assert private == []


def test_connect_step_uses_one_picker_for_stream_management(app_module, monkeypatch, imgui_frame):
    picker = app_module["device"]
    assert picker._selectable and not picker._show_header
    assert picker._on_add is not None
    assert picker._on_remove == app_module["app"].remove_stream
    assert "streams" not in app_module
    drawn = []
    monkeypatch.setattr(picker, "ui", drawn.append)
    ctx = app_module["app"].ctx
    imgui_frame(lambda: app_module["connect_ui"](ctx))
    assert drawn == [ctx]


def test_connect_fits_default_step_cell(app_module, monkeypatch, imgui_frame):
    from imgui_bundle import imgui

    from myogestic import _theme

    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    heights = []

    def draw():
        imgui.begin_child("connect-card", imgui.ImVec2(400, 400))
        top = imgui.get_cursor_pos_y()
        app_module["panel_header"]("Connect")
        app_module["connect_ui"](app_module["app"].ctx)
        heights.append(imgui.get_cursor_pos_y() - top)
        imgui.end_child()

    imgui_frame(draw)
    assert heights[0] <= 400 - 2 * imgui.get_style().window_padding.y


@pytest.mark.parametrize("running,bound,launchable,expected", [
    (False, False, True, ["Connect"]),
    (False, False, False, ["Connect"]),
    (False, True, True, []),
    (True, False, True, ["Stop"]),
    (True, True, True, ["Stop"]),
])
def test_hand_actions_fit_one_row(app_module, monkeypatch, imgui_frame, running, bound, launchable, expected):
    from imgui_bundle import imgui

    monkeypatch.setattr(type(app_module["processes"]), "running", lambda *args: running)
    monkeypatch.setitem(app_module["hand_ui"].__globals__, "hand_processes", [("hand", ["hand"])] if launchable else [])
    monkeypatch.setattr(type(app_module["binder"]), "poll", lambda self: None)
    if bound:
        app_module["link"]._bus = object()
    actions = []
    button = imgui.small_button

    def tracked(label, *args):
        actions.append(label.split("##")[0])
        return button(label, *args)

    monkeypatch.setattr(imgui, "small_button", tracked)
    heights = []

    def draw():
        top = imgui.get_cursor_pos_y()
        app_module["hand_ui"]()
        heights.append(imgui.get_cursor_pos_y() - top)

    try:
        imgui_frame(draw)
        assert actions == expected
        assert heights[0] <= imgui.get_frame_height() + app_module["ui_px"](8) + imgui.get_style().item_spacing.y
    finally:
        app_module["link"]._bus = None


def test_record_step_done_reads_disk(app_module, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = app_module["app"].ctx
    done = app_module["_step_done"]
    assert not done(ctx)[1]
    ctx.participant = "P-014"
    assert not done(ctx)[1]
    folder = tmp_path / "sessions" / "P-014"
    folder.mkdir(parents=True)
    (folder / "unrelated.txt").touch()
    assert not done(ctx)[1]
    take = folder / "P-014_2026-10-24_15-12-03"
    take.mkdir()
    assert done(ctx)[1]
    take.rmdir()
    take.with_suffix(".session.zip").touch()
    assert done(ctx)[1]
    ctx.participant = "P-015"
    assert not done(ctx)[1]
    ctx.participant = ""
    assert not done(ctx)[1]


@pytest.mark.parametrize("size", [(1440, 900), (900, 1100)], ids=["wide", "narrow"])
def test_myocontrol_renders_each_step(app_module, imgui_frame, size):
    from imgui_bundle import imgui, implot

    def draw():
        imgui.set_window_size(imgui.ImVec2(*size))
        app_module["myocontrol_ui"](app_module["app"].ctx)

    implot.create_context()
    try:
        for index in range(4):
            app_module["steps"].active = index
            imgui_frame(draw)
    finally:
        implot.destroy_context()


def test_myocontrol_binding_notifies_once(app_module, monkeypatch):
    bus = object()

    def ensure(link):
        link._bus = bus
        return bus

    monkeypatch.setattr(ControlLink, "ensure", ensure)
    try:
        app_module["_bind"]()
        app_module["_bind"]()
        notices = app_module["app"].ctx.notifications
        assert [(n.title, n.detail, n.kind) for n in notices] == [
            ("Virtual Hand connected", "Start predicting drives it.", "info")
        ]
    finally:
        app_module["link"]._bus = None


@pytest.mark.parametrize("size", [(1140, 800), (1280, 800), (900, 1100)])
def test_myocontrol_header_fits_the_theme_padding(app_module, monkeypatch, implot_frame, size):
    from imgui_bundle import imgui

    from myogestic import _theme

    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    bounds = []

    def remember():
        maximum = imgui.get_item_rect_max()
        pos = imgui.get_window_pos()
        extent = imgui.get_window_size()
        padding = imgui.get_style().window_padding
        bounds.append((
            maximum.x <= pos.x + extent.x - padding.x,
            maximum.y <= pos.y + extent.y - imgui.get_cursor_start_pos().y,
        ))

    text_colored = imgui.text_colored

    def text(color, label):
        text_colored(color, label)
        if label == "Myocontrol":
            remember()

    monkeypatch.setattr(imgui, "text_colored", text)
    ui_globals = app_module["header"].ui.__func__.__globals__
    status_pill = ui_globals["status_pill"]

    def pill(label, color):
        status_pill(label, color)
        remember()

    monkeypatch.setitem(ui_globals, "status_pill", pill)
    steps = app_module["steps"]
    step_ui = steps.ui

    def navigation(done, **kwargs):
        active = step_ui(done, **kwargs)
        remember()
        return active

    monkeypatch.setattr(steps, "ui", navigation)

    def draw():
        imgui.set_window_size(imgui.ImVec2(*size))
        app_module["app"].ctx.state = "predicting"
        app_module["myocontrol_ui"](app_module["app"].ctx)

    implot_frame(draw)
    assert bounds and all(x and y for x, y in bounds)


def test_header_controls_share_a_row_after_resizing(app_module, monkeypatch, implot_frame):
    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    ctx = app_module["app"].ctx
    ctx.participant = "P-014"
    items = []
    bounds = []
    button = imgui.button
    pill = app_module["header"].ui.__func__.__globals__["status_pill"]

    def remember():
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        origin, size = imgui.get_window_pos(), imgui.get_window_size()
        items.append((lo.x, hi.x, (lo.y + hi.y) / 2))
        bounds.append((hi.x <= origin.x + size.x, hi.y <= origin.y + size.y))

    def tracked_button(label, *args):
        result = button(label, *args)
        if "###step" in label or label.endswith("###chip"):
            remember()
        return result

    def tracked_pill(label, color):
        pill(label, color)
        if label == "IDLE":
            remember()

    monkeypatch.setattr(imgui, "button", tracked_button)
    monkeypatch.setitem(app_module["header"].ui.__func__.__globals__, "status_pill", tracked_pill)
    for scale, width in [(1.0, 900), (1.3, 1440), (0.85, 900)]:
        monkeypatch.setattr(_scale, "_current", scale)
        _theme.apply_theme()
        imgui.get_style().scale_all_sizes(scale)
        imgui.get_style().font_scale_main = scale
        items.clear()
        bounds.clear()
        imgui.get_io().display_size = imgui.ImVec2(width, 1100)

        def draw(width=width):
            imgui.set_next_window_size(imgui.ImVec2(width, 1100))
            imgui.begin("scaled-workflow")
            app_module["myocontrol_ui"](ctx)
            imgui.end()

        implot_frame(draw)
        assert len(items) == 6
        assert all(x and y for x, y in bounds)
        # Connectors and buttons round their baseline separately at fractional scales.
        assert max(y for _, _, y in items) - min(y for _, _, y in items) <= 2 * scale, (scale, items)
        assert all(left[1] <= right[0] for left, right in zip(items, items[1:], strict=False))


def test_myocontrol_drive_toggle_balances_selected_style(app_module, monkeypatch, imgui_frame):
    pipeline = app_module["pipeline"]
    pipeline.model = ("Classification", OnlyPredictProba())
    monkeypatch.setitem(app_module["drive_ui"].__globals__, "primary_button", lambda label, **k: True)
    imgui_frame(app_module["drive_ui"])
    assert app_module["app"].ctx.state == "predicting"
    imgui_frame(app_module["drive_ui"])
    assert app_module["app"].ctx.state == "idle"


@pytest.mark.parametrize("changed", ["mode", "features", "notch"])
def test_myocontrol_warns_when_fitted_inputs_change(app_module, monkeypatch, imgui_frame, changed):
    from imgui_bundle import imgui

    pipeline = app_module["pipeline"]
    pipeline.model = ("Classification", OnlyPredictProba())
    app_module["training_inputs"]["fitted"] = ("Classification", ("RMS", "MAV"), 0)
    messages = []
    monkeypatch.setattr(imgui, "text_wrapped", messages.append)
    imgui_frame(app_module["model_ui"])
    warning = "Features changed — retrain to apply them."
    assert warning not in messages

    if changed == "mode":
        app_module["training_mode"]["index"] = 1
    elif changed == "features":
        app_module["features"].set_active("WL", True)
    else:
        app_module["notch"]["index"] = 1
    messages.clear()
    imgui_frame(app_module["model_ui"])
    assert warning in messages


def test_myocontrol_switches_session_selection_before_train(
    app_module, monkeypatch, implot_frame, tmp_path,
):
    from myogestic import TrainingData
    from myogestic.widgets.training import _session_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_session_state, "_states", {})
    ctx = app_module["app"].ctx
    ctx.participant = "P-014"
    app_module["steps"].active = 2
    state = _session_state.get_state(app_module["sessions"]._widget_id)
    state.participant = "P-013"
    state.sessions = [{"path": "sessions/P-013/old.session.zip", "selected": True}]
    app_module["pipeline"].training_data = TrainingData(paths=[state.sessions[0]["path"]])
    selections_at_train = []
    ui_globals = app_module["myocontrol_ui"].__globals__
    monkeypatch.setitem(
        ui_globals, "model_ui",
        lambda: selections_at_train.append(app_module["pipeline"].training_data.paths),
    )
    implot_frame(lambda: app_module["myocontrol_ui"](ctx))
    assert selections_at_train == [[]]
    assert not app_module["_step_done"](ctx)[1]


def test_nothing_attaches_itself(monkeypatch):
    """"Nothing attaches on its own" is the project's rule, and unlike force_ramps this
    app has no task target to except — so nothing may even *try* to connect.

    Asserted on the attempt, not on the outcome. ``DEFAULT_DEVICES[0]`` is a Muovi, real
    hardware that is not on this machine, so a module that did auto-connect would still
    leave every ``_connected`` False — the obvious version of this test passes whatever
    the module does, and its only symptom is a 30 s import while the socket times out.
    """
    called: list[str] = []
    monkeypatch.setattr(
        myogestic.stream.Stream, "reconnect", lambda self, *a, **k: called.append(self.name)
    )
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    monkeypatch.syspath_prepend(str(_APP.parent))
    runpy.run_path(str(_APP), run_name="__main__")

    assert called == [], f"connected without being asked: {called}"


def test_predict_uses_the_models_mode_not_the_switch(app_module):
    """The mode is bound into the model at Train, never read off the live switch.

    Reading it live means flipping the switch under a loaded classifier sends a class
    *index* down the regression branch — the hand snaps to full flexion and nothing
    raises. The stub has no `.predict`, so a live read fails here with AttributeError
    instead of shipping.
    """
    app_module["training_mode"]["index"] = app_module["MODES"].index("Regression")

    out = app_module["predict"](("Classification", OnlyPredictProba()), np.zeros(4))

    assert "class" in out, f"predict took the wrong branch: {out}"
    assert out["class"] == app_module["CLASSES"].index("Fist")


def test_predict_never_binds_the_bus(app_module, monkeypatch):
    """`ensure()` costs a blocking RPC and `predict` runs on a deadline.

    RuntimeError, not ValueError: the example catches ValueError around `ensure` in its
    UI handlers, so a ValueError would be swallowed by a `predict` that routed through
    one of those and this would pass while the RPC still blocked the thread.
    """

    def boom(self):
        raise RuntimeError("predict must read link.bus, never call link.ensure()")

    monkeypatch.setattr(ControlLink, "ensure", boom)

    out = app_module["predict"](("Classification", OnlyPredictProba()), np.zeros(4))

    assert "controls" not in out, "nothing is bound, so nothing can have been pushed"


def test_the_model_and_hand_tabs_draw(app_module, implot_frame):
    """A layout pass only ever draws a tab bar's *first* tab, so neither of these is
    reached by `test_example_draws_a_frame` — the drawing crashes live in there."""
    implot_frame(app_module["model_ui"])
    implot_frame(app_module["hand_ui"])


def test_the_map_declares_exactly_what_the_app_pushes(app_module):
    """Every alias in the map is driven, and every alias pushed is declared.

    An alias the app never sends is a row in the Hand panel that never moves — the
    operator sees a control and cannot tell whether it is broken or simply unused. The
    other direction is worse: `push` silently drops a key the `ControlSet` does not
    declare, so a typo'd alias is a hand that never moves and a log that says nothing.
    """
    import numpy as np

    pushed: list[dict] = []

    class Bus:
        def push(self, values):
            pushed.append(dict(values))
            return values

    class Clf:
        def predict_proba(self, x):
            return np.array([[0.1, 0.9]])

    app_module["link"]._bus = Bus()
    try:
        app_module["predict"](("Classification", Clf()), np.zeros(4))
    finally:
        app_module["link"]._bus = None

    declared = set(app_module["CONTROL_MAP"].bindings)
    assert pushed and set(pushed[0]) == declared, (
        f"pushed {set(pushed[0]) if pushed else set()} but the map declares {declared}"
    )
    # Both hands are commanded every frame. Omit either and `push` rests it — the
    # control hand would drop a frame after it was set, and the prediction hand would
    # twitch to rest on every button press.
    assert declared == {"prediction", "control"}
def test_launching_vhi_is_what_arms_the_binder(app_module, monkeypatch, implot_frame):
    """Pressing Launch is the operator's intent; a second Connect press is ceremony.

    "Nothing attaches on its own" survives — the binding follows an act they performed.
    What must not happen is binding with no act at all, so the connector is polled only
    while the panel reports the process it started is alive.
    """
    polled: list[bool] = []
    monkeypatch.setattr(
        type(app_module["binder"]), "poll", lambda self, force=False: polled.append(True)
    )
    launcher = app_module["processes"]

    monkeypatch.setattr(type(launcher), "running", lambda self, name: False)
    implot_frame(app_module["hand_ui"])
    assert polled == [], "bound without anyone launching or pressing anything"

    monkeypatch.setattr(type(launcher), "running", lambda self, name: True)
    implot_frame(app_module["hand_ui"])
    assert polled == [True], "launched the target and then did not bind to it"


def test_the_binder_never_blocks_a_frame(app_module):
    """`poll` is the whole reason the connector exists: `ControlLink.ensure` blocks on an
    RPC, and this runs inside `@app.ui`."""
    source = inspect.getsource(app_module["hand_ui"])
    assert "binder.poll()" in source
    assert "link.ensure()" not in source, "ensure() would stall the render thread"


# --- classification is regression that emits a constant -----------------------
def test_a_class_is_a_pose_and_goes_out_on_the_same_aliases(app_module):
    """The two modes differ in where the numbers come from, not in what is sent.

    A classifier picks a row of `POSES`; a regressor computes one. Both reach the bus as
    the same continuous aliases, in the same units — which is why one control map serves
    both and nothing downstream has to know which mode is running.
    """
    import numpy as np

    sent: list[dict] = []

    class Bus:
        def push(self, values):
            sent.append(dict(values))
            return values

    class Clf:
        def predict_proba(self, x):
            return np.array([[0.1, 0.9]])  # -> "Fist"

    class Reg:
        def predict(self, x):
            return [0.62]

    app_module["link"]._bus = Bus()
    try:
        app_module["predict"](("Classification", Clf()), np.zeros(4))
        app_module["predict"](("Regression", Reg()), np.zeros(4))
    finally:
        app_module["link"]._bus = None

    assert len(sent) == 2
    classified, regressed = sent
    assert set(classified) == set(regressed), "the modes push different aliases"
    assert classified["prediction"] == app_module["POSES"]["Fist"]
    assert regressed["prediction"] == pytest.approx(0.62)


def test_every_class_has_a_pose(app_module):
    """A class with no pose pushes an all-rest frame and reads as a model that never
    fires — a silence, not an error. The module asserts it at import; this pins that the
    assert exists rather than that it happens to pass today."""
    assert set(app_module["POSES"]) == set(app_module["CLASSES"])


def test_the_cue_survives_a_prediction_that_disagrees_with_it(app_module):
    """The two hands are allowed to disagree — that disagreement is the point.

    The operator selects Fist; the model, mid-training or simply wrong, says Rest. The
    prediction hand must open while the control hand stays closed. Leaving `control` out
    of the predict frame rests it instead, so it drops 31 ms after it is set and the
    button reads as doing nothing.
    """
    import numpy as np

    sent: list[dict] = []

    class Bus:
        def push(self, values):
            sent.append(dict(values))
            return values

    class SaysRest:
        def predict_proba(self, x):
            return np.array([[0.9, 0.1]])

    app_module["link"]._bus = Bus()
    try:
        app_module["_on_control"](app_module["CLASSES"].index("Fist"))
        app_module["predict"](("Classification", SaysRest()), np.zeros(4))
    finally:
        app_module["link"]._bus = None

    # One frame, from `predict`. The click only remembers: a push there would complete
    # the frame with `prediction` at rest and twitch the other hand on every press.
    (predicted,) = sent
    assert predicted["control"] == app_module["POSES"]["Fist"], "the predict frame rested it"
    assert predicted["prediction"] == app_module["POSES"]["Rest"]


def test_the_ui_streams_the_frame_while_the_predict_loop_is_not(app_module):
    """VHI drops a control pose whose streams go quiet, so a command has to be sustained.

    `ControlHandSkeleton._Process` follows the pose only while `ControlPoseLive` — five
    seconds since the last sample — and on the falling edge calls `StopToRest()`, giving
    the rig back to its own movement animation. Fire once and the hand closes, then opens
    again five seconds later. The predict loop is that producer while predicting; the
    class buttons are used while *recording*, when it is not running, so the UI has to be.

    Not the same question as whether the outlet repeats its last value — it does, forever.
    That keeps a value on the wire, while VHI's liveness test is on samples *arriving*.
    Conflating the two is what made this take so long to find.

    Asserted on the source: the push sits at the tail of `@app.ui`, and reaching it in a
    layout pass would mean standing up the whole grid.
    """
    source = inspect.getsource(app_module["myocontrol_ui"])

    assert "bus.push" in source, "nothing drives the hands while recording"
    assert 'ctx.state != "predicting"' in source, (
        "the UI would drive the same outlets as the predict loop, at a different rate"
    )


def test_train_refuses_a_take_conditioned_differently_from_the_switch(app_module, tmp_path):
    """Fitting on unfiltered signal and predicting through a notch is silent and fatal.

    The notch conditions acquisition, so a filtered session holds filtered samples and
    nothing in the arrays says so. Train on raw takes with SIGNAL set to 50 Hz and the
    model meets an input distribution it never saw, while every read-out stays healthy —
    the same shape of bug as concatenating %MVC targets with signed control units.
    """

    from myogestic import TrainingData
    from myogestic.session import Session
    from myogestic.stream import StreamInfo

    def _take(notch_hz: int | None) -> str:
        sess = Session(base_path=str(tmp_path))
        sess.init_stream("emg", StreamInfo(n_channels=2, fs=100.0, dtype=np.dtype("float32")))
        sess.append("emg", np.zeros((50, 2), dtype=np.float32), np.arange(50) / 100.0)
        sess.add_label(0.0, 0)
        if notch_hz is not None:
            sess.extras["conditioning"] = {"emg": {"notch_hz": notch_hz}}
        sess.save_meta("test", ["Rest", "Fist"])
        sess.close()
        return str(sess.path)

    raw, filtered = _take(None), _take(50)
    notch = app_module["notch"]
    train = app_module["train"]

    notch["index"] = app_module["NOTCH_HZ"].index(50)  # SIGNAL says 50 Hz
    with pytest.raises(ValueError, match="recorded with notch"):
        train(TrainingData(paths=[raw], classes=set()))

    notch["index"] = 0  # SIGNAL says off
    with pytest.raises(ValueError, match="recorded with notch"):
        train(TrainingData(paths=[filtered], classes=set()))

    # And a matched pair gets past the guard — it fails later, on having no windows,
    # which is a different error and proves the guard is not simply refusing everything.
    notch["index"] = app_module["NOTCH_HZ"].index(50)
    with pytest.raises(ValueError) as excinfo:
        train(TrainingData(paths=[filtered], classes=set()))
    assert "recorded with notch" not in str(excinfo.value), str(excinfo.value)


def test_hand_connect_checks_before_launch_and_stop_cancels(app_module, monkeypatch, imgui_frame):
    from types import SimpleNamespace

    from imgui_bundle import imgui

    state = SimpleNamespace(busy=False, finished=False, last_error=None, status="", polls=0, stops=0)

    def poll(*, force=False):
        state.polls += 1
        state.busy = True
        state.finished = False
        return True

    def stop(*, timeout_s):
        assert timeout_s == 0.0
        state.stops += 1

    state.poll, state.stop = poll, stop
    globals_ = app_module["hand_ui"].__globals__
    monkeypatch.setitem(globals_, "binder", state)
    monkeypatch.setitem(globals_, "hand_processes", [("hand", ["hand"])])
    running = {"value": False}
    launched, stopped = [], []

    def launch(name):
        launched.append(name)
        running["value"] = True

    monkeypatch.setattr(app_module["processes"], "launch", launch)
    monkeypatch.setattr(app_module["processes"], "stop", stopped.append)
    monkeypatch.setattr(app_module["processes"], "running", lambda name: running["value"])
    click = {"label": None}
    button = imgui.small_button

    def pressed(label, *args):
        button(label, *args)
        return label == click["label"]

    monkeypatch.setattr(imgui, "small_button", pressed)
    render = app_module["hand_ui"]
    imgui_frame(render)
    assert state.polls == 0 and launched == []
    click["label"] = "Connect"
    imgui_frame(render)
    assert state.polls == 1 and launched == []
    click["label"] = None
    imgui_frame(render)
    assert state.polls == 1 and launched == []
    state.busy, state.finished = False, True
    imgui_frame(render)
    assert launched == [app_module["vhi"].name]
    assert state.polls == 2
    click["label"] = "Stop"
    imgui_frame(render)
    assert stopped == [app_module["vhi"].name] and state.stops == 1
    click["label"] = None
    imgui_frame(render)
    assert state.polls == 2 and len(launched) == 1


@pytest.mark.parametrize("result", ["external", "external_without_install", "missing", "incompatible"])
def test_hand_bind_outcome_never_launches_a_second_target(app_module, monkeypatch, imgui_frame, result):
    from types import SimpleNamespace

    from imgui_bundle import imgui

    state = SimpleNamespace(busy=False, finished=True, last_error=None, status="")
    state.poll = lambda **kwargs: True
    globals_ = app_module["hand_ui"].__globals__
    monkeypatch.setitem(globals_, "binder", state)
    missing_install = result in ("missing", "external_without_install")
    monkeypatch.setitem(globals_, "hand_processes", [] if missing_install else [("hand", ["hand"])])
    monkeypatch.setattr(app_module["processes"], "running", lambda name: False)
    monkeypatch.setattr(app_module["processes"], "launch", lambda name: pytest.fail("duplicate launch"))
    button = imgui.small_button
    click = {"label": "Connect"}
    actions = []

    def pressed(label, *args):
        actions.append(label)
        button(label, *args)
        return label == click["label"]

    monkeypatch.setattr(imgui, "small_button", pressed)
    imgui_frame(app_module["hand_ui"])
    click["label"] = None
    actions.clear()
    external = result.startswith("external")
    if external:
        app_module["link"]._bus = object()
    elif result == "incompatible":
        state.last_error = ValueError("wrong map")
        state.status = "control connection failed: wrong map"
    try:
        imgui_frame(app_module["hand_ui"])
        assert actions == ([] if external else ["Retry"])
    finally:
        app_module["link"]._bus = None


def test_hand_missing_install_explains_idle_and_failed_connect(app_module, monkeypatch, imgui_frame):
    from types import SimpleNamespace

    from imgui_bundle import imgui

    state = SimpleNamespace(busy=False, finished=False, last_error=None, status="", polls=0)

    def poll(*, force=False):
        assert force
        state.polls += 1
        state.busy = True
        return True

    state.poll = poll
    render = app_module["hand_ui"]
    globals_ = render.__globals__
    monkeypatch.setitem(globals_, "binder", state)
    monkeypatch.setitem(globals_, "hand_processes", [])
    monkeypatch.setattr(app_module["processes"], "running", lambda name: False)
    monkeypatch.setattr(app_module["processes"], "launch", lambda name: pytest.fail("nothing installed to launch"))
    details, tones, tooltips = [], [], []
    ellipsize, text_colored = globals_["_ellipsize"], imgui.text_colored

    def detail(text, width):
        details.append(text)
        return ellipsize(text, width)

    def colored(tone, text):
        if text == globals_["fa"].ICON_FA_CIRCLE:
            tones.append(tone)
        text_colored(tone, text)

    monkeypatch.setitem(globals_, "_ellipsize", detail)
    monkeypatch.setattr(imgui, "text_colored", colored)
    monkeypatch.setattr(imgui, "set_item_tooltip", tooltips.append)
    button = imgui.small_button
    click = {"label": None}

    def pressed(label, *args):
        button(label, *args)
        return label == click["label"]

    monkeypatch.setattr(imgui, "small_button", pressed)
    hint = app_module["vhi"].install_hint.strip()

    def assert_status(expected, tone):
        assert details[-1] == expected
        assert tones[-1] == tone
        assert tooltips[-1].startswith(f"{expected}\n\n{hint}\n\n")
        assert "prediction →" in tooltips[-1] and "control →" in tooltips[-1]

    imgui_frame(render)
    assert_status("not installed here", globals_["IDLE"])
    assert state.polls == 0
    click["label"] = "Connect"
    imgui_frame(render)
    assert state.polls == 1, "Connect must still look for a hand started elsewhere"
    click["label"] = None
    state.busy, state.finished = False, True
    imgui_frame(render)
    assert_status("no Virtual Hand answered · not installed here", globals_["DANGER"])


def test_hand_rechecks_bus_after_observing_attempt_completion(app_module, monkeypatch, imgui_frame):
    """The worker can bind between the initial bus read and its completion read."""
    class JustFinished:
        busy = False
        last_error = None
        status = "controls connected"

        @property
        def finished(self):
            app_module["link"]._bus = object()
            return True

    globals_ = app_module["hand_ui"].__globals__
    monkeypatch.setitem(globals_, "binder", JustFinished())
    monkeypatch.setitem(globals_, "hand_processes", [("hand", ["hand"])])
    app_module["hand_attempt"]["phase"] = "checking"
    monkeypatch.setattr(app_module["processes"], "running", lambda name: False)
    monkeypatch.setattr(app_module["processes"], "launch", lambda name: pytest.fail("launched beside the bound hand"))
    try:
        imgui_frame(app_module["hand_ui"])
    finally:
        app_module["link"]._bus = None


@pytest.mark.parametrize("scale,size", [(1.0, (1280, 828)), (1.0, (900, 1100)), (2.0, (2560, 1656))])
def test_connect_card_fits_real_step_layout(app_module, monkeypatch, implot_frame, scale, size):
    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    imgui.get_io().display_size = imgui.ImVec2(*size)
    render = app_module["connect_ui"]
    measurements = []

    def tracked(ctx):
        render(ctx)
        cursor = imgui.get_cursor_pos_y()
        height = imgui.get_window_size().y
        measurements.append((cursor, height, imgui.get_scroll_max_y()))

    monkeypatch.setitem(app_module["myocontrol_ui"].__globals__, "connect_ui", tracked)

    def draw():
        imgui.set_next_window_size(imgui.ImVec2(*size))
        imgui.begin("connect-workflow")
        app_module["myocontrol_ui"](app_module["app"].ctx)
        imgui.end()

    implot_frame(draw)
    implot_frame(draw)
    assert all(cursor <= height and scroll == 0 for cursor, height, scroll in measurements), measurements


def test_train_card_uses_selection_and_names_missing_gesture(app_module, imgui_frame, monkeypatch):
    from types import SimpleNamespace

    from myogestic import TrainingData

    render = app_module["model_ui"]
    globals_ = render.__globals__
    summary = SimpleNamespace(n_selected=2, n_total=3, class_seconds={"Rest": 18.})
    monkeypatch.setattr(app_module["sessions"], "selection", lambda: summary, raising=False)
    app_module["pipeline"].training_data = TrainingData(paths=["one", "two"], classes={0})
    reasons, actions, text = [], [], []
    monkeypatch.setitem(globals_, "_disabled_reason", reasons.append)
    real_mono = globals_["mono_text"]

    def mono(value, color=None):
        text.append(value)
        real_mono(value, color)

    monkeypatch.setitem(globals_, "mono_text", mono)
    monkeypatch.setitem(globals_, "primary_button", lambda label, size=(0, 0): actions.append((label, size)) or True)
    monkeypatch.setattr(app_module["pipeline"], "start_training", lambda: pytest.fail("missing Fist must disable training"))
    imgui_frame(render)
    assert any("Fist" in reason for reason in reasons)
    assert actions[-1][0] == "Train classifier" and actions[-1][1][0] < 0
    assert "0:18" in text


def test_train_card_starts_fit_and_shows_saved_model(app_module, imgui_frame, monkeypatch):
    from types import SimpleNamespace

    from imgui_bundle import imgui

    from myogestic import TrainingData

    render = app_module["model_ui"]
    globals_ = render.__globals__
    summary = SimpleNamespace(n_selected=2, n_total=2, class_seconds={"Rest": 18., "Fist": 22.})
    monkeypatch.setattr(app_module["sessions"], "selection", lambda: summary, raising=False)
    pipeline = app_module["pipeline"]
    pipeline.training_data = TrainingData(paths=["one", "two"], classes={0, 1})
    pipeline.model = object()
    pipeline.last_saved_model = "/sessions/P-014/classifier.pkl"
    app_module["training_inputs"]["fitted"] = app_module["_input_fingerprint"]()
    starts, labels = [], []
    monkeypatch.setattr(pipeline, "start_training", lambda: starts.append(True))
    monkeypatch.setitem(globals_, "primary_button", lambda *args, **kwargs: True)
    real_text = imgui.text_unformatted

    def text(value, *args):
        labels.append(value)
        real_text(value, *args)

    monkeypatch.setattr(imgui, "text_unformatted", text)
    imgui_frame(render)
    assert starts == [True]
    assert app_module["training_inputs"]["requested"] == app_module["_input_fingerprint"]()
    assert any("classifier.pkl" in label for label in labels)


@pytest.mark.parametrize("scale", [1., 2.])
@pytest.mark.parametrize("fitted", [False, True])
def test_train_card_fits_step_cell(app_module, implot_frame, monkeypatch, scale, fitted):
    from types import SimpleNamespace

    from imgui_bundle import imgui

    from myogestic import TrainingData, _scale, _theme

    if fitted:
        summary = SimpleNamespace(n_selected=12, n_total=38, class_seconds={"Rest": 180., "Fist": 220.})
        monkeypatch.setattr(app_module["sessions"], "selection", lambda: summary)
        monkeypatch.setattr(app_module["sessions"], "ui", lambda **kwargs: TrainingData(paths=["take"], classes={0, 1}))
        app_module["pipeline"].model = object()
        app_module["pipeline"].last_saved_model = "/sessions/P-014/classifier.pkl"
        # A fitted model plus changed features keeps the warning and saved row visible.
    font_path = Path(myogestic.core.__file__).parent / "assets/fonts/IBMPlexMono-Regular.ttf"
    font = imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 13.)
    monkeypatch.setattr(_theme, "_MONO_FONT", font)
    mono_bounds = []
    mono = app_module["model_ui"].__globals__["mono_text"]

    def measured_mono(text, color=None):
        mono(text, color)
        mono_bounds.append((text, imgui.get_item_rect_max().x,
                            imgui.get_window_pos().x + imgui.get_window_size().x - imgui.get_style().window_padding.x))

    monkeypatch.setitem(app_module["model_ui"].__globals__, "mono_text", measured_mono)
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    size = (1280 * scale, 828 * scale)
    imgui.get_io().display_size = imgui.ImVec2(*size)
    monkeypatch.setattr(app_module["header"], "ui", lambda ctx, done: 2)
    render = app_module["model_ui"]
    measurements = []

    def tracked():
        render()
        measurements.append((imgui.get_cursor_pos_y(), imgui.get_window_size().y, imgui.get_scroll_max_y()))

    monkeypatch.setitem(app_module["myocontrol_ui"].__globals__, "model_ui", tracked)

    def draw():
        imgui.set_next_window_size(imgui.ImVec2(*size))
        imgui.begin("train-workflow")
        app_module["myocontrol_ui"](app_module["app"].ctx)
        imgui.end()

    implot_frame(draw)
    implot_frame(draw)
    assert all(cursor <= height and scroll == 0 for cursor, height, scroll in measurements), measurements
    assert all(right <= edge + 1 for _, right, edge in mono_bounds), mono_bounds
