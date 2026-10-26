"""The four-class multi-model example keeps its workflow on the session shell."""

import runpy
from pathlib import Path

import pytest

import myogestic.remote

_EXAMPLES_ROOT = Path(__file__).resolve().parent.parent / "examples"
PANELS = {"Signal", "Streams", "Log", "Processes", "Connect", "Recording", "Model",
          "Post-processing", "Sessions", "Prediction", "Simulated EMG"}


@pytest.fixture
def multi_model_app(monkeypatch, tmp_path):
    """Wire the classification workflow without launching its external targets."""
    from types import SimpleNamespace

    from myogestic.tools import emg_generator

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(emg_generator, "control_outlet", lambda: SimpleNamespace(push_sample=lambda x: None))
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [("Virtual Hand", ["unused"])])
    namespace = runpy.run_path(str(_EXAMPLES_ROOT / "synthetic" / "emg_32ch_multi_model.py"))
    streams = tuple(namespace["app"].ctx.streams.values())
    try:
        yield namespace
    finally:
        namespace["link"].stop()
        namespace["vhi_control"].stop()
        for stream in streams:
            stream.stop()


def test_multi_model_uses_the_session_shell(multi_model_app):
    """One header and active step surround a persistent signal and sessions."""
    from myogestic import Fr, Px
    from myogestic.widgets import AppHeader, SimulatorControls, StatusBar

    ns = multi_model_app
    layout, header, steps = (ns[name] for name in ("layout", "header", "steps"))
    assert isinstance(header, AppHeader) and header.title == "EMG · 32 ch multi-model"
    assert header.steps is steps and header.participant is ns["participant"]
    assert steps.steps == ["Connect", "Record", "Train", "Predict"]
    assert steps._widget_id == "emg_32ch_multi_model_steps"
    assert isinstance(ns["status"], StatusBar) and ns["status"].pipeline is ns["pipeline"]
    assert isinstance(ns["simulator"], SimulatorControls)
    assert "ctrl_outlet" not in ns
    assert not ns["recording"]._show_header
    assert ns["app"]._docking
    assert ns["simulator"]._presets == list(zip(ns["CLASSES"], ns["CTRL_VALUES"], strict=True))
    specs = ns["app"]._popout_specs
    assert {title for title, *_ in specs} == PANELS
    assert all(spec[2:] == (False, True, False) for spec in specs)
    assert layout.panel_names == {"header", "signal", "simulator", "step", "sessions", "log", "status"}
    assert layout._breakpoint == Px(1100)
    assert layout._wide._col_tracks == [Fr(1), Px(400)]
    assert layout._wide._areas == {
        "header": (0, 1, 0, 2), "signal": (1, 3, 0, 1),
        "step": (1, 2, 1, 2), "sessions": (2, 5, 1, 2),
        "simulator": (3, 4, 0, 1), "log": (4, 5, 0, 1), "status": (5, 6, 0, 2),
    }
    for grid in (layout._wide, layout._narrow):
        assert grid._bare == {"header", "status"}
        assert grid._row_tracks[0] == Px(52) and grid._row_tracks[-1] == Px(26)
        signal, simulator = grid._areas["signal"], grid._areas["simulator"]
        assert simulator[0] == signal[1] and simulator[2:] == signal[2:]
        assert grid._row_tracks[simulator[0]] == Px(76)


def test_multi_model_completion_tracks_the_participants_takes(multi_model_app, monkeypatch, tmp_path):
    from types import SimpleNamespace

    ns = multi_model_app
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
@pytest.mark.parametrize("state", ["idle", "recording", "training"])
def test_multi_model_shell_fits_light_theme(
    multi_model_app, monkeypatch, implot_frame, step, width, participant, trained, state,
):
    """Every active card fits the default window; narrow cards remain reachable."""
    import platform

    from imgui_bundle import hello_imgui, imgui

    from myogestic import _scale, _theme
    from myogestic.ml import widgets as ml_widgets
    from myogestic.widgets.panels import process_launcher, recording
    from myogestic.widgets.signals import simulator_controls

    ns = multi_model_app
    app = ns["app"]
    app.ctx.participant = participant
    ns["steps"].active = step
    if trained:
        ns["pipeline"].model = object()
        ns["pipeline"].train_log.append("Trained on 100 windows from 2 sessions.")
        ns["pipeline"].predictions.update({"class": 1, "proba": [0.1, 0.7, 0.1, 0.1]})
        app.ctx.state = "predicting" if step == 3 else "idle"
    if state != "idle":
        app.ctx.state = state
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
    for attr, filename, size in (("_MONO_FONT", "IBMPlexMono-Regular.ttf", 13),
                                 ("_DISPLAY_FONT", "InstrumentSerif-Regular.ttf", 28)):
        font = imgui.get_io().fonts.add_font_from_file_ttf(str(font_dir / filename), size)
        monkeypatch.setattr(_theme, attr, font)
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width, 1656)
    headers, views, cells, buttons, heights = [], [], [], [], {}
    text_bounds = []
    for method in ("text", "text_unformatted", "text_wrapped", "text_colored"):
        original_text = getattr(imgui, method)

        def text_item(*args, original=original_text, **kwargs):
            result = original(*args, **kwargs)
            lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            draw = imgui.get_window_draw_list()
            clip_lo, clip_hi = draw.get_clip_rect_min(), draw.get_clip_rect_max()
            text_bounds.append((str(args), lo.x - clip_lo.x, clip_hi.x - hi.x,
                                lo.y - clip_lo.y, clip_hi.y - hi.y))
            return result

        monkeypatch.setattr(imgui, method, text_item)
    original_header = ns["panel_header"]

    def header(title, *args, **kwargs):
        headers.append(title)
        return original_header(title, *args, **kwargs)

    monkeypatch.setitem(app._ui_fn.__globals__, "panel_header", header)
    for module in (ml_widgets, process_launcher, recording, simulator_controls):
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
    render_connect = ns["connect_ui"]

    def connect(ctx):
        render_connect(ctx)
        cells.append(("connect", imgui.get_cursor_pos_y(), imgui.get_window_size().y,
                      imgui.get_scroll_max_x(), imgui.get_scroll_max_y()))

    monkeypatch.setitem(app._ui_fn.__globals__, "connect_ui", connect)
    for name in ("viewer", "simulator", "recording", "train_button", "training_log",
                 "prediction", "predict_button", "output_filter", "sessions", "status"):
        widget = ns[name]
        render = type(widget).ui

        def view(self, *args, name=name, render=render, **kwargs):
            views.append((name, kwargs))
            result = render(self, *args, **kwargs)
            if kwargs.get("visible", True) and name != "status":
                heights[name] = imgui.get_window_size().y
                cells.append((name, imgui.get_cursor_pos_y(), imgui.get_window_size().y,
                              imgui.get_scroll_max_x(), imgui.get_scroll_max_y()))
            return result

        monkeypatch.setattr(type(widget), "ui", view)

    render_log = ns["log_ui"]

    def log():
        views.append(("log", {}))
        render_log()
        cells.append(("log", imgui.get_cursor_pos_y(), imgui.get_window_size().y,
                      imgui.get_scroll_max_x(), imgui.get_scroll_max_y()))

    monkeypatch.setitem(app._ui_fn.__globals__, "log_ui", log)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1656))
        imgui.begin("multi-model-shell", flags=imgui.WindowFlags_.no_title_bar)
        app._ui_fn(app.ctx)
        assert imgui.get_scroll_max_x() == imgui.get_scroll_max_y() == 0
        imgui.end()

    for _ in range(4):
        headers.clear()
        views.clear()
        cells.clear()
        buttons.clear()
        text_bounds.clear()
        implot_frame(draw)
    assert headers == [ns["steps"].steps[step], "Signal", "Simulated EMG", "Activity log"]
    expected = {"viewer", "simulator", "recording", "sessions", "log", "status"}
    expected |= {2: {"train_button", "training_log"},
                 3: {"prediction", "predict_button", "output_filter"}}.get(step, set())
    assert {name for name, _ in views} == expected
    record_calls = [kwargs for name, kwargs in views if name == "recording"]
    assert len(record_calls) == 1
    assert record_calls[0].get("visible", True) == (step == 1)
    assert next(kwargs for name, kwargs in views if name == "sessions") == {"participant": participant}
    assert all(overhang <= 1 for _, overhang in buttons), buttons
    assert all(horizontal == 0 for _, _, _, horizontal, _ in cells), cells
    assert heights["viewer"] > heights["simulator"]
    assert all(cursor - imgui.get_style().item_spacing.y <= height and vertical == 0
               for name, cursor, height, _, vertical in cells if name == "simulator"), cells
    if width == 2560:
        assert all(min(bounds[1:]) >= -1 for bounds in text_bounds), text_bounds
        assert all(cursor - imgui.get_style().item_spacing.y <= height and vertical == 0
                   for _, cursor, height, _, vertical in cells), cells
    assert ns["layout"]._active is (ns["layout"]._wide if width == 2560 else ns["layout"]._narrow)


def test_multi_model_recording_callbacks_keep_the_generator_and_hand_wiring(multi_model_app, monkeypatch):
    """Recording callbacks synchronize the simulator, hand and selected label."""
    import numpy as np

    from myogestic.tools import emg_generator

    ns = multi_model_app
    calls = []
    monkeypatch.setattr(type(ns["link"]), "ensure", lambda self: calls.append("bind"))
    outlet = emg_generator.control_outlet()
    monkeypatch.setattr(outlet, "push_sample", lambda value: calls.append(value))
    monkeypatch.setattr(emg_generator, "control_outlet", lambda: outlet)
    monkeypatch.setattr(ns["app"], "start_recording", lambda: calls.append("record"))
    ns["_on_gesture"](1)
    assert calls[0] == "bind"
    np.testing.assert_array_equal(calls[1], np.array([1.0], dtype=np.float32))
    assert ns["simulator"].value == 1.0
    calls.clear()
    ns["_on_record"]()
    assert calls == ["bind", "record"]
    # Previewing another signal must not change the gesture of the next take.
    calls.clear()
    ns["app"].ctx.current_label = 0
    ns["_on_record"]()
    assert calls[0] == "bind" and calls[2] == "record"
    np.testing.assert_array_equal(calls[1], np.array([0.0], dtype=np.float32))
    assert ns["simulator"].value == 0.0


@pytest.mark.parametrize("step", range(4))
@pytest.mark.parametrize("state", ["idle", "recording", "predicting"])
def test_multi_model_simulator_steers_each_step_and_defers_to_recording(
    multi_model_app, monkeypatch, implot_frame, step, state,
):
    """The persistent chips drive only the signal, and recording can still set it."""
    from imgui_bundle import imgui

    ns = multi_model_app
    ns["steps"].active = step
    ns["app"].ctx.state = state
    # Establish the lazy outlet, then observe the samples without touching LSL.
    ns["simulator"].set(0.0)
    samples, chips = [], []
    monkeypatch.setattr(ns["simulator"]._outlet, "push_sample", lambda value: samples.append(value))
    button = imgui.small_button

    def click(label):
        result = button(label)
        if "##preset_" in label:
            disabled = bool(imgui.get_item_flags() & imgui.ItemFlags_.disabled)
            chips.append((label.split("##")[0], disabled))
            return label.startswith("Fist##") and not disabled
        return result

    monkeypatch.setattr(imgui, "small_button", click)
    implot_frame(lambda: ns["app"]._ui_fn(ns["app"].ctx))
    assert chips == [(label, state == "recording") for label in ns["CLASSES"]]
    assert ns["simulator"].value == (0.0 if state == "recording" else 1.0)
    assert len(samples) == (0 if state == "recording" else 1)
    assert ns["app"].ctx.current_label == -1
    monkeypatch.setattr(type(ns["link"]), "ensure", lambda self: None)
    ns["_on_gesture"](1)
    assert ns["simulator"].value == 1.0


@pytest.mark.parametrize("gesture", range(4))
def test_recording_resyncs_each_of_the_four_presets(multi_model_app, monkeypatch, gesture):
    """Previewing any other class must not change the label of the next take."""
    ns = multi_model_app
    calls = []
    monkeypatch.setattr(type(ns["link"]), "ensure", lambda self: calls.append("bind"))
    monkeypatch.setattr(type(ns["simulator"]), "set", lambda self, value: calls.append(value))
    monkeypatch.setattr(ns["app"], "start_recording", lambda: calls.append("record"))
    ns["_on_gesture"](gesture)
    assert calls == ["bind", ns["CTRL_VALUES"][gesture]]
    calls.clear()
    ns["app"].ctx.current_label = gesture
    ns["_on_record"]()
    assert calls == ["bind", ns["CTRL_VALUES"][gesture], "record"]


def test_classifier_caption_and_icon_actions_keep_model_persistence(
    multi_model_app, monkeypatch, implot_frame, tmp_path,
):
    """The recipe precedes Train, Save auto-names, and Load opens the same picker."""
    from types import SimpleNamespace

    from imgui_bundle import imgui

    ns = multi_model_app
    globals_ = ns["model_ui"].__globals__
    ns["steps"].active = 2
    ns["pipeline"].model = {"fitted": "example"}
    calls, tooltips = [], []
    monkeypatch.setattr(ns["_time"], "strftime", lambda fmt: "20261025_120000")
    monkeypatch.setattr(imgui, "set_item_tooltip", lambda text: tooltips.append(text))
    original_text = imgui.text_colored
    original_combo = imgui.combo
    original_button = imgui.small_button
    clicked = {"save_model"}

    def caption(color, text):
        calls.append(text)
        return original_text(color, text)

    def combo(label, selected, names):
        original_combo(label, selected, names)
        assert calls[-1] == "Classifier"
        assert names == ns["MODEL_NAMES"]
        calls.append("recipe")
        return True, 3

    def button(label):
        result = original_button(label)
        if label.endswith(("##save_model", "##load_model")):
            visible, action = label.split("##")
            assert len(visible) == 1
            if action in clicked:
                clicked.remove(action)
                return True
        return result

    monkeypatch.setattr(imgui, "text_colored", caption)
    monkeypatch.setattr(imgui, "combo", combo)
    monkeypatch.setattr(imgui, "small_button", button)
    monkeypatch.setattr(type(ns["train_button"]), "ui", lambda self: calls.append("train"))
    monkeypatch.setattr(ns["pfd"], "open_file", lambda *args: (
        calls.append(args), SimpleNamespace(ready=lambda: False)
    )[1])
    implot_frame(lambda: ns["app"]._ui_fn(ns["app"].ctx))
    assert calls.index("recipe") < calls.index("train")
    assert globals_["selected_model_idx"] == 3
    saved = tmp_path / "models" / "CatBoost_20261025_120000.joblib"
    assert ns["load_pickle"](str(saved)) == ns["pipeline"].model
    assert ns["_save_current"]().name == "Logistic_Regression_20261025_120000.joblib"
    clicked.add("load_model")
    implot_frame(lambda: ns["app"]._ui_fn(ns["app"].ctx))
    assert ("Load model", "models", ["Model", "*.joblib"]) in calls
    assert any(t.startswith("Save model") for t in tooltips)
    assert any(t.startswith("Load model") for t in tooltips)


@pytest.mark.parametrize("step", [0, 1, 3])
def test_model_dialog_and_log_survive_leaving_train(multi_model_app, monkeypatch, implot_frame, step):
    """An open picker or training-log window stays alive off the Train step."""
    from types import SimpleNamespace

    ns = multi_model_app
    globals_ = ns["demo_ui"].__globals__
    model = {"recipe": "saved model"}
    path = Path("saved.joblib")
    ns["save_pickle"](model, str(path))
    monkeypatch.setitem(globals_, "_load_dialog", SimpleNamespace(
        ready=lambda: True, result=lambda: [str(path)],
    ))
    monkeypatch.setitem(globals_, "_popout_open", True)
    popouts = []
    monkeypatch.setitem(globals_, "render_log_popout", lambda *a, **k: popouts.append(k) or True)
    ns["steps"].active = step
    implot_frame(lambda: ns["app"]._ui_fn(ns["app"].ctx))
    assert ns["pipeline"].model == model
    assert globals_["_load_dialog"] is None
    assert popouts == [{"title": "Model training log"}]
    assert "Loaded" in ns["app"].ctx.status_message


def test_features_and_prediction_preserve_the_original_wiring(multi_model_app, monkeypatch):
    from types import SimpleNamespace

    import numpy as np
    import torch

    ns = multi_model_app
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
        assert pushed[-1] == ns["HAND_POSES"][index]


def test_popout_actions_open_registered_windows_and_training_log_survives_steps(
    multi_model_app, monkeypatch, implot_frame,
):
    from imgui_bundle import hello_imgui, imgui

    from myogestic.widgets.panels.popout import _make_dockable_window

    ns = multi_model_app
    app = ns["app"]
    params = hello_imgui.RunnerParams()
    params.docking_params.dockable_windows = [_make_dockable_window(*spec) for spec in app._popout_specs]
    app._runner_params = params
    for title in PANELS:
        assert not ns["_panel_visible"](title)
        ns["_show_panel"](title)
        assert ns["_panel_visible"](title)
        window = next(window for window in params.docking_params.dockable_windows
                      if window.label == title)
        assert window.dock_space_name == "" and window.focus_window_at_next_frame
    # Closing windows in the runner must be reflected immediately, including Recording.
    for window in params.docking_params.dockable_windows:
        window.is_visible = False
    assert not any(ns["_panel_visible"](title) for title in PANELS)
    calls = []
    monkeypatch.setitem(app._ui_fn.__globals__, "render_log_popout",
                        lambda *args, **kwargs: calls.append(kwargs["title"]) or True)
    monkeypatch.setitem(app._ui_fn.__globals__, "_popout_open", True)
    for step in range(4):
        ns["steps"].active = step
        implot_frame(lambda: app._ui_fn(app.ctx))
    assert calls == ["Model training log"] * 4
    # A detached Recording card owns its visible tick; the shell must not tick it twice.
    ns["_show_panel"]("Recording")
    monkeypatch.setattr(type(ns["recording"]), "ui", lambda self, *a, **kw: calls.append("record"))
    callbacks = {title: callback for title, callback, *_ in app._popout_specs}

    def draw():
        app._ui_fn(app.ctx)
        imgui.begin("Detached Recording")
        callbacks["Recording"]()
        imgui.end()

    for step in range(4):
        ns["steps"].active = step
        calls.clear()
        implot_frame(draw)
        assert calls.count("record") == 1
    # Closing the detached window returns the visible or hidden tick to the shell.
    for window in params.docking_params.dockable_windows:
        window.is_visible = False
    calls.clear()
    implot_frame(lambda: app._ui_fn(app.ctx))
    assert calls.count("record") == 1


def test_popout_header_buttons_open_windows_and_log(multi_model_app, monkeypatch, implot_frame):
    from imgui_bundle import imgui

    ns = multi_model_app
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
        return True if label.endswith("##ml_multi_popout") else result

    monkeypatch.setattr(imgui, "small_button", small)
    monkeypatch.setattr(imgui, "button", button)
    implot_frame(lambda: ns["_card_header"]("Activity log", panel="Log"))
    implot_frame(lambda: ns["_card_header"]("Train", training=True))
    assert opened == ["Log"]
    assert scope["_popout_open"]
    assert all(len(label.split("##")[0]) == 1 for label in labels)


@pytest.mark.parametrize("target", sorted(PANELS))
def test_step_header_chooser_can_open_every_card(multi_model_app, monkeypatch, implot_frame, target):
    """Cards without a window action of their own stay reachable from the step header."""
    from imgui_bundle import imgui

    ns = multi_model_app
    opened, choices = [], []
    scope = ns["demo_ui"].__globals__
    monkeypatch.setitem(scope, "_show_panel", opened.append)
    original_button, original_selectable = imgui.small_button, imgui.selectable

    def button(label):
        result = original_button(label)
        return True if "##panels_" in label else result

    def selectable(label, selected):
        original_selectable(label, selected)
        choices.append(label)
        return label == target, selected

    monkeypatch.setattr(imgui, "small_button", button)
    monkeypatch.setattr(imgui, "selectable", selectable)
    implot_frame(lambda: ns["_card_header"]("Connect"))
    assert set(choices) == PANELS
    assert opened == [target]
