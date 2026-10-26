"""The RaulNet workflow keeps capture, training progress and output visible."""

from __future__ import annotations

import platform
import runpy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example(monkeypatch, tmp_path):
    """Wire the real example without starting a runner or external processes."""
    pytest.importorskip("lightning")
    pytest.importorskip("myoverse.models.raul_net.v17")
    from myogestic.remote import InterfaceSpec
    from myogestic.tools import emg_generator

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(InterfaceSpec, "launchable", lambda self: [(self.name, ["vhi"])])
    monkeypatch.setattr(emg_generator, "control_outlet", lambda: SimpleNamespace(push_sample=lambda x: None))
    ns = runpy.run_path(str(ROOT / "examples/synthetic/emg_regression_raulnet.py"))
    streams = tuple(ns["app"].ctx.streams.values())
    try:
        yield ns
    finally:
        ns["link"].stop()
        ns["recording_aid"].stop()
        ns["vhi_control"].stop()
        for stream in streams:
            stream.stop()


def test_session_shell_and_model_wiring(example):
    """The session shell retains the model callbacks and both recorded streams."""
    from myogestic import Px
    from myogestic.widgets import AppHeader, SimulatorControls, StatusBar

    ns = example
    assert isinstance(ns["header"], AppHeader)
    assert ns["header"].title == "EMG regression · RaulNet"
    assert ns["header"].steps is ns["steps"]
    assert ns["header"].participant is ns["participant"]
    assert ns["steps"].steps == ["Connect", "Record", "Train", "Predict"]
    assert ns["steps"]._widget_id == "emg_regression_raulnet_steps"
    assert isinstance(ns["status"], StatusBar)
    assert ns["status"].pipeline is ns["pipeline"]
    assert isinstance(ns["simulator"], SimulatorControls)
    assert "ctrl_outlet" not in ns and "logo" not in ns
    assert not ns["recording"]._show_header
    assert ns["layout"].panel_names == {
        "header", "signal", "simulator", "step", "sessions", "log", "status",
    }
    for grid in (ns["layout"]._wide, ns["layout"]._narrow):
        assert grid._bare == {"header", "status"}
        assert grid._row_tracks[0] == Px(52) and grid._row_tracks[-1] == Px(26)
        signal, simulator = grid._areas["signal"], grid._areas["simulator"]
        assert simulator[0] == signal[1] and simulator[2:] == signal[2:]
    assert set(ns["app"].ctx.streams) == {"emg", "vhi_control"}
    assert ns["pipeline"].save_model is ns["save_raulnet"]
    assert ns["pipeline"].load_model is ns["load_raulnet"]
    assert ns["pipeline"].predict_hz == 20


def test_completion_follows_participant_takes(example, monkeypatch, tmp_path):
    ns = example
    ctx, done = ns["app"].ctx, ns["_step_done"]
    assert done(ctx) == [False] * 4
    ctx.participant = "P-014"
    monkeypatch.setitem(ctx.streams, "emg", SimpleNamespace(status="connected", info=object()))
    folder = tmp_path / "sessions" / ctx.participant
    folder.mkdir(parents=True)
    (folder / "someone-else_take.session.zip").touch()
    assert done(ctx) == [True, False, False, False]
    (folder / "P-014_take.session.zip").touch()
    ns["pipeline"].model = object()
    ctx.state = "predicting"
    assert done(ctx) == [True] * 4
    ctx.participant = "P-015"
    ctx.streams["emg"].info = None
    assert done(ctx) == [False, False, True, True]


def test_recording_resyncs_simulator_and_preserves_hand_gate(example, monkeypatch):
    """A preview cannot silently change the EMG recorded for the selected gesture."""
    ns = example
    calls = []
    bus = SimpleNamespace(select=lambda *args: calls.append(("select", *args)))
    monkeypatch.setattr(type(ns["link"]), "ensure", lambda self: (calls.append("bind"), bus)[1])
    monkeypatch.setattr(ns["simulator"], "set", lambda value: calls.append(("signal", value)))
    monkeypatch.setattr(ns["app"], "start_recording", lambda: calls.append("record"))
    monkeypatch.setattr(ns["app"], "stop_recording", lambda: calls.append("stop"))
    monkeypatch.setattr(type(ns["recording_aid"]), "set_recording_session",
                        lambda self, active: (calls.append(("gate", active)), True)[1])
    ns["_on_gesture"](1)
    assert calls == ["bind", ("signal", 1.0), ("select", "gesture", "Fist")]
    calls.clear()
    ns["app"].ctx.current_label = 0
    ns["_on_record"]()
    assert calls == ["bind", ("signal", 0.0), "record", ("gate", True)]
    calls.clear()
    ns["_on_stop"]()
    assert calls == ["stop", ("gate", False)]


@pytest.mark.parametrize("step", range(4))
@pytest.mark.parametrize("width", [2560, 1800])
@pytest.mark.parametrize("state", ["idle", "recording", "training", "predicting", "failed"])
def test_shell_fits_and_keeps_each_steps_controls_visible(
    example, monkeypatch, implot_frame, step, width, state,
):
    """Measure real cards at scale two in light theme, including a long-running fit."""
    from imgui_bundle import hello_imgui, imgui

    from myogestic import _scale, _theme
    from myogestic.ml import widgets as ml_widgets
    from myogestic.widgets.panels import recording
    from myogestic.widgets.signals import simulator_controls

    ns, cells, buttons, views, headers, words, logs = example, [], [], [], [], [], []
    text_extents = []
    app, pipeline = ns["app"], ns["pipeline"]
    ns["steps"].active = step
    app.ctx.state = "idle" if state == "failed" else state
    if state != "idle":
        app.ctx.participant = "P-014"
    if state in {"training", "predicting", "failed"}:
        pipeline.train_log.extend(["Training from 2 sessions...", "  epoch 12/300  loss=0.0412"])
    if state == "predicting":
        pipeline.model = object()
        pipeline.predictions["dof"] = dict.fromkeys(ns["DOF_NAMES"], -0.25)
    if state == "failed":
        app.ctx.status_message = "Training failed: Only 8 windows — record more data."
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    font_path = Path(_theme._SYS_FONTS.get(platform.system(), ""))
    if not font_path.is_file():
        font_path = Path(hello_imgui.asset_file_full_path("fonts/Roboto/Roboto-Regular.ttf"))
    imgui.get_io().font_default = imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 14)
    for attr, filename, size in (("_MONO_FONT", "IBMPlexMono-Regular.ttf", 13),
                                 ("_DISPLAY_FONT", "InstrumentSerif-Regular.ttf", 28)):
        font = imgui.get_io().fonts.add_font_from_file_ttf(str(ROOT / "myogestic/assets/fonts" / filename), size)
        monkeypatch.setattr(_theme, attr, font)
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width, 1656)
    original_header = ns["panel_header"]

    def header(title, *args, **kwargs):
        headers.append(title)
        return original_header(title, *args, **kwargs)

    monkeypatch.setitem(app._ui_fn.__globals__, "panel_header", header)
    for module in (ml_widgets, recording, simulator_controls):
        monkeypatch.setattr(module, "panel_header", header)
    monkeypatch.setattr(imgui, "begin_tab_bar", lambda *a: pytest.fail("the shell has no tabs"))
    for method in ("button", "small_button", "text_unformatted", "text_wrapped", "text_colored"):
        original = getattr(imgui, method)

        def item(*args, method=method, original=original, **kwargs):
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            result = original(*args, **kwargs)
            if "button" in method:
                buttons.append((args[0], imgui.get_item_rect_max().x - right))
            else:
                text = args[1] if method == "text_colored" else args[0]
                words.append(text)
                text_extents.append((text, imgui.get_item_rect_max().x - right))
            return result

        monkeypatch.setattr(imgui, method, item)
    original_log = imgui.input_text_multiline

    def log(label, text, size, **kwargs):
        result = original_log(label, text, size, **kwargs)
        logs.append((label, text, imgui.get_item_rect_size().y))
        return result

    monkeypatch.setattr(imgui, "input_text_multiline", log)
    for name in ("viewer", "simulator", "recording", "train_button", "training_log",
                 "predict_button", "output_filter", "sessions", "log", "status"):
        widget = ns[name]
        render = type(widget).ui

        def view(self, *args, name=name, render=render, **kwargs):
            views.append((name, kwargs))
            result = render(self, *args, **kwargs)
            if kwargs.get("visible", True) and name != "status":
                cells.append((imgui.get_cursor_pos_y(), imgui.get_window_size().y,
                              imgui.get_scroll_max_x(), imgui.get_scroll_max_y()))
            return result

        monkeypatch.setattr(type(widget), "ui", view)
    for name in ("connect_ui", "model_ui", "predict_ui"):
        render = ns[name]

        def card(*args, render=render):
            render(*args)
            cells.append((imgui.get_cursor_pos_y(), imgui.get_window_size().y,
                          imgui.get_scroll_max_x(), imgui.get_scroll_max_y()))

        monkeypatch.setitem(app._ui_fn.__globals__, name, card)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1656))
        imgui.begin("raulnet-shell", flags=imgui.WindowFlags_.no_title_bar)
        app._ui_fn(app.ctx)
        assert imgui.get_scroll_max_x() == imgui.get_scroll_max_y() == 0
        imgui.end()

    for _ in range(4):
        for collection in (cells, buttons, views, headers, words, logs, text_extents):
            collection.clear()
        implot_frame(draw)
    assert headers == [ns["steps"].steps[step], "Simulated EMG"]
    expected = {"viewer", "simulator", "recording", "sessions", "log", "status"}
    expected |= {2: {"train_button", "training_log"}, 3: {"predict_button", "output_filter"}}.get(step, set())
    assert {name for name, _ in views} == expected
    assert [kw.get("visible", True) for name, kw in views if name == "recording"] == [step == 1]
    assert next(kw for name, kw in views if name == "sessions") == {"participant": app.ctx.participant}
    assert all(overhang <= 1 for _, overhang in buttons), buttons
    assert all(horizontal == 0 for _, _, horizontal, _ in cells), cells
    if width == 2560:
        assert all(cursor - imgui.get_style().item_spacing.y <= height and vertical == 0
                   for cursor, height, _, vertical in cells), cells
        assert all(overhang <= 1 for _, overhang in text_extents), text_extents
    if step == 2 and state == "training":
        assert "Training…" in words
        assert any("epoch 12/300" in text and height >= 100 for _, text, height in logs), logs
    if step == 2 and state == "failed":
        assert "Training failed" in words
    if step == 3 and state == "predicting":
        assert all(name in words for name in ns["DOF_NAMES"])
        assert any("-0.25" in word for word in words)


@pytest.mark.parametrize("step", range(4))
@pytest.mark.parametrize("state", ["idle", "recording", "predicting"])
def test_simulator_is_available_on_each_step_except_during_capture(
    example, monkeypatch, implot_frame, step, state,
):
    from imgui_bundle import imgui

    ns = example
    ns["steps"].active = step
    ns["app"].ctx.state = state
    ns["simulator"].set(0.0)
    samples, chips = [], []
    monkeypatch.setattr(ns["simulator"]._outlet, "push_sample", lambda value: samples.append(value))
    original = imgui.small_button

    def click(label):
        result = original(label)
        if "##preset_" in label:
            disabled = bool(imgui.get_item_flags() & imgui.ItemFlags_.disabled)
            chips.append((label.split("##")[0], disabled))
            return label.startswith("Fist##") and not disabled
        return result

    monkeypatch.setattr(imgui, "small_button", click)
    implot_frame(lambda: ns["app"]._ui_fn(ns["app"].ctx))
    assert chips == [("Rest", state == "recording"), ("Fist", state == "recording")]
    assert ns["app"].ctx.current_label == -1
    assert len(samples) == (0 if state == "recording" else 1)
    if samples:
        np.testing.assert_array_equal(samples[0], np.array([1.0], dtype=np.float32))


@pytest.mark.parametrize("card", ["connect_ui", "model_ui", "predict_ui"])
def test_step_content_fits_a_320_pixel_card(example, monkeypatch, implot_frame, card):
    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    ns, extents = example, []
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(400, 1400)
    ns["app"].ctx.state = "training" if card == "model_ui" else "predicting"
    ns["pipeline"].train_log.append("epoch 12/300  loss=0.0412")
    ns["pipeline"].predictions["dof"] = dict.fromkeys(ns["DOF_NAMES"], -0.25)
    for method in ("button", "small_button", "text_unformatted", "text_wrapped", "text_colored"):
        original = getattr(imgui, method)

        def item(*args, method=method, original=original, **kwargs):
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            result = original(*args, **kwargs)
            text = args[1] if method == "text_colored" else args[0]
            extents.append((text, imgui.get_item_rect_max().x - right))
            return result

        monkeypatch.setattr(imgui, method, item)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(320, 1300))
        imgui.begin("narrow-step", flags=imgui.WindowFlags_.horizontal_scrollbar)
        ns[card](ns["app"].ctx) if card == "connect_ui" else ns[card]()
        assert imgui.get_scroll_max_x() == 0
        imgui.end()

    for _ in range(4):
        extents.clear()
        implot_frame(draw)
    assert all(overhang <= 1 for _, overhang in extents), extents
