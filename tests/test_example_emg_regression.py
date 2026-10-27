"""Regression keeps its capture and continuous control inside the session shell."""

import platform
import runpy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def regression_app(monkeypatch, tmp_path):
    """Build the real example without external processes or a control outlet."""
    pytest.importorskip("torch")
    pytest.importorskip("myoverse")
    from myogestic.remote import InterfaceSpec
    from myogestic.tools import emg_generator

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(InterfaceSpec, "launcher", lambda self: [(self.name, ["virtual-hand"])])
    monkeypatch.setattr(
        emg_generator, "control_outlet", lambda: SimpleNamespace(push_sample=lambda x: None)
    )
    ns = runpy.run_path(str(ROOT / "examples/synthetic/emg_regression.py"))
    streams = tuple(ns["app"].ctx.streams.values())
    try:
        yield ns
    finally:
        ns["link"].stop()
        ns["recording_aid"].stop()
        ns["vhi_control"].stop()
        for stream in streams:
            stream.stop()


def test_regression_uses_the_session_shell(regression_app):
    """The simulator follows the signal while steps share one header and footer."""
    from myogestic import Fr, Px
    from myogestic.widgets import AppHeader, SimulatorControls, StatusBar

    ns = regression_app
    layout, header, steps = (ns[name] for name in ("layout", "header", "steps"))
    assert isinstance(header, AppHeader) and header.title == "EMG regression"
    assert header.steps is steps and header.participant is ns["participant"]
    assert steps.steps == ["Connect", "Record", "Train", "Predict"]
    assert steps._widget_id == "emg_regression_steps"
    assert isinstance(ns["status"], StatusBar) and ns["status"].pipeline is ns["pipeline"]
    assert isinstance(ns["simulator"], SimulatorControls)
    assert not {"ctrl_outlet", "logo", "panel"} & ns.keys()
    assert not ns["recording"]._show_header and not ns["streams"]._show_header
    assert set(ns["app"].ctx.streams) == {"emg", "vhi_control"}
    assert ns["processes"]._processes == ns["PROCESSES"]
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


def test_regression_completion_tracks_the_participants_takes(regression_app, monkeypatch, tmp_path):
    """Optional kinematics do not block the existing labelled-take fallback."""
    ns = regression_app
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
@pytest.mark.parametrize("scenario", ["empty", "participant", "recording", "trained", "failure"])
def test_regression_shell_fits_light_theme(
    regression_app,
    monkeypatch,
    implot_frame,
    step,
    width,
    scenario,
):
    """Measure all real cards at scale two, including their visible text and actions."""
    from imgui_bundle import hello_imgui, imgui

    from myogestic import _scale, _theme
    from myogestic.ml import widgets as ml_widgets
    from myogestic.widgets.panels import process_launcher, recording
    from myogestic.widgets.signals import simulator_controls, stream_panel

    ns = regression_app
    app = ns["app"]
    ns["steps"].active = step
    app.ctx.participant = "" if scenario == "empty" else "P-014"
    if scenario == "trained":
        ns["pipeline"].model = object()
        ns["pipeline"].train_log.append("Trained on 100 windows from 2 sessions.")
        ns["pipeline"].predictions["dof"] = dict.fromkeys(ns["DOF_NAMES"], 0.75)
        app.ctx.state = "predicting" if step == 3 else "idle"
    elif scenario == "recording":
        app.ctx.state = "recording"
        app.ctx.recording = True
    elif scenario == "failure":
        ns["launch_errors"].update(
            dict.fromkeys((name for name, _ in ns["PROCESSES"]), "Executable not found")
        )
        for stream in app.ctx.streams.values():
            stream.last_error = "No matching outlet found; start the source and retry."
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    font_path = Path(_theme._SYS_FONTS.get(platform.system(), ""))
    if not font_path.is_file():
        font_path = Path(hello_imgui.asset_file_full_path("fonts/Roboto/Roboto-Regular.ttf"))
    imgui.get_io().font_default = imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 14)
    for attr, filename, size in (
        ("_MONO_FONT", "IBMPlexMono-Regular.ttf", 13),
        ("_DISPLAY_FONT", "InstrumentSerif-Regular.ttf", 28),
    ):
        font = imgui.get_io().fonts.add_font_from_file_ttf(
            str(ROOT / "myogestic/assets/fonts" / filename), size
        )
        monkeypatch.setattr(_theme, attr, font)
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width, 1656)
    headers, views, cells, items = [], [], [], []
    original_header = ns["panel_header"]

    def header(title, *args, **kwargs):
        headers.append(title)
        return original_header(title, *args, **kwargs)

    monkeypatch.setitem(app._ui_fn.__globals__, "panel_header", header)
    for module in (ml_widgets, process_launcher, recording, stream_panel, simulator_controls):
        monkeypatch.setattr(module, "panel_header", header)
    monkeypatch.setattr(imgui, "begin_tab_bar", lambda *a: pytest.fail("the shell has no tabs"))
    for name in ("button", "small_button", "text_unformatted", "text_colored", "text_wrapped"):
        original = getattr(imgui, name)

        def item(*args, original=original, name=name, **kwargs):
            right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
            result = original(*args, **kwargs)
            items.append((name, str(args), imgui.get_item_rect_max().x - right))
            return result

        monkeypatch.setattr(imgui, name, item)
    for name in ("connect_ui", "model_ui", "predict_ui"):
        render = ns[name]

        def card(*args, name=name, render=render, **kwargs):
            render(*args, **kwargs)
            cells.append(
                (
                    name,
                    imgui.get_cursor_pos_y(),
                    imgui.get_window_size().y,
                    imgui.get_scroll_max_x(),
                    imgui.get_scroll_max_y(),
                )
            )

        monkeypatch.setitem(app._ui_fn.__globals__, name, card)
    for name in (
        "viewer",
        "simulator",
        "recording",
        "streams",
        "train_button",
        "training_log",
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
        imgui.begin("regression-shell", flags=imgui.WindowFlags_.no_title_bar)
        app._ui_fn(app.ctx)
        assert imgui.get_scroll_max_x() == imgui.get_scroll_max_y() == 0
        imgui.end()

    for _ in range(4):
        headers.clear()
        views.clear()
        cells.clear()
        items.clear()
        implot_frame(draw)
    assert headers == [ns["steps"].steps[step], "Simulated EMG"]
    expected = {"viewer", "simulator", "recording", "sessions", "log", "status"}
    expected |= {
        0: {"streams"},
        2: {"train_button", "training_log"},
        3: {"predict_button", "output_filter"},
    }.get(step, set())
    assert {name for name, _ in views} == expected
    record_calls = [kwargs for name, kwargs in views if name == "recording"]
    assert len(record_calls) == 1
    assert record_calls[0].get("visible", True) == (step == 1)
    assert next(kwargs for name, kwargs in views if name == "sessions") == {
        "participant": app.ctx.participant
    }
    assert all(overhang <= 1 for _, _, overhang in items), [item for item in items if item[2] > 1]
    assert all(horizontal == 0 for _, _, _, horizontal, _ in cells), cells
    if width == 2560:
        assert all(
            cursor - imgui.get_style().item_spacing.y <= height and vertical == 0
            for _, cursor, height, _, vertical in cells
        ), cells
    assert ns["layout"]._active is (ns["layout"]._wide if width == 2560 else ns["layout"]._narrow)


def test_regression_recording_preserves_pose_and_keyboard_gate(regression_app, monkeypatch):
    """A take re-syncs its simulated signal and keeps VHI's recording-session gate."""
    ns, calls = regression_app, []
    bus = SimpleNamespace(select=lambda *args: calls.append(("select", *args)))
    monkeypatch.setattr(type(ns["link"]), "ensure", lambda self: calls.append("bind") or bus)
    ns["simulator"].set(0.0)
    monkeypatch.setattr(
        ns["simulator"]._outlet, "push_sample", lambda value: calls.append(float(value[0]))
    )
    monkeypatch.setattr(ns["app"], "start_recording", lambda: calls.append("record"))
    monkeypatch.setattr(ns["app"], "stop_recording", lambda: calls.append("stop"))
    monkeypatch.setattr(
        type(ns["recording_aid"]),
        "set_recording_session",
        lambda self, enabled: calls.append(("gate", enabled)) or True,
    )
    ns["_on_gesture"](1)
    assert calls == ["bind", 1.0, ("select", "gesture", "Fist")]
    ns["app"].ctx.current_label = 0
    calls.clear()
    ns["_on_record"]()
    assert calls == ["bind", 0.0, "record", ("gate", True)]
    assert ns["simulator"].value == 0.0
    calls.clear()
    ns["_on_stop"]()
    assert calls == ["stop", ("gate", False)]


def test_regression_predict_still_pushes_continuous_aliases(regression_app, monkeypatch):
    """Prediction keeps its bus payload and never binds on the predict thread."""
    ns, pushed = regression_app, []
    values = np.linspace(-0.5, 0.9, len(ns["DOF_NAMES"]))
    bus = SimpleNamespace(push=lambda frame: pushed.append(frame) or frame)
    monkeypatch.setattr(type(ns["link"]), "bus", property(lambda self: bus))
    monkeypatch.setattr(
        type(ns["link"]), "ensure", lambda self: pytest.fail("predict must not bind")
    )
    model = SimpleNamespace(predict=lambda features: np.array([values]))
    result = ns["predict"](model, np.ones(3))
    assert result == {"dof": dict(zip(ns["DOF_NAMES"], values, strict=True))}
    assert pushed == [result["dof"]]


@pytest.mark.parametrize("step", range(4))
@pytest.mark.parametrize("state", ["idle", "recording", "predicting"])
def test_regression_simulator_is_available_on_each_step(
    regression_app,
    monkeypatch,
    implot_frame,
    step,
    state,
):
    """Preview changes only the signal; the recording gesture remains authoritative."""
    from imgui_bundle import imgui

    ns = regression_app
    ns["steps"].active = step
    ns["app"].ctx.state = state
    ns["app"].ctx.recording = state == "recording"
    ns["simulator"].set(0.0)
    samples, chips = [], []
    monkeypatch.setattr(ns["simulator"]._outlet, "push_sample", lambda value: samples.append(value))
    original_button = imgui.small_button

    def click(label):
        result = original_button(label)
        if "##preset_" in label:
            disabled = bool(imgui.get_item_flags() & imgui.ItemFlags_.disabled)
            chips.append((label.split("##")[0], disabled))
            return label.startswith("Fist##") and not disabled
        return result

    monkeypatch.setattr(imgui, "small_button", click)
    implot_frame(lambda: ns["app"]._ui_fn(ns["app"].ctx))
    assert chips == [("Rest", state == "recording"), ("Fist", state == "recording")]
    assert ns["simulator"].value == (0.0 if state == "recording" else 1.0)
    assert len(samples) == (0 if state == "recording" else 1)
    assert ns["app"].ctx.current_label == -1
    monkeypatch.setattr(type(ns["link"]), "ensure", lambda self: None)
    ns["_on_gesture"](1)
    assert ns["simulator"].value == 1.0


def test_regression_connect_launches_each_configured_process(
    regression_app, monkeypatch, implot_frame
):
    """Connect retains both launcher actions and reports an unlaunchable target."""
    from imgui_bundle import imgui

    ns, launches = regression_app, []
    original_button = imgui.small_button

    def click(label):
        result = original_button(label)
        return True if "##launch_" in label else result

    def launch(self, name):
        launches.append(name)
        raise FileNotFoundError("Executable not found")

    monkeypatch.setattr(imgui, "small_button", click)
    monkeypatch.setattr(type(ns["processes"]), "launch", launch)
    implot_frame(lambda: ns["connect_ui"](ns["app"].ctx))
    assert launches == [name for name, _ in ns["PROCESSES"]]
    assert ns["launch_errors"] == dict.fromkeys(launches, "Executable not found")
