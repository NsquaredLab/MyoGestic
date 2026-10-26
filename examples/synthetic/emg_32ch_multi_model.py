"""Multi-model classification demo: 32-ch fake EMG → MyoVerse features →
selectable classifier → VHI hand pose.

Run with:
    uv run python examples/synthetic/emg_32ch_multi_model.py

Workflow:
    1. Connect: launch "EMG Generator 32ch", then connect the EMG stream.
    2. Click Rest / Fist / Pinch / Open to switch the generator's class
       (signal pattern + label sample).
    3. Record one trial per class.
    4. In Train, choose CatBoost / Random Forest / Extra Trees /
       Logistic Regression / Dummy Constant.
    5. Click Train → Predict — VHI hand follows the predicted class.
    6. Use Simulated EMG on any step to try all four classes while predicting.
    7. Use a card's pop-out icon to open panels in their own windows.

Mirrors `emg_classification.py` but expands to 32 channels and 4 classes, and lets
you compare classifiers side-by-side without editing the file.

Which hand controls the poses drive is declared in `examples/controls/multi_model.toml`
— our own alias on the left, the address VHI exports on the right.
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
output_filter = PostProcessor(hz=32, compact=True)

# Which of this example's outputs drive which of VHI's controls. The left side of the
# file is ours and the right side is VHI's, so nothing below hard-codes what a control
# means — the addresses are resolved against a live VHI by `link.ensure()`.
CONTROL_FILE = Path(__file__).resolve().parent.parent / "controls" / "multi_model.toml"
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

#: Our aliases in file order. Poses that move everything (Fist, Open) are built from
#: this rather than from a second list that could drift out of step with the TOML.
POSE_ALIASES = tuple(CONTROL_MAP.bindings)

vhi_control = vhi.control_client()

# Per-class hand poses, in control values keyed by *our* aliases: +1 is the
# direction the alias names, 0 is rest, and an alias left out of a pose rests.
# The target turns them into whatever this VHI's wire wants, so no channel index
# or sign flip appears here.
#
# `thumb_spread` used to be written as 0 in a fist. Recorded VHI sessions have it
# at exactly -1.0 on the wire — full abduction — so a fist abducts the thumb
# rather than leaving it neutral.
HAND_POSES: dict[int, dict[str, float]] = {
    0: {},  # Rest — every alias at 0
    1: dict.fromkeys(POSE_ALIASES, 1.0),  # Fist: everything flexed, thumb abducted
    2: {  # Pinch
        "thumb_curl": 0.7,
        "thumb_spread": 0.6,
        "index_curl": 0.8,
        "middle_curl": 0.6,
    },
    3: dict.fromkeys(POSE_ALIASES, -0.5),  # Open: extended past rest
}

rms_transform = RMS(window_size=32)
mav_transform = MAV(window_size=32)
wl_transform = WaveformLength(window_size=32)

def extract_features(emg: np.ndarray) -> np.ndarray:
    """RMS + MAV + WL on a (n_channels, n_samples) window."""
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
    # An unavailable launcher must not prevent startup; a running hand needs no
    # button, and the reason is logged either way.
    *vhi.launchable(),
]

app = App("EMG · 32 ch multi-model", docking=True)
app.streams(Stream("emg", source=LSLSource("TestEMG32"), window_ms=WINDOW_MS, buffer_ms=60000))
pipeline = Pipeline(app)
# Wire generic save/load so save_model_button / load_model_button work, and
# so the example's custom picker can call them through the pipeline too.
pipeline.save_model = save_pickle
pipeline.load_model = load_pickle

# `link.bus` stays None until `link.ensure()` succeeds. The link and its target own the
# wire once bound, and that matters more than it looks: VHI's continuous inlet takes
# control values, and `RemoteTarget` negotiates the space at bind time and refuses a VHI it
# cannot fully drive rather than guessing. No hand and no stream is named here — the
# target looks this file's addresses up in VHI's manifest and publishes one stream per
# address it drives, named for that address.
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


# --- Model recipes (kept in the example, NOT in the library) ---------------

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


_load_dialog: object | None = None  # in-flight pfd.open_file future, None if idle

# The training log can stay open while another workflow step is active.
_MODEL_WIDGET_ID = "ml_multi"
_popout_open = False

train_button = TrainButton(pipeline, size=(-1, 0))
predict_button = PredictButton(pipeline, size=(-1, 0))
training_log = TrainingLog(pipeline, height=80.0, widget_id=_MODEL_WIDGET_ID)

def _slug(name: str) -> str:
    """Filesystem-safe recipe slug — strip everything outside [A-Za-z0-9_-]."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "model"

def _list_saved_models() -> list[Path]:
    """Saved models, newest first. Empty if the directory does not exist yet."""
    if not MODELS_DIR.is_dir():
        return []
    return sorted(MODELS_DIR.glob("*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)

def _save_current() -> Path | None:
    """Save `pipeline.model` under `models/<recipe>_<timestamp>.joblib`."""
    if pipeline.model is None:
        return None
    MODELS_DIR.mkdir(exist_ok=True)
    slug = _slug(MODEL_NAMES[selected_model_idx])
    ts = _time.strftime("%Y%m%d_%H%M%S")
    path = MODELS_DIR / f"{slug}_{ts}.joblib"
    save_pickle(pipeline.model, str(path))
    return path

def model_actions_ui() -> None:
    """Save with an automatic name, open a model, or pop out the training log."""
    global _load_dialog, _popout_open
    imgui.begin_disabled(pipeline.model is None)
    if imgui.small_button(f"{fa.ICON_FA_FLOPPY_DISK}##save_model"):
        path = _save_current()
        if path is not None:
            app.ctx.status_message = f"Saved → {path.name}"
            app.ctx.log(f"Model saved → {path}")
    imgui.end_disabled()
    imgui.set_item_tooltip("Save model with an automatic recipe and timestamp name")
    imgui.same_line()
    if imgui.small_button(f"{fa.ICON_FA_FOLDER_OPEN}##load_model"):
        # The native picker needs its initial directory to exist.
        MODELS_DIR.mkdir(exist_ok=True)
        _load_dialog = pfd.open_file("Load model", str(MODELS_DIR), ["Model", "*.joblib"])
    imgui.set_item_tooltip(f"Load model · {len(_list_saved_models())} saved in {MODELS_DIR}")
    imgui.same_line()
    _popout_open = render_log_buttons(_MODEL_WIDGET_ID, popped_out=_popout_open)

def model_ui() -> None:
    """Choose a classifier and train it on the selected takes."""
    global selected_model_idx
    imgui.text_colored(muted(), "Classifier")
    imgui.set_next_item_width(-1)
    _, selected_model_idx = imgui.combo("##model_selector", selected_model_idx, MODEL_NAMES)
    with tinted_row(SUCCESS if pipeline.model is not None else IDLE):
        imgui.text_wrapped("Model ready" if pipeline.model is not None else
                           "No model yet — train or load to enable Save.")
    imgui.text_colored(muted(), "Features")
    mono_text("RMS · MAV · WL", muted())
    imgui.spacing()
    train_button.ui()
    if _popout_open:
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped("Training log is open in a separate window.")
        imgui.pop_style_color()
    else:
        training_log.ui()

def _poll_model_ui() -> None:
    """Keep the open log and model picker alive when the Train step is hidden."""
    global _load_dialog, _popout_open
    if _popout_open:
        _popout_open = render_log_popout(
            _MODEL_WIDGET_ID, pipeline.train_log, title="Model training log",
        )
    # Poll the in-flight dialog (if any). pfd's open_file returns list[str];
    # cancel produces an empty list.
    if _load_dialog is not None and _load_dialog.ready():  # type: ignore
        result = _load_dialog.result()  # type: ignore
        _load_dialog = None
        if result:
            path = Path(result[0])
            try:
                pipeline.model = load_pickle(str(path))
                app.ctx.status_message = f"Loaded ← {path.name}"
                app.ctx.log(f"Model loaded ← {path}")
            except Exception as e:
                app.ctx.status_message = f"Load failed: {e}"
                app.ctx.log(f"Model load failed: {e}")


# --- Train / predict --------------------------------------------------------


@pipeline.train
def train(data: TrainingData):
    """Train the currently-selected model on labeled windows from the
    selected sessions. Active class chips filter which trials get used."""
    log = pipeline.train_log
    log.clear()

    if data.is_empty:
        raise ValueError("No sessions selected. Tick at least one in the list.")
    if len(data.classes) < 2:
        active = sorted(data.classes)
        names = [CLASSES[i] if 0 <= i < len(CLASSES) else f"c{i}" for i in active]
        raise ValueError(
            f"Need ≥2 active classes — got {len(active)} ({names}). Toggle more class chips on."
        )

    all_X: list[np.ndarray] = []
    all_y: list[int] = []
    for window, _ts, ci in iter_labeled_windows(
        data.paths,
        "emg",
        WINDOW_MS,
        HOP_MS,
        classes=data.classes,
    ):
        all_X.append(extract_features(window))
        all_y.append(ci)

    if len(all_X) < 2:
        raise ValueError(f"Need at least 2 windows, got {len(all_X)}")
    X = np.stack(all_X)
    y = np.array(all_y)
    if len(np.unique(y)) < 2:
        raise ValueError(f"Need at least 2 classes, got {len(np.unique(y))}")

    model_name = MODEL_NAMES[selected_model_idx]
    log.append(f"Model: {model_name}")
    log.append(f"X: {X.shape}, y: {y.shape}, classes: {sorted(set(y))}")

    # Held-out 80/20 split — comparing classifiers on training accuracy
    # is misleading (any tree-ensemble overfits to ~100%); a hold-out
    # score is the cheapest meaningful signal for "is this recipe better".
    rng = np.random.default_rng(0)
    perm = rng.permutation(len(X))
    cut = max(1, int(0.8 * len(X)))
    tr, te = perm[:cut], perm[cut:]
    model = MODEL_RECIPES[model_name]()
    model.fit(X[tr], y[tr])

    if len(te) and hasattr(model, "score"):
        try:
            log.append(f"Held-out accuracy ({len(te)} samples): {model.score(X[te], y[te]):.2%}")
        except Exception as e:
            log.append(f"score() failed: {e}")
    return model


@pipeline.predict
def predict(model, features):
    """Classify → look up hand pose → smooth → push to VHI.

    Some recipes (e.g. constant_classifier in degenerate cases) lack
    predict_proba, so we branch on availability instead of requiring it.
    """
    x = features.reshape(1, -1)
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x)[0]
        class_idx = int(np.argmax(proba))
    else:
        proba = None
        class_idx = int(model.predict(x)[0])

    # `link.bus`, never `link.ensure()`: binding blocks on an RPC, which this thread
    # must not do.
    if link.bus is None:
        return {"class": class_idx, "proba": proba}  # nothing resolved yet, nothing to command

    # Control values in; the bus rests every alias the pose omits, sanitises and
    # smooths, and the target places them on the channels this VHI negotiated.
    values = link.bus.push(HAND_POSES.get(class_idx, HAND_POSES[0]))
    return {"class": class_idx, "proba": proba, "hand": values}


layout = Layout(
    wide=Grid.areas(
        """
        header   header
        signal   step
        signal   sessions
        simulator sessions
        log      sessions
        status   status
        """,
        row_height=[Px(52), Fr(3), Fr(1), Px(76), Px(110), Px(26)],
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
steps = StepBar(["Connect", "Record", "Train", "Predict"], widget_id="emg_32ch_multi_model_steps")
participant = ParticipantPanel()
header = AppHeader("EMG · 32 ch multi-model", steps=steps, participant=participant)
status = StatusBar("emg", pipeline=pipeline)

def _on_gesture(i: int) -> None:
    link.ensure()
    simulator.set(CTRL_VALUES[i])

def _on_record() -> None:
    link.ensure()
    # A simulator preview may differ from the gesture selected for this take.
    if 0 <= app.ctx.current_label < len(CTRL_VALUES):
        simulator.set(CTRL_VALUES[app.ctx.current_label])
    app.start_recording()


# The Connect step owns acquisition; signal and simulator stay visible on every step.
viewer = SignalViewer("emg", selectable=True, show_connect=False, show_title=False)
simulator = SimulatorControls(list(zip(CLASSES, CTRL_VALUES, strict=True)))
processes = ProcessLauncher(PROCESSES)
streams = StreamPanel()
recording = RecordingControls(
    CLASSES,
    on_record=_on_record,
    on_stop=app.stop_recording,
    on_gesture=_on_gesture,
    show_header=False,
)
sessions = SessionManager("sessions", class_names=CLASSES)
prediction = PredictionLabel(pipeline, CLASSES)
connection = {"busy": False}
launch_errors: dict[str, str] = {}


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
    """Keep window, model and log actions on one icon-only header line."""
    style = imgui.get_style()
    icon = fa.ICON_FA_UP_RIGHT_FROM_SQUARE
    icons = [icon]
    if training:
        log_icon = (fa.ICON_FA_DOWN_LEFT_AND_UP_RIGHT_TO_CENTER if _popout_open
                    else fa.ICON_FA_UP_RIGHT_AND_DOWN_LEFT_FROM_CENTER)
        icons += [fa.ICON_FA_FLOPPY_DISK, fa.ICON_FA_FOLDER_OPEN, log_icon]
    if clear_log:
        icons.append(fa.ICON_FA_BROOM)
    actions_width = sum(imgui.calc_text_size(action).x + 2 * style.frame_padding.x
                        for action in icons) + (len(icons) - 1) * style.item_spacing.x
    right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
    panel_header(title, reserve=actions_width + style.item_spacing.x, status=status)
    imgui.same_line()
    imgui.set_cursor_pos_x(right - actions_width)
    if imgui.small_button(f"{icon}##panels_{title}"):
        if panel is not None:
            _show_panel(panel)
        else:
            imgui.open_popup("detachable_panels")
    imgui.set_item_tooltip(f"Open {panel} in its own window" if panel else
                           "Open a panel in its own window")
    if training:
        imgui.same_line()
        model_actions_ui()
    if clear_log:
        imgui.same_line()
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

def _process_ui(ctx: Context, name: str) -> None:
    """Show a process's status and launch action."""
    running = processes.running(name)
    error = launch_errors.get(name, "")
    tone = SUCCESS if running else DANGER if error else IDLE
    style = imgui.get_style()
    icon = fa.ICON_FA_STOP if running else fa.ICON_FA_PLAY
    action_width = imgui.calc_text_size(icon).x + 2 * style.frame_padding.x
    imgui.text_colored(muted(), fit_text(name, imgui.get_content_region_avail().x))
    imgui.set_item_tooltip(name)
    with tinted_row(tone) as width:
        left = imgui.get_cursor_pos_x()
        imgui.align_text_to_frame_padding()
        detail = "Running" if running else "Launch failed" if error else "Not running"
        imgui.text_unformatted(fit_text(detail, width - action_width - style.item_spacing.x))
        imgui.set_item_tooltip(error or f"Launch {name} before using it.")
        imgui.same_line()
        imgui.set_cursor_pos_x(left + width - action_width)
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


def connect_ui(ctx: Context) -> None:
    """Launch the generator and optional hand, then connect the EMG stream."""
    for name, _argv in PROCESSES:
        _process_ui(ctx, name)
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
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped(stream.last_error)
        imgui.pop_style_color()
    imgui.begin_disabled(ctx.state != "idle" or busy)
    if primary_button("Reconnect" if connected else "Retry" if stream.last_error else "Connect",
                      size=(-1, 0)):
        _connect()
    imgui.end_disabled()
    imgui.push_style_color(imgui.Col_.text, muted())
    imgui.text_wrapped("Return to idle before changing the generator or connection." if ctx.state != "idle"
                       else "Launch the generator, then connect to see the signal.")
    imgui.pop_style_color()


def predict_ui() -> None:
    """Tune the output filter and inspect the live class while predicting."""
    output_filter.ui()
    imgui.spacing()
    prediction.ui()
    predict_button.ui()


def signal_ui() -> None:
    """Draw the signal card with its own detachable-window action."""
    _card_header("Signal", panel="Signal")
    viewer.ui(app.ctx)


def log_ui() -> None:
    """Keep the activity log's clear and pop-out actions on its header."""
    _card_header("Activity log", panel="Log", clear_log=True)
    render_log("activity", app.ctx.logs or ["(no events yet)"])


def _step_done(ctx: Context) -> list[bool]:
    """Completion follows the connection, participant takes, model and prediction."""
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
    _poll_model_ui()
    done = _step_done(ctx)
    with layout["header"]:
        active = header.ui(ctx, done)
    padding = imgui.get_style().window_padding
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding.x, ui_px(4)))
    # A detached Recording card owns its tick; otherwise advance it off-step.
    detached_recording = _panel_visible("Recording")
    if active != 1 and not detached_recording:
        recording.ui(ctx, visible=False)
    # Refresh the participant's selection before Train reads it this frame.
    with layout["sessions"]:
        pipeline.training_data = sessions.ui(participant=ctx.participant)
    with layout["step"]:
        stream = ctx.streams.get("emg")
        tone = SUCCESS if done[0] else DANGER if stream is not None and stream.last_error else IDLE
        _card_header(steps.steps[active], status=tone if active == 0 else None,
                     training=active == 2)
        if active == 0:
            connect_ui(ctx)
        elif active == 1:
            if detached_recording:
                imgui.push_style_color(imgui.Col_.text, muted())
                imgui.text_wrapped("Recording controls are open in their own window. Close it to return here.")
                imgui.pop_style_color()
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


def _connect_panel() -> None:
    panel_header("Connect")
    connect_ui(app.ctx)


def _recording_panel() -> None:
    panel_header("Record")
    recording.ui(app.ctx)


def _training_panel() -> None:
    _card_header("Train", training=True)
    model_ui()


def _sessions_panel() -> None:
    pipeline.training_data = sessions.ui(participant=app.ctx.participant)


def _prediction_panel() -> None:
    panel_header("Predict")
    predict_ui()


# Start closed: the session shell stays the default and its header actions open windows.
for _title, _draw in (
    ("Signal", signal_ui),
    ("Streams", lambda: streams.ui(app.ctx)),
    ("Log", log_ui),
    ("Processes", processes.ui),
    ("Connect", _connect_panel),
    ("Recording", _recording_panel),
    ("Model", _training_panel),
    ("Post-processing", output_filter.ui),
    ("Sessions", _sessions_panel),
    ("Prediction", _prediction_panel),
    ("Simulated EMG", lambda: simulator.ui(app.ctx)),
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
