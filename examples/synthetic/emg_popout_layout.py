"""Pop-out windows demo: the 32-ch multi-model experiment from
``emg_32ch_multi_model.py``, with every block registered via ``app.popout(...)``
so panels tear off into floating ImGui windows — real OS windows with
multi-viewport on.

Use the icon in a card header to open a floating panel, or choose any of the
nine panels from the active step's pop-out menu. Close a window to return to
the shell; the model training log can stay open while you change steps.

Run with:
    uv run python examples/synthetic/emg_popout_layout.py

Experimental - see the README "Status" note for macOS caveats.
"""

import re
import sys
import threading
import time as _time
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import torch
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui
from imgui_bundle import portable_file_dialogs as pfd
from myoverse.transforms import MAV, RMS, WaveformLength

from myogestic import App, Context, Fr, Grid, Layout, Px, Stream, TrainingData
from myogestic.controls import ControlLink, load_control_map
from myogestic.ml import Pipeline, load_pickle, save_pickle
from myogestic.ml.widgets import PredictButton, TrainButton, TrainingLog
from myogestic.recipes.estimators import (
    catboost_classifier,
    constant_classifier,
    sklearn_classifier,
    sklearn_extra_trees_classifier,
    sklearn_logistic_classifier,
)
from myogestic.remote import RemoteTarget
from myogestic.session import iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.vhi import virtual_hand
from myogestic.widgets import (
    AppHeader,
    FeatureSelector,
    ParticipantPanel,
    PostProcessor,
    PredictionLabel,
    ProcessLauncher,
    RecordingControls,
    SessionManager,
    SignalViewer,
    SimulatorControls,
    StatusBar,
    StepBar,
    StreamPanel,
)
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    SUCCESS,
    WARNING,
    fit_text,
    mono_text,
    muted,
    panel_header,
    primary_button,
    tinted_row,
    ui_px,
)
from myogestic.widgets.panels.log_box import render_log, render_log_buttons, render_log_popout

N_CHANNELS = 32
CLASSES = ["Rest", "Fist", "Pinch", "Open"]
CTRL_VALUES = [0.0, 1.0, 2.0, 3.0]
WINDOW_MS = 250
HOP_MS = 100

vhi = virtual_hand()
output_filter = PostProcessor(hz=32)

# Which of *this example's* output names go to which of VHI's controls. Parsing the file
# needs no VHI; learning what its addresses mean does — see `link.ensure`.
CONTROL_FILE = Path(__file__).resolve().parent.parent / "controls" / "popout_layout.toml"
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

# Our aliases, taken from the file, so renaming one there needs no edit here.
POSE_ALIASES = tuple(CONTROL_MAP.bindings)

# Per-class poses in control values: +1 is the direction the alias' target names, 0 is
# rest. The fist abducts the thumb — this used to write that channel as 0, but recorded
# VHI sessions have it at full excursion.
HAND_POSES: dict[int, dict[str, float]] = {
    0: {},  # Rest
    1: dict.fromkeys(POSE_ALIASES, 1.0),  # Fist
    2: {  # Pinch
        "thumb_curl": 0.7,
        "thumb_spread": 0.6,
        "index_curl": 0.8,
        "middle_curl": 0.6,
    },
    3: dict.fromkeys(POSE_ALIASES, -0.5),  # Open: extended past rest
}

vhi_control = vhi.control_client()

rms_transform = RMS(window_size=32)
mav_transform = MAV(window_size=32)
wl_transform = WaveformLength(window_size=32)


def extract_features(emg: np.ndarray) -> np.ndarray:
    tensor = torch.from_numpy(emg).float()
    return np.concatenate(
        [
            rms_transform(tensor).numpy().flatten(),
            mav_transform(tensor).numpy().flatten(),
            wl_transform(tensor).numpy().flatten(),
        ]
    )


PROCESSES = [
    (
        "EMG Generator 32ch",
        [
            sys.executable,
            "-m",
            "myogestic.tools.emg_generator",
            "--name",
            "TestEMG32",
            "--channels",
            str(N_CHANNELS),
            "--classes",
            str(len(CLASSES)),
            "--fs",
            "2048",
            "--control",
            "EMG_Control",
        ],
    ),
    # A [(name, argv)] list, splatted so the generator and VHI share one launcher.
    # `launchable`, never `launcher`: a VHI that cannot be launched must not stop this app
    # from opening.
    *vhi.launchable(),
]

# docking=True enables ImGui multi-viewport so each app.popout(...) panel
# becomes a tearable / dockable window.
app = App("EMG 32ch Popout", docking=True, require_participant=True)
app.streams(Stream("emg", source=LSLSource("TestEMG32"), window_ms=WINDOW_MS, buffer_ms=60000))
pipeline = Pipeline(app)
pipeline.save_model = save_pickle
pipeline.load_model = load_pickle

# Nothing resolves until `link.ensure()` finds VHI up: the map declares no kinds or ranges,
# so the target reads them from VHI's manifest and refuses a VHI it cannot fully drive.
link = ControlLink(
    CONTROL_MAP,
    [RemoteTarget(client=vhi_control, interface=vhi)],
    ctx=app.ctx,
    smoothing=output_filter,
    hz=32,
)

MODELS_DIR = Path("models")


@pipeline.extract
def extract(windows) -> np.ndarray:
    return extract_features(windows["emg"])


# --- Model recipes ----------------------------------------------------------

MODEL_RECIPES: dict[str, Callable[[], Any]] = {
    "CatBoost": lambda: catboost_classifier(iterations=150),
    "Random Forest": lambda: sklearn_classifier(n_estimators=200, random_state=0, n_jobs=-1),
    "Extra Trees": lambda: sklearn_extra_trees_classifier(
        n_estimators=300, random_state=0, n_jobs=-1
    ),
    "Logistic Regression": lambda: sklearn_logistic_classifier(max_iter=1000),
    "Dummy Constant": lambda: constant_classifier(0),
}
MODEL_NAMES = list(MODEL_RECIPES)
selected_model_idx = 0
_load_dialog: object | None = None


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "model"


def _list_saved() -> list[Path]:
    if not MODELS_DIR.is_dir():
        return []
    return sorted(MODELS_DIR.glob("*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)


@pipeline.train
def train(data: TrainingData):
    log = pipeline.train_log
    log.clear()
    if data.is_empty:
        raise ValueError("No sessions selected.")
    if len(data.classes) < 2:
        raise ValueError("Need ≥2 active classes.")
    X, y = [], []
    for window, _ts, ci in iter_labeled_windows(
        data.paths, "emg", WINDOW_MS, HOP_MS, classes=data.classes
    ):
        X.append(extract_features(window))
        y.append(ci)
    if len(X) < 2:
        raise ValueError(f"Need at least 2 windows, got {len(X)}")
    X = np.stack(X)
    y = np.array(y)

    model_name = MODEL_NAMES[selected_model_idx]
    log.append(f"Model: {model_name} · X={X.shape} · classes={sorted(set(y))}")
    rng = np.random.default_rng(0)
    perm = rng.permutation(len(X))
    cut = max(1, int(0.8 * len(X)))
    tr, te = perm[:cut], perm[cut:]
    model = MODEL_RECIPES[model_name]()
    model.fit(X[tr], y[tr])
    if len(te) and hasattr(model, "score"):
        log.append(f"Held-out accuracy ({len(te)}): {model.score(X[te], y[te]):.2%}")
    return model


@pipeline.predict
def predict(model, features):
    x = features.reshape(1, -1)
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x)[0]
        class_idx = int(np.argmax(proba))
    else:
        proba = None
        class_idx = int(model.predict(x)[0])
    # `link.bus`, never `link.ensure()`: nothing resolved yet means nothing to command,
    # and asking VHI what it exports blocks on an RPC, which this thread must not do.
    if link.bus is None:
        return {"class": class_idx, "proba": proba, "hand": {}}
    pose = HAND_POSES.get(class_idx, HAND_POSES[0])
    hand = link.bus.push({**dict.fromkeys(POSE_ALIASES, 0.0), **pose})
    return {"class": class_idx, "proba": proba, "hand": hand}


# The fixed MyoVerse feature stack is also shown in Train, without changing what
# existing models receive. The chips are read-only because these recipes use all three.
features = FeatureSelector(
    {"RMS": lambda emg: rms_transform(torch.from_numpy(emg).float()).numpy().flatten(),
     "MAV": lambda emg: mav_transform(torch.from_numpy(emg).float()).numpy().flatten(),
     "WL": lambda emg: wl_transform(torch.from_numpy(emg).float()).numpy().flatten()},
    show_header=False,
)

layout = Layout(
    wide=Grid.areas(
        """
        header    header
        signal    step
        signal    sessions
        simulator sessions
        log       sessions
        status    status
        """,
        row_height=[Px(52), Fr(4), Fr(1), Px(76), Px(110), Px(26)],
        col_width=[Fr(1), Px(400)],
        bare=("header", "status"),
    ),
    narrow=Grid.areas(
        """
        header
        signal
        simulator
        step
        sessions
        log
        status
        """,
        row_height=[Px(52), Fr(2), Px(76), Fr(3), Fr(1.5), Px(110), Px(26)],
        bare=("header", "status"),
    ),
    breakpoint=Px(1100),
)
steps = StepBar(["Connect", "Record", "Train", "Predict"], widget_id="emg_popout_layout_steps")
participant = ParticipantPanel()
header = AppHeader("EMG · pop-out panels", steps=steps, participant=participant)
status = StatusBar("emg", pipeline=pipeline)
viewer = SignalViewer("emg", selectable=True, show_connect=False, show_title=False)
simulator = SimulatorControls(list(zip(CLASSES, CTRL_VALUES, strict=True)))
processes = ProcessLauncher(PROCESSES)
streams = StreamPanel()
sessions = SessionManager("sessions", class_names=CLASSES)
train_button = TrainButton(pipeline, size=(-1, 0))
predict_button = PredictButton(pipeline, size=(-1, 0))
_MODEL_WIDGET_ID = "ml_popout"
training_log = TrainingLog(pipeline, height=50, widget_id=_MODEL_WIDGET_ID)
prediction = PredictionLabel(pipeline, CLASSES)
_log_popout_open = False
connection = {"busy": False}
launch_errors: dict[str, str] = {}


def _on_gesture(i: int) -> None:
    link.ensure()
    simulator.set(CTRL_VALUES[i])


def _on_record() -> None:
    link.ensure()
    # Previewing another signal must not change the gesture captured in this take.
    if 0 <= app.ctx.current_label < len(CTRL_VALUES):
        simulator.set(CTRL_VALUES[app.ctx.current_label])
    app.start_recording()


recording = RecordingControls(
    CLASSES, on_record=_on_record, on_stop=app.stop_recording,
    on_gesture=_on_gesture, show_header=False,
)


def _panel_visible(title: str) -> bool:
    """Read visibility from the runner, including windows closed with their X."""
    params = getattr(app, "_runner_params", None)
    return params is not None and any(
        window.label == title and window.is_visible
        for window in params.docking_params.dockable_windows
    )


def _show_panel(title: str) -> None:
    """Open an already registered window, leaving the central shell in place."""
    params = getattr(app, "_runner_params", None)
    if params is not None:
        for window in params.docking_params.dockable_windows:
            if window.label == title:
                window.dock_space_name = ""
                window.is_visible = True
                window.focus_window_at_next_frame = True
                break


def _card_header(
    title: str, *, panel: str | None = None, status: imgui.ImVec4 | None = None,
    training: bool = False, clear_log: bool = False,
) -> None:
    """Keep the panel chooser and training-log pop-out on the header line."""
    global _log_popout_open
    style = imgui.get_style()
    icon = fa.ICON_FA_UP_RIGHT_FROM_SQUARE
    width = imgui.calc_text_size(icon).x + 2 * style.frame_padding.x
    log_icon = (fa.ICON_FA_DOWN_LEFT_AND_UP_RIGHT_TO_CENTER if _log_popout_open
                else fa.ICON_FA_UP_RIGHT_AND_DOWN_LEFT_FROM_CENTER)
    log_width = imgui.calc_text_size(log_icon).x + 2 * style.frame_padding.x
    clear_width = imgui.calc_text_size(fa.ICON_FA_BROOM).x + 2 * style.frame_padding.x
    reserve = width + style.item_spacing.x
    if clear_log:
        reserve += clear_width + style.item_spacing.x
    if training:
        reserve += log_width + style.item_spacing.x
    right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
    panel_header(title, reserve=reserve, status=status)
    imgui.same_line()
    imgui.set_cursor_pos_x(right - reserve + style.item_spacing.x)
    if imgui.small_button(f"{icon}##panels_{title}"):
        if panel is not None:
            _show_panel(panel)
        else:
            imgui.open_popup("detachable_panels")
    imgui.set_item_tooltip(f"Open {panel} in its own window" if panel else "Open a panel in its own window")
    if training:
        imgui.same_line()
        imgui.set_cursor_pos_x(right - log_width)
        _log_popout_open = render_log_buttons(_MODEL_WIDGET_ID, popped_out=_log_popout_open)
    if clear_log:
        imgui.same_line()
        imgui.set_cursor_pos_x(right - clear_width)
        if imgui.small_button(f"{fa.ICON_FA_BROOM}##clear_log"):
            app.ctx.logs.clear()
        imgui.set_item_tooltip("Clear the log")
    if panel is None and imgui.begin_popup("detachable_panels"):
        for name, *_ in app._popout_specs:
            if imgui.selectable(name, _panel_visible(name))[0]:
                _show_panel(name)
        imgui.end_popup()


def _connect() -> None:
    """Resolve the synthetic stream off the render thread, one attempt at a time."""
    if connection["busy"]:
        return
    connection["busy"] = True

    def connect() -> None:
        try:
            app.ctx.streams["emg"].reconnect()
        finally:
            connection["busy"] = False

    threading.Thread(target=connect, daemon=True).start()


def connect_ui(ctx: Context) -> None:
    """Launch the generator or hand and connect the named EMG stream."""
    for name, _ in PROCESSES:
        running = processes.running(name)
        error = launch_errors.get(name, "")
        tone = SUCCESS if running else DANGER if error else IDLE
        style = imgui.get_style()
        icon = fa.ICON_FA_STOP if running else fa.ICON_FA_PLAY
        width = imgui.calc_text_size(icon).x + 2 * style.frame_padding.x
        imgui.text_colored(muted(), name)
        with tinted_row(tone) as room:
            left = imgui.get_cursor_pos_x()
            imgui.align_text_to_frame_padding()
            detail = "Running" if running else "Launch failed" if error else "Not running"
            imgui.text_unformatted(fit_text(detail, room - width - style.item_spacing.x))
            imgui.set_item_tooltip(error or name)
            imgui.same_line()
            imgui.set_cursor_pos_x(left + room - width)
            imgui.begin_disabled(ctx.state != "idle")
            clicked = imgui.small_button(f"{icon}##launch_{name}")
            imgui.end_disabled()
            imgui.set_item_tooltip(f"Stop {name}" if running else f"Launch {name}")
            if clicked:
                if running:
                    processes.stop(name)
                else:
                    try:
                        processes.launch(name)
                        launch_errors[name] = ""
                    except Exception as exc:
                        launch_errors[name] = str(exc)
                        ctx.log(f"{name} launch failed: {exc}")
    imgui.spacing()
    imgui.text_colored(muted(), "EMG stream · TestEMG32")
    stream = ctx.streams["emg"]
    connected = stream.status == "connected" and stream.info is not None
    busy = connection["busy"]
    tone = SUCCESS if connected else WARNING if busy else DANGER if stream.last_error else IDLE
    with tinted_row(tone):
        imgui.text_unformatted("Connected" if connected else "Connecting…" if busy else
                               "Connection failed" if stream.last_error else "Not connected")
    if stream.last_error and not busy and not connected:
        _caption(stream.last_error)
    imgui.begin_disabled(ctx.state != "idle" or busy)
    if primary_button("Reconnect" if connected else "Retry" if stream.last_error else "Connect",
                      size=(-1, 0)):
        _connect()
    imgui.end_disabled()
    _caption("Return to idle before changing the generator or connection." if ctx.state != "idle"
             else "Launch the generator, then connect to see the signal.")


def _caption(text: str) -> None:
    imgui.push_style_color(imgui.Col_.text, muted())
    imgui.text_wrapped(text)
    imgui.pop_style_color()


def model_ui() -> None:
    """Choose the estimator, train and save or load the unchanged model files."""
    global selected_model_idx, _load_dialog
    imgui.text_colored(muted(), "Estimator")
    imgui.set_next_item_width(-1)
    _, selected_model_idx = imgui.combo("##model_sel", selected_model_idx, MODEL_NAMES)
    training = app.ctx.state == "training"
    failed = app.ctx.status_message.startswith("Training failed:")
    tone = WARNING if training else DANGER if failed else SUCCESS if pipeline.model is not None else IDLE
    with tinted_row(tone):
        imgui.text_unformatted("Training…" if training else "Training failed" if failed else
                               "Model ready" if pipeline.model is not None else "No model yet")
    if failed:
        imgui.set_item_tooltip(app.ctx.status_message)
    imgui.text_colored(muted(), "Features")
    imgui.begin_disabled()
    features.ui()
    imgui.end_disabled()
    _caption("Fixed MyoVerse features for this example.")
    train_button.ui()
    if _log_popout_open:
        _caption("Training log open in its own window.")
    else:
        training_log.ui()
    can_save = pipeline.model is not None
    imgui.begin_disabled(not can_save)
    save = imgui.small_button(f"{fa.ICON_FA_FLOPPY_DISK}##save_model")
    imgui.end_disabled()
    imgui.set_item_tooltip("Save the model" if can_save else "Train or load a model to save it")
    if save and can_save:
        MODELS_DIR.mkdir(exist_ok=True)
        slug = _slug(MODEL_NAMES[selected_model_idx])
        ts = _time.strftime("%Y%m%d_%H%M%S")
        path = MODELS_DIR / f"{slug}_{ts}.joblib"
        save_pickle(pipeline.model, str(path))
        app.ctx.log(f"Model saved → {path}")
    imgui.same_line()
    if imgui.small_button(f"{fa.ICON_FA_FOLDER_OPEN}##load_model"):
        MODELS_DIR.mkdir(exist_ok=True)
        _load_dialog = pfd.open_file("Load model", str(MODELS_DIR), ["Model", "*.joblib"])
    imgui.set_item_tooltip("Load a model…")
    imgui.same_line()
    mono_text(f"{len(_list_saved())} saved", muted())
    if not can_save:
        _caption("Train or load a model to save it.")


def _poll_model_dialog() -> None:
    """Finish an already opened file dialog even after changing steps."""
    global _load_dialog
    if _load_dialog is not None and _load_dialog.ready():  # type: ignore
        result = _load_dialog.result()  # type: ignore
        _load_dialog = None
        if result:
            try:
                pipeline.model = load_pickle(result[0])
                app.ctx.log(f"Model loaded ← {result[0]}")
            except Exception as exc:
                app.ctx.log(f"Load failed: {exc}")


def predict_ui() -> None:
    """Tune smoothing and inspect the predicted gesture and probabilities."""
    output_filter.ui()
    imgui.spacing()
    prediction.ui()
    predict_button.ui()


def signal_ui() -> None:
    _card_header("Signal", panel="Signal")
    viewer.ui(app.ctx)


def log_ui() -> None:
    _card_header("Activity log", panel="Log", clear_log=True)
    render_log("activity", app.ctx.logs or ["No events yet — connect to begin."])


def _step_done(ctx: Context) -> list[bool]:
    """Completion reflects connection, participant takes, model and prediction."""
    stream = ctx.streams.get("emg")
    return [
        stream is not None and stream.status == "connected" and stream.info is not None,
        bool(ctx.participant)
        and any(Path("sessions", ctx.participant).glob(f"{ctx.participant}_*")),
        pipeline.model is not None,
        ctx.state == "predicting",
    ]


@app.ui
def demo_ui(ctx: Context) -> None:
    """Keep the shell visible while any of its original panels floats separately."""
    global _log_popout_open
    _poll_model_dialog()
    # This belongs to the shell, so changing steps cannot strand a floating log.
    if _log_popout_open:
        _log_popout_open = render_log_popout(
            _MODEL_WIDGET_ID, pipeline.train_log, title="Model training log",
        )
    done = _step_done(ctx)
    with layout["header"]:
        active = header.ui(ctx, done)
    padding = imgui.get_style().window_padding
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding.x, ui_px(4)))
    # A detached recording card owns its tick; otherwise keep the timer alive off-step.
    detached_recording = _panel_visible("Recording")
    if active != 1 and not detached_recording:
        recording.ui(ctx, visible=False)
    with layout["sessions"]:
        pipeline.training_data = sessions.ui(participant=ctx.participant)
    with layout["step"]:
        stream = ctx.streams.get("emg")
        tone = SUCCESS if done[0] else DANGER if stream is not None and stream.last_error else IDLE
        _card_header(steps.steps[active], status=tone if active == 0 else None, training=active == 2)
        if active == 0:
            connect_ui(ctx)
        elif active == 1:
            if detached_recording:
                _caption("Recording controls are open in their own window. Close it to return here.")
            else:
                recording.ui(ctx)
        elif active == 2:
            model_ui()
        else:
            predict_ui()
    with layout["signal"]:
        signal_ui()
    with layout["simulator"]:
        simulator.ui(ctx)
    with layout["log"]:
        log_ui()
    imgui.pop_style_var()
    with layout["status"]:
        status.ui(ctx)


def _recording_panel() -> None:
    panel_header("Record")
    recording.ui(app.ctx)


def _training_panel() -> None:
    _card_header("Train", training=True)
    model_ui()


def _sessions_panel() -> None:
    pipeline.training_data = sessions.ui(participant=app.ctx.participant)


# Register before app.run so every original panel remains available to Hello ImGui.
# Start closed: the shell is the default view, and its header actions open these windows.
for _title, _draw in (
    ("Signal", signal_ui),
    ("Streams", lambda: streams.ui(app.ctx)),
    ("Log", log_ui),
    ("Processes", processes.ui),
    ("Recording", _recording_panel),
    ("Model", _training_panel),
    ("Post-processing", output_filter.ui),
    ("Sessions", _sessions_panel),
    ("Prediction", prediction.ui),
):
    app.popout(_title, _draw, default_open=False, can_be_closed=True, remember_is_visible=False)


def main() -> None:
    try:
        app.run()
    finally:
        # Rest the hand and make that frame land before the outlet's thread dies.
        link.stop()
        vhi_control.stop()


if __name__ == "__main__":
    main()
