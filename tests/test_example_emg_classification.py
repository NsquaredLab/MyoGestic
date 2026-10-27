"""EMG classification runs alone and optionally drives both Virtual Hand outputs."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

import myogestic.remote

_EXAMPLES_ROOT = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def classification_app(monkeypatch, tmp_path):
    """Wire the classification workflow without launching its external targets."""
    from types import SimpleNamespace

    from myogestic.tools import emg_generator

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        emg_generator, "control_outlet", lambda: SimpleNamespace(push_sample=lambda x: None)
    )
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    namespace = runpy.run_path(str(_EXAMPLES_ROOT / "synthetic" / "emg_classification.py"))
    namespace = namespace["demo_ui"].__globals__
    assert namespace["_init_hand"]()
    binder = namespace["binder"]
    streams = tuple(namespace["app"].ctx.streams.values())
    try:
        yield namespace
    finally:
        binder.stop()
        namespace["vhi_control"].stop()
        namespace["recording_aid"].stop()
        for stream in streams:
            stream.stop()


def test_classification_uses_the_session_shell(classification_app):
    """One header and active step surround a persistent signal and sessions."""
    from myogestic import Fr, Px
    from myogestic.widgets import AppHeader, SimulatorControls, StatusBar

    ns = classification_app
    layout, header, steps = (ns[name] for name in ("layout", "header", "steps"))
    assert isinstance(header, AppHeader) and header.title == "EMG classification"
    assert header.steps is steps and header.participant is ns["participant"]
    assert steps.steps == ["Connect", "Record", "Train", "Predict"]
    assert steps._widget_id == "emg_classification_steps"
    assert isinstance(ns["status"], StatusBar) and ns["status"].pipeline is ns["pipeline"]
    assert isinstance(ns["simulator"], SimulatorControls)
    assert "ctrl_outlet" not in ns
    assert ns["app"].ctx.require_participant
    assert not ns["recording"]._show_header and not ns["features"]._show_header
    assert layout.panel_names == {
        "header",
        "signal",
        "simulator",
        "step",
        "sessions",
        "log",
        "status",
    }
    assert layout._breakpoint == Px(1100)
    assert layout._wide._col_tracks == [Fr(1), Px(400)]
    assert layout._wide._areas == {
        "header": (0, 1, 0, 2),
        "signal": (1, 3, 0, 1),
        "step": (1, 2, 1, 2),
        "sessions": (2, 5, 1, 2),
        "simulator": (3, 4, 0, 1),
        "log": (4, 5, 0, 1),
        "status": (5, 6, 0, 2),
    }
    for grid in (layout._wide, layout._narrow):
        assert grid._bare == {"header", "status"}
        assert grid._row_tracks[0] == Px(52) and grid._row_tracks[-1] == Px(26)
        signal, simulator = grid._areas["signal"], grid._areas["simulator"]
        assert simulator[0] == signal[1] and simulator[2:] == signal[2:]
        assert grid._row_tracks[simulator[0]] == Px(76)


def test_classification_completion_tracks_the_participants_takes(
    classification_app, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    ns = classification_app
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
    ctx.streams["emg"].info = None
    ctx.participant = "P-015"
    assert done(ctx) == [False, False, True, True]


@pytest.mark.parametrize("step", range(4))
@pytest.mark.parametrize("width", [2560, 1800])
@pytest.mark.parametrize("participant", ["", "P-014"])
@pytest.mark.parametrize("trained", [False, True])
@pytest.mark.parametrize("recording_active", [False, True])
def test_classification_shell_fits_light_theme(
    classification_app,
    monkeypatch,
    implot_frame,
    step,
    width,
    participant,
    trained,
    recording_active,
):
    """Every active card fits the default window; narrow cards remain reachable."""
    import platform

    from imgui_bundle import hello_imgui, imgui

    from myogestic import _scale, _theme
    from myogestic.ml import widgets as ml_widgets
    from myogestic.widgets.panels import process_launcher, recording
    from myogestic.widgets.signals import simulator_controls
    from myogestic.widgets.training import feature_selector

    ns = classification_app
    app = ns["app"]
    app.ctx.participant = participant
    ns["steps"].active = step
    if trained:
        ns["pipeline"].model = object()
        ns["pipeline"].train_log.append("Trained on 100 windows from 2 sessions.")
        ns["pipeline"].predictions.update(
            {"class": 1, "proba": [0.1, 0.9], "hand": {"fist": 1.0, "gesture": "Fist"}}
        )
        app.ctx.state = "predicting" if step == 3 else "idle"
    if recording_active:
        app.ctx.state = "recording"
        app.ctx.recording = True
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    # The app uses a proportional body face. The fixture's monospace default
    # makes ordinary session guidance 45% wider than the real control surface.
    font_path = Path(_theme._SYS_FONTS.get(platform.system(), ""))
    if not font_path.is_file():
        font_path = Path(hello_imgui.asset_file_full_path("fonts/Roboto/Roboto-Regular.ttf"))
    imgui.get_io().font_default = imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 14)
    font_dir = _EXAMPLES_ROOT.parent / "myogestic" / "assets" / "fonts"
    for attr, filename, size in (
        ("_MONO_FONT", "IBMPlexMono-Regular.ttf", 13),
        ("_DISPLAY_FONT", "InstrumentSerif-Regular.ttf", 28),
    ):
        font = imgui.get_io().fonts.add_font_from_file_ttf(str(font_dir / filename), size)
        monkeypatch.setattr(_theme, attr, font)
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width, 1656)
    headers, views, cells, buttons, heights = [], [], [], [], {}
    texts = []
    original_header = ns["panel_header"]

    def header(title, *args, **kwargs):
        headers.append(title)
        return original_header(title, *args, **kwargs)

    monkeypatch.setitem(app._ui_fn.__globals__, "panel_header", header)
    for module in (ml_widgets, process_launcher, recording, feature_selector, simulator_controls):
        monkeypatch.setattr(module, "panel_header", header)
    monkeypatch.setattr(imgui, "begin_tab_bar", lambda *a: pytest.fail("the shell has no tabs"))
    original_button = imgui.button

    def button(label, *args, **kwargs):
        right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        result = original_button(label, *args, **kwargs)
        buttons.append((label, imgui.get_item_rect_max().x - right))
        return result

    monkeypatch.setattr(imgui, "button", button)
    original_chip = imgui.small_button

    def chip(label):
        right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        result = original_chip(label)
        buttons.append((label, imgui.get_item_rect_max().x - right))
        return result

    monkeypatch.setattr(imgui, "small_button", chip)
    for name in ("text", "text_colored", "text_unformatted", "text_wrapped"):
        original_text = getattr(imgui, name)

        def text(*args, render=original_text, **kwargs):
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            result = render(*args, **kwargs)
            texts.append((str(args[-1]), imgui.get_item_rect_max().x - right))
            return result

        monkeypatch.setattr(imgui, name, text)
    for name in ("connect_ui", "model_ui", "predict_ui"):
        render_step = ns[name]

        def draw_step(*args, render=render_step, name=name):
            render(*args)
            cells.append(
                (
                    name,
                    imgui.get_cursor_pos_y(),
                    imgui.get_window_size().y,
                    imgui.get_scroll_max_x(),
                    imgui.get_scroll_max_y(),
                )
            )

        monkeypatch.setitem(app._ui_fn.__globals__, name, draw_step)
    for name in (
        "viewer",
        "simulator",
        "recording",
        "features",
        "train_button",
        "training_log",
        "prediction",
        "predict_button",
        "output_filter",
        "sessions",
        "log",
        "status",
    ):
        widget = ns[name]
        render = type(widget).ui

        def view(self, *args, name=name, render=render, **kwargs):
            views.append((name, kwargs))
            result = render(self, *args, **kwargs)
            if kwargs.get("visible", True) and name != "status":
                heights[name] = imgui.get_window_size().y
                cells.append(
                    (
                        name,
                        imgui.get_cursor_pos_y(),
                        imgui.get_window_size().y,
                        imgui.get_scroll_max_x(),
                        imgui.get_scroll_max_y(),
                    )
                )
            return result

        monkeypatch.setattr(type(widget), "ui", view)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1656))
        imgui.begin("classification-shell", flags=imgui.WindowFlags_.no_title_bar)
        app._ui_fn(app.ctx)
        assert imgui.get_scroll_max_x() == imgui.get_scroll_max_y() == 0
        imgui.end()

    for _ in range(4):
        headers.clear()
        views.clear()
        cells.clear()
        buttons.clear()
        texts.clear()
        implot_frame(draw)
    assert headers == [ns["steps"].steps[step], "Simulated EMG"]
    expected = {"viewer", "simulator", "recording", "sessions", "log", "status"}
    expected |= {
        2: {"features", "train_button", "training_log"},
        3: {"prediction", "predict_button", "output_filter"},
    }.get(step, set())
    assert {name for name, _ in views} == expected
    record_calls = [kwargs for name, kwargs in views if name == "recording"]
    assert len(record_calls) == 1
    assert record_calls[0].get("visible", True) == (step == 1)
    assert next(kwargs for name, kwargs in views if name == "sessions") == {
        "participant": participant
    }
    assert all(overhang <= 1 for _, overhang in buttons), buttons
    assert all(overhang <= 1 for _, overhang in texts), texts
    assert all(horizontal == 0 for _, _, _, horizontal, _ in cells), cells
    assert heights["viewer"] > heights["simulator"]
    assert all(
        cursor - imgui.get_style().item_spacing.y <= height and vertical == 0
        for name, cursor, height, _, vertical in cells
        if name == "simulator"
    ), cells
    if width == 2560:
        assert all(
            cursor - imgui.get_style().item_spacing.y <= height and vertical == 0
            for _, cursor, height, _, vertical in cells
        ), cells
    assert ns["layout"]._active is (ns["layout"]._wide if width == 2560 else ns["layout"]._narrow)


def test_gesture_and_take_keep_the_generator_hand_and_recording_gate(
    classification_app, monkeypatch
):
    """Preview can change the signal; recording restores its selected label first."""
    from types import SimpleNamespace

    ns = classification_app
    calls = []
    bus = SimpleNamespace(select=lambda alias, state: calls.append((alias, state)))
    monkeypatch.setattr(
        type(ns["link"]), "ensure", lambda self: pytest.fail("callbacks must not probe the hand")
    )
    ns["link"]._bus = bus
    bus.stop = lambda: None
    ns["recording_aid"].available = True
    monkeypatch.setattr(
        type(ns["simulator"]), "set", lambda self, value: calls.append(("signal", value))
    )
    monkeypatch.setattr(ns["app"], "start_recording", lambda: calls.append("record"))
    monkeypatch.setattr(ns["app"], "stop_recording", lambda: calls.append("stop"))
    monkeypatch.setattr(
        type(ns["recording_aid"]),
        "set_recording_session",
        lambda self, active: calls.append(("gate", active)) or True,
    )
    ns["_on_gesture"](1)
    assert calls == [("signal", 1.0), ("gesture", "Fist")]
    calls.clear()
    ns["app"].ctx.current_label = 0
    ns["_on_record"]()
    assert calls == [("signal", 0.0), "record", ("gate", True)]
    ns["_on_stop"]()
    assert calls[-2:] == ["stop", ("gate", False)]


def test_prediction_still_pushes_the_two_outputs_without_binding(classification_app, monkeypatch):
    """The continuous pose and discrete gesture share one frame without binding."""
    from types import SimpleNamespace

    import numpy as np

    ns = classification_app
    calls = []
    monkeypatch.setattr(
        type(ns["link"]), "ensure", lambda self: pytest.fail("predict must not bind")
    )
    ns["link"]._bus = SimpleNamespace(
        push=lambda values: calls.append(values) or values, stop=lambda: None
    )
    model = SimpleNamespace(predict_proba=lambda values: np.array([[0.1, 0.9]]))
    result = ns["predict"](model, np.array([1.0, 2.0]))
    assert result["class"] == 1
    assert calls == [{"fist": 1.0, "gesture": "Fist"}]
    assert result["hand"] == calls[0]
    ns["pipeline"].predictions = result
    assert [(label, value) for label, value, _targets in ns["_pushed"]()] == [
        ("fist · predicted hand (LSL)", "+1.00"),
        ("gesture · control hand (gRPC)", "Fist"),
    ]
    ns["link"]._bus = None
    assert "hand" not in ns["predict"](model, np.array([1.0, 2.0]))


@pytest.mark.parametrize("step", range(4))
@pytest.mark.parametrize("state", ["idle", "recording", "predicting"])
def test_simulator_is_available_on_each_step(
    classification_app, monkeypatch, implot_frame, step, state
):
    """Manual simulator changes never relabel a take or bypass the hand callbacks."""
    from imgui_bundle import imgui

    ns = classification_app
    ns["steps"].active = step
    ns["app"].ctx.state = state
    ns["app"].ctx.recording = state == "recording"
    ns["simulator"].set(0.0)
    samples, chips = [], []
    monkeypatch.setattr(ns["simulator"]._outlet, "push_sample", samples.append)
    original = imgui.small_button

    def click(label):
        clicked = original(label)
        if "##preset_" in label:
            disabled = bool(imgui.get_item_flags() & imgui.ItemFlags_.disabled)
            chips.append((label.split("##")[0], disabled))
            return label.startswith("Fist##") and not disabled
        return clicked

    monkeypatch.setattr(imgui, "small_button", click)
    implot_frame(lambda: ns["app"]._ui_fn(ns["app"].ctx))
    assert chips == [("Rest", state == "recording"), ("Fist", state == "recording")]
    assert ns["simulator"].value == (0.0 if state == "recording" else 1.0)
    assert len(samples) == (0 if state == "recording" else 1)
    assert ns["app"].ctx.current_label == -1


@pytest.mark.parametrize("failure", [False, True])
def test_hand_connect_checks_existing_service_before_launch(
    classification_app, monkeypatch, implot_frame, failure
):
    """The compact row connects off-thread, launches if absent and reports errors."""
    from types import SimpleNamespace

    from imgui_bundle import imgui

    ns = classification_app
    calls = []
    binder = SimpleNamespace(
        busy=False,
        finished=False,
        last_error=None,
        status="Connecting…",
        poll=lambda **kwargs: calls.append(("bind", kwargs)),
    )
    monkeypatch.setitem(ns["hand_ui"].__globals__, "binder", binder)
    monkeypatch.setitem(ns["hand_ui"].__globals__, "hand_processes", [(ns["vhi"].name, ["vhi"])])
    original = imgui.small_button

    def click(label):
        result = original(label)
        return label == "Connect##virtual_hand" or result

    def launch(self, name):
        calls.append(("launch", name))
        if failure:
            raise OSError("Hand executable cannot be launched")

    monkeypatch.setattr(imgui, "small_button", click)
    monkeypatch.setattr(type(ns["processes"]), "launch", launch)
    implot_frame(ns["hand_ui"])
    assert calls == [("bind", {"force": True})]
    assert ns["hand_attempt"]["phase"] == "checking"
    binder.finished = True
    implot_frame(ns["hand_ui"])
    assert calls[1] == ("launch", ns["vhi"].name)
    assert ns["hand_attempt"]["phase"] == ("failed" if failure else "launched")
    if failure:
        assert "cannot be launched" in ns["hand_attempt"]["error"]
    else:
        assert calls[2] == ("bind", {})


def test_hand_movement_palette_remains_accessible(classification_app, monkeypatch, implot_frame):
    """The existing movement widget keeps its callback and its own popover card."""
    from imgui_bundle import imgui

    ns = classification_app
    calls = []
    original = imgui.small_button

    def click(label):
        result = original(label)
        return "Hand movements" in label or result

    monkeypatch.setattr(imgui, "small_button", click)
    monkeypatch.setattr(type(ns["vhi_panel"]), "ui", lambda self: calls.append(self))
    implot_frame(ns["hand_ui"])
    assert calls == [ns["vhi_panel"]]
    assert ns["vhi_panel"]._on_movement is ns["_select_gesture"]


@pytest.mark.parametrize("width", [320, 800])
def test_hand_connection_words_and_actions_do_not_overlap(
    classification_app, monkeypatch, implot_frame, width
):
    """The connection remains readable even in a small scale-two card."""
    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(1000, 1500)
    items = []
    for name in ("text_unformatted", "text_colored", "small_button"):
        original = getattr(imgui, name)

        def item(*args, render=original, **kwargs):
            result = render(*args, **kwargs)
            low, high = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            items.append((str(args[-1]), low.x, low.y, high.x, high.y))
            return result

        monkeypatch.setattr(imgui, name, item)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1200))
        imgui.begin(
            "hand-width",
            flags=imgui.WindowFlags_.no_title_bar | imgui.WindowFlags_.horizontal_scrollbar,
        )
        classification_app["hand_ui"]()
        assert imgui.get_scroll_max_x() == 0
        imgui.end()

    for _ in range(4):
        items.clear()
        implot_frame(draw)
    for index, first in enumerate(items):
        for second in items[index + 1 :]:
            if not first[0] or not second[0]:
                continue
            overlap_x = min(first[3], second[3]) - max(first[1], second[1])
            overlap_y = min(first[4], second[4]) - max(first[2], second[2])
            assert overlap_x <= 1 or overlap_y <= 1, (first, second)


def test_hand_map_keeps_the_lsl_pose_and_debounced_grpc_gesture(classification_app):
    """The combined app names both routes in the mapping it actually loads."""
    ns = classification_app
    bindings = ns["CONTROL_MAP"].bindings
    assert ns["CONTROL_FILE"].name == "classification_grpc.toml"
    assert set(bindings) == {"fist", "gesture"}
    assert {ref.address for ref in bindings["fist"].targets} == {
        "vhi.prediction.thumb.flexion",
        "vhi.prediction.thumb.abduction",
        "vhi.prediction.index",
        "vhi.prediction.middle",
        "vhi.prediction.ring",
        "vhi.prediction.little",
    }
    assert [ref.address for ref in bindings["gesture"].targets] == ["vhi.control.gesture"]
    assert bindings["gesture"].debounce_s == 0.1


@pytest.mark.parametrize("step", range(4))
def test_all_steps_run_without_loading_grpc(monkeypatch, tmp_path, implot_frame, step):
    """No installation or service is required for the complete EMG workflow."""
    from types import SimpleNamespace

    import numpy as np
    from imgui_bundle import imgui

    from myogestic.remote import InterfaceSpec
    from myogestic.tools import emg_generator

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        InterfaceSpec, "launcher", lambda self: (_ for _ in ()).throw(FileNotFoundError())
    )
    calls = []

    def missing_grpc(self):
        calls.append("grpc")
        raise ModuleNotFoundError("No module named 'grpc'", name="grpc")

    monkeypatch.setattr(InterfaceSpec, "control_client", missing_grpc)
    monkeypatch.setattr(InterfaceSpec, "recording_client", missing_grpc)
    monkeypatch.setattr(
        emg_generator, "control_outlet", lambda: SimpleNamespace(push_sample=lambda x: None)
    )
    ns = runpy.run_path(str(_EXAMPLES_ROOT / "synthetic" / "emg_classification.py"))
    ns = ns["demo_ui"].__globals__
    streams = tuple(ns["app"].ctx.streams.values())
    try:
        ns["steps"].active = step
        words = []
        render = imgui.text_unformatted

        def text(value):
            words.append(value)
            return render(value)

        monkeypatch.setattr(imgui, "text_unformatted", text)
        implot_frame(lambda: ns["demo_ui"](ns["app"].ctx))
        assert not calls
        if step == 0:
            assert "Not running" in words
        model = SimpleNamespace(predict_proba=lambda values: np.array([[0.1, 0.9]]))
        assert ns["predict"](model, np.ones(2))["class"] == 1
        assert "hand" not in ns["predict"](model, np.ones(2))
        monkeypatch.setattr(ns["app"], "start_recording", lambda: calls.append("record"))
        monkeypatch.setattr(ns["app"], "stop_recording", lambda: calls.append("stop"))
        ns["app"].ctx.current_label = 1
        ns["_on_gesture"](1)
        ns["_on_record"]()
        ns["_on_stop"]()
        assert calls == ["record", "stop"]
        assert not ns["_init_hand"]()
        assert ns["link"] is ns["binder"] is None
        assert "grpc extra" in ns["hand_attempt"]["error"]
        implot_frame(ns["hand_ui"])
        assert calls == ["record", "stop", "grpc"]
    finally:
        for stream in streams:
            stream.stop()


def test_default_entrypoint_imports_no_optional_grpc_package(tmp_path):
    """A fresh Python process must wire and close on the default install."""
    import subprocess
    import sys

    example = _EXAMPLES_ROOT / "synthetic" / "emg_classification.py"
    script = """
import builtins
import runpy
import sys
original_import = builtins.__import__
def without_grpc(name, *args, **kwargs):
    if name == "grpc" or name.startswith(("grpc.", "google.protobuf")):
        raise ModuleNotFoundError(name, name=name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = without_grpc
from myogestic import App
App.run = lambda self: None
ns = runpy.run_path(sys.argv[1], run_name="__main__")
assert ns["link"] is None
assert ns["header"].title == "EMG classification"
assert "grpc" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(example)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
