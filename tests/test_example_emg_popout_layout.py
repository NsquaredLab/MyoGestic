"""The pop-out demo keeps its detachable panels inside the session shell."""

import platform
import runpy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
PANELS = {"Signal", "Streams", "Log", "Processes", "Recording", "Model",
          "Post-processing", "Sessions", "Prediction"}


@pytest.fixture
def popout_app(monkeypatch, tmp_path):
    from myogestic.remote import InterfaceSpec
    from myogestic.tools import emg_generator

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(InterfaceSpec, "launcher", lambda self: [(self.name, ["virtual-hand"])])
    monkeypatch.setattr(emg_generator, "control_outlet", lambda: SimpleNamespace(push_sample=lambda x: None))
    ns = runpy.run_path(str(ROOT / "examples/synthetic/emg_popout_layout.py"))
    streams = tuple(ns["app"].ctx.streams.values())
    try:
        yield ns
    finally:
        ns["link"].stop()
        ns["vhi_control"].stop()
        for stream in streams:
            stream.stop()


def test_popout_session_shell_and_original_detachable_panels(popout_app):
    from myogestic import Fr, Px
    from myogestic.widgets import AppHeader, SimulatorControls, StatusBar

    ns = popout_app
    layout, header, steps = (ns[key] for key in ("layout", "header", "steps"))
    assert isinstance(header, AppHeader) and header.title == "EMG · pop-out panels"
    assert header.steps is steps and header.participant is ns["participant"]
    assert steps.steps == ["Connect", "Record", "Train", "Predict"]
    assert steps._widget_id == "emg_popout_layout_steps"
    assert isinstance(ns["status"], StatusBar) and ns["status"].pipeline is ns["pipeline"]
    assert isinstance(ns["simulator"], SimulatorControls)
    assert ns["simulator"]._presets == list(zip(ns["CLASSES"], ns["CTRL_VALUES"], strict=True))
    assert "ctrl_outlet" not in ns and "_model_block" not in ns
    assert ns["app"]._docking and ns["app"].ctx.require_participant
    assert not ns["recording"]._show_header and not ns["features"]._show_header
    assert layout.panel_names == {"header", "signal", "simulator", "step", "sessions", "log", "status"}
    assert layout._breakpoint == Px(1100)
    assert layout._wide._col_tracks == [Fr(1), Px(400)]
    for grid in (layout._wide, layout._narrow):
        assert grid._bare == {"header", "status"}
        assert grid._row_tracks[0] == Px(52) and grid._row_tracks[-1] == Px(26)
        signal, simulator = grid._areas["signal"], grid._areas["simulator"]
        assert simulator[0] == signal[1] and simulator[2:] == signal[2:]
    specs = ns["app"]._popout_specs
    assert {title for title, *_ in specs} == PANELS
    assert all(spec[2:] == (False, True, False) for spec in specs)


def test_popout_completion_and_recording_callbacks(popout_app, monkeypatch, tmp_path):
    ns = popout_app
    ctx = ns["app"].ctx
    done = ns["_step_done"]
    assert done(ctx) == [False] * 4
    ctx.participant = "P-014"
    folder = tmp_path / "sessions" / ctx.participant
    folder.mkdir(parents=True)
    (folder / "someone-else_take.session.zip").touch()
    monkeypatch.setitem(ctx.streams, "emg", SimpleNamespace(status="connected", info=object()))
    assert done(ctx) == [True, False, False, False]
    (folder / "P-014_take.session.zip").touch()
    ns["pipeline"].model = object()
    ctx.state = "predicting"
    assert done(ctx) == [True] * 4
    calls = []
    monkeypatch.setattr(type(ns["link"]), "ensure", lambda self: calls.append("bind"))
    monkeypatch.setattr(ns["app"], "start_recording", lambda: calls.append("record"))
    ns["simulator"].set(0)
    monkeypatch.setattr(ns["simulator"]._outlet, "push_sample", lambda value: calls.append(value))
    for index, value in enumerate(ns["CTRL_VALUES"]):
        calls.clear()
        ns["_on_gesture"](index)
        assert calls[0] == "bind"
        np.testing.assert_array_equal(calls[1], np.array([value], dtype=np.float32))
    ctx.current_label = 1
    calls.clear()
    ns["_on_record"]()
    assert calls[0] == "bind" and calls[2] == "record"
    np.testing.assert_array_equal(calls[1], np.array([1.0], dtype=np.float32))


def test_popout_features_and_prediction_preserve_the_original_wiring(popout_app, monkeypatch):
    import torch

    ns = popout_app
    emg = np.random.default_rng(0).normal(size=(32, 512)).astype(np.float32)
    tensor = torch.from_numpy(emg).float()
    expected = np.concatenate([ns[key](tensor).numpy().flatten()
                               for key in ("rms_transform", "mav_transform", "wl_transform")])
    np.testing.assert_array_equal(ns["extract"]({"emg": emg}), expected)
    pushed = []
    bus = SimpleNamespace(push=lambda values: pushed.append(values) or values)
    monkeypatch.setattr(type(ns["link"]), "bus", property(lambda self: bus))
    for index in range(4):
        proba = np.eye(4)[index]
        result = ns["predict"](SimpleNamespace(predict_proba=lambda x, p=proba: p[None]), expected)
        assert result["class"] == index
        assert pushed[-1] == {**dict.fromkeys(ns["POSE_ALIASES"], 0.0), **ns["HAND_POSES"][index]}


def _light_theme(monkeypatch, width):
    from imgui_bundle import hello_imgui, imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    font_path = Path(_theme._SYS_FONTS.get(platform.system(), ""))
    if not font_path.is_file():
        font_path = Path(hello_imgui.asset_file_full_path("fonts/Roboto/Roboto-Regular.ttf"))
    imgui.get_io().font_default = imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 14)
    font_dir = ROOT / "myogestic/assets/fonts"
    for attr, filename, size in (("_MONO_FONT", "IBMPlexMono-Regular.ttf", 13),
                                 ("_DISPLAY_FONT", "InstrumentSerif-Regular.ttf", 28)):
        font = imgui.get_io().fonts.add_font_from_file_ttf(str(font_dir / filename), size)
        monkeypatch.setattr(_theme, attr, font)
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width, 1656)


@pytest.mark.parametrize("step", range(4))
@pytest.mark.parametrize("width", [2560, 1800])
@pytest.mark.parametrize("state", ["empty", "participant", "trained", "recording", "training"])
def test_popout_shell_fits_light_theme(popout_app, monkeypatch, implot_frame, step, width, state):
    from imgui_bundle import imgui

    ns = popout_app
    app = ns["app"]
    ns["steps"].active = step
    if state != "empty":
        app.ctx.participant = "P-014"
    if state == "trained":
        ns["pipeline"].model = object()
        ns["pipeline"].train_log.append("Trained on 100 windows from 4 sessions.")
        ns["pipeline"].predictions.update({"class": 2, "proba": [0.1, 0.1, 0.7, 0.1]})
        app.ctx.state = "predicting" if step == 3 else "idle"
    if state in {"recording", "training"}:
        app.ctx.state = state
    if state == "training":
        ns["pipeline"].train_log.append("Fitting 32 channels and four gesture classes.")
    _light_theme(monkeypatch, width)
    monkeypatch.setattr(imgui, "begin_tab_bar", lambda *a: pytest.fail("the shell has no tabs"))
    cells, buttons, headings, records, texts = [], [], [], [], []
    original_header = ns["panel_header"]

    def header(title, *args, **kwargs):
        headings.append(title)
        return original_header(title, *args, **kwargs)

    monkeypatch.setitem(app._ui_fn.__globals__, "panel_header", header)
    for method in ("button", "small_button"):
        original = getattr(imgui, method)

        def button(label, *args, _original=original, **kwargs):
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            result = _original(label, *args, **kwargs)
            buttons.append((label, imgui.get_item_rect_max().x - right))
            return result

        monkeypatch.setattr(imgui, method, button)
    for method in ("text", "text_unformatted", "text_colored", "text_wrapped", "text_disabled"):
        original = getattr(imgui, method)

        def text(*args, _original=original, method=method, **kwargs):
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            result = _original(*args, **kwargs)
            label = args[1] if method == "text_colored" else args[0]
            texts.append((label, imgui.get_item_rect_max().x - right))
            return result

        monkeypatch.setattr(imgui, method, text)
    for name in ("connect_ui", "model_ui", "predict_ui", "signal_ui", "log_ui"):
        original = ns[name]

        def view(*args, _original=original, name=name):
            _original(*args)
            cells.append((name, imgui.get_cursor_pos_y(), imgui.get_window_size().y,
                          imgui.get_scroll_max_x(), imgui.get_scroll_max_y()))

        monkeypatch.setitem(app._ui_fn.__globals__, name, view)
    for name in ("simulator", "recording", "sessions"):
        widget = ns[name]
        original = type(widget).ui

        def view(self, *args, _original=original, name=name, **kwargs):
            result = _original(self, *args, **kwargs)
            if name == "recording":
                records.append(kwargs.get("visible", True))
            if kwargs.get("visible", True):
                cells.append((name, imgui.get_cursor_pos_y(), imgui.get_window_size().y,
                              imgui.get_scroll_max_x(), imgui.get_scroll_max_y()))
            return result

        monkeypatch.setattr(type(widget), "ui", view)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1656))
        imgui.begin("popout-shell", flags=imgui.WindowFlags_.no_title_bar)
        app._ui_fn(app.ctx)
        assert imgui.get_scroll_max_x() == imgui.get_scroll_max_y() == 0
        imgui.end()

    for _ in range(4):
        cells.clear()
        buttons.clear()
        headings.clear()
        records.clear()
        texts.clear()
        implot_frame(draw)
    assert ns["steps"].steps[step] in headings and "MODEL" not in headings
    assert records == [step == 1]
    assert all(overhang <= 1 for _, overhang in buttons), buttons
    assert all(horizontal == 0 for _, _, _, horizontal, _ in cells), cells
    if width == 2560:
        assert all(overhang <= 1 for _, overhang in texts), texts
        assert all(cursor - imgui.get_style().item_spacing.y <= height and vertical == 0
                   for _, cursor, height, _, vertical in cells), cells
    assert ns["layout"]._active is (ns["layout"]._wide if width == 2560 else ns["layout"]._narrow)


def test_popout_actions_open_registered_windows_and_training_log_survives_steps(
    popout_app, monkeypatch, implot_frame,
):
    from imgui_bundle import hello_imgui, imgui

    from myogestic.widgets.panels.popout import _make_dockable_window

    ns = popout_app
    app = ns["app"]
    params = hello_imgui.RunnerParams()
    params.docking_params.dockable_windows = [_make_dockable_window(*spec) for spec in app._popout_specs]
    app._runner_params = params
    for title in PANELS:
        assert not ns["_panel_visible"](title)
        ns["_show_panel"](title)
        assert ns["_panel_visible"](title)
    # Closing windows in the runner must be reflected immediately, including Recording.
    for window in params.docking_params.dockable_windows:
        window.is_visible = False
    assert not any(ns["_panel_visible"](title) for title in PANELS)
    calls = []
    monkeypatch.setitem(app._ui_fn.__globals__, "render_log_popout",
                        lambda *args, **kwargs: calls.append(kwargs["title"]) or True)
    monkeypatch.setitem(app._ui_fn.__globals__, "_log_popout_open", True)
    for step in range(4):
        ns["steps"].active = step
        implot_frame(lambda: app._ui_fn(app.ctx))
    assert calls == ["Model training log"] * 4
    # A detached Recording card owns its visible tick; the shell must not tick it twice.
    ns["_show_panel"]("Recording")
    monkeypatch.setattr(type(ns["recording"]), "ui", lambda self, *a, **kw: calls.append("record"))
    ns["steps"].active = 1
    callbacks = {title: callback for title, callback, *_ in app._popout_specs}

    def draw():
        app._ui_fn(app.ctx)
        imgui.begin("Detached Recording")
        callbacks["Recording"]()
        imgui.end()

    calls.clear()
    implot_frame(draw)
    assert calls.count("record") == 1


@pytest.mark.parametrize("step", range(4))
@pytest.mark.parametrize("state", ["idle", "recording", "predicting"])
def test_popout_simulator_is_available_on_every_step(popout_app, monkeypatch, implot_frame, step, state):
    from imgui_bundle import imgui

    ns = popout_app
    ns["steps"].active = step
    ns["app"].ctx.state = state
    ns["simulator"].set(0.0)
    values = []
    monkeypatch.setattr(ns["simulator"]._outlet, "push_sample", lambda value: values.append(float(value[0])))
    original = imgui.small_button

    def click(label):
        result = original(label)
        if "##preset_" in label:
            return label.startswith("Pinch##") and not (imgui.get_item_flags() & imgui.ItemFlags_.disabled)
        return result

    monkeypatch.setattr(imgui, "small_button", click)
    implot_frame(lambda: ns["app"]._ui_fn(ns["app"].ctx))
    assert values == ([] if state == "recording" else [2.0])
    assert ns["app"].ctx.current_label == -1


def test_popout_header_buttons_open_windows_and_log(popout_app, monkeypatch, implot_frame):
    from imgui_bundle import imgui

    ns = popout_app
    opened, labels = [], []
    scope = ns["app"]._ui_fn.__globals__
    monkeypatch.setitem(scope, "_show_panel", opened.append)
    original_small, original_button = imgui.small_button, imgui.button

    def small(label):
        result = original_small(label)
        if "##panels_" in label:
            labels.append(label)
            return True
        return result

    def button(label, *args, **kwargs):
        result = original_button(label, *args, **kwargs)
        return True if label.endswith("##ml_popout_popout") else result

    monkeypatch.setattr(imgui, "small_button", small)
    monkeypatch.setattr(imgui, "button", button)
    implot_frame(lambda: ns["_card_header"]("Activity log", panel="Log"))
    implot_frame(lambda: ns["_card_header"]("Train", training=True))
    assert opened == ["Log"]
    assert scope["_log_popout_open"]
    assert all(len(label.split("##")[0]) == 1 for label in labels)
