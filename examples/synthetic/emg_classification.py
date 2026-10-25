"""Classification demo: fake EMG → numpy features → CatBoost → VHI hand.

Run with:
    uv run python examples/synthetic/emg_classification.py

Workflow:
    1. Connect: launch "EMG Generator", then connect the EMG stream
    2. Set a participant, then click Rest/Fist to switch signal + set label
    3. Record Rest trial → Record Fist trial
    4. Select sessions → Train → Predict → VHI hand moves
    5. Use Simulated EMG on any step to try Rest/Fist while predicting
"""

import pathlib
import sys
import threading
import tomllib

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic import App, Context, Fr, Grid, Layout, Px, Stream, TrainingData
from myogestic.controls import ControlLink, load_control_map
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PredictButton, TrainButton, TrainingLog
from myogestic.recipes.estimators import catboost_classifier
from myogestic.recipes.features import mav, rms, var, wl, zc
from myogestic.remote import RemoteTarget
from myogestic.session import iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.vhi import virtual_hand
from myogestic.widgets import (
    AppHeader,
    FeatureSelector,
    LogPanel,
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
)
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    SUCCESS,
    WARNING,
    fit_text,
    muted,
    panel_header,
    primary_button,
    tinted_row,
    ui_px,
)

# --8<-- [start:poses]
vhi = virtual_hand()

# The left side is ours, the right side is VHI's. Parsing needs no VHI; resolving does.
CONTROL_FILE = pathlib.Path(__file__).resolve().parent.parent / "controls" / "classification.toml"
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

# Both aliases declare a `threshold_fraction` in the file, so a probability is gated to
# 0 or 1 there and reaches the hand as an ordinary control value — same path as regression.
FIST_ALIASES = ("fist", "thumb_spread")

# --8<-- [end:poses]

# --8<-- [start:filter]
output_filter = PostProcessor(hz=32, compact=True)
# --8<-- [end:filter]

vhi_control = vhi.control_client()


# Any callable of your own goes in this dict too — features are user code.
# --8<-- [start:features]
features = FeatureSelector(
    {"RMS": rms, "MAV": mav, "WL": wl, "VAR": var, "ZC": zc},
    default=["RMS", "MAV"], show_header=False,
)
# --8<-- [end:features]

PROCESSES = [
    (
        "EMG Generator",
        [
            sys.executable,
            "-m",
            "myogestic.tools.emg_generator",
            "--name",
            "TestEMG1",
            "--channels",
            "8",
            "--fs",
            "2048",
            "--control",
            "EMG_Control",
        ],
    ),
]

CLASSES = ["Rest", "Fist"]
CTRL_VALUES = [0.0, 1.0]

# --8<-- [start:setup]
WINDOW_MS = 200
HOP_MS = 100

app = App("EMG Classification", require_participant=True)
app.streams(Stream("emg", source=LSLSource("TestEMG1"), window_ms=WINDOW_MS, buffer_ms=60000))
pipeline = Pipeline(app)
# --8<-- [end:setup]

# Nothing is resolved here. `link.ensure()` binds to an already running VHI on the
# first click that finds VHI up; `link.bus` is None until then, and `RemoteTarget` refuses
# a VHI it cannot fully drive rather than guessing.
link = ControlLink(
    CONTROL_MAP,
    # No hand and no stream is named: the target looks this file's addresses up in VHI's
    # manifest and publishes one one-channel stream per address it drives.
    [RemoteTarget(client=vhi_control, interface=vhi)],
    ctx=app.ctx,
    smoothing=output_filter,
    hz=32,
)


# --8<-- [start:extract]
@pipeline.extract
def extract(windows: dict[str, np.ndarray]) -> np.ndarray:
    """Active features stacked along axis 0 → flat feature vector."""
    return features(windows["emg"])


# --8<-- [end:extract]


# --8<-- [start:train]
@pipeline.train
def train(data: TrainingData):
    """Train a CatBoost classifier on numpy features from selected sessions.

    Every feature here reduces a window to one scalar per channel, so the feature
    dimension is ``n_active_features * n_channels``.
    """
    if data.is_empty:
        raise ValueError("No sessions selected. Load some and tick the checkboxes.")
    if len(data.classes) < 2:
        active = sorted(data.classes)
        names = [CLASSES[i] if 0 <= i < len(CLASSES) else f"c{i}" for i in active]
        raise ValueError(
            f"Classification needs ≥2 active classes — got {len(active)} ({names}). "
            f"Toggle more class chips on."
        )
    if features.n_active == 0:
        raise ValueError(
            "No features ticked in the FEATURES panel. Tick at least one "
            "(RMS+MAV is the default combo)."
        )
    print(f"[train] features: {features.active_names}")

    all_X: list[np.ndarray] = []
    all_y: list[int] = []

    for window, _ts, class_idx in iter_labeled_windows(
        data.paths, "emg", WINDOW_MS, HOP_MS, classes=data.classes
    ):
        all_X.append(extract({"emg": window}))
        all_y.append(class_idx)

    print(
        f"[train] {len(all_X)} windows from {len(data.paths)} sessions, "
        f"classes={sorted(data.classes)}"
    )
    if len(all_X) < 2:
        raise ValueError(f"Need at least 2 windows, got {len(all_X)}")

    X = np.stack(all_X)
    y = np.array(all_y)

    if len(np.unique(y)) < 2:
        raise ValueError(f"Need at least 2 classes, got {len(np.unique(y))}")

    clf = catboost_classifier(iterations=100)
    clf.fit(X, y)
    print(f"[train] done — accuracy on train: {clf.score(X, y):.2%}")
    return clf


# --8<-- [end:train]


# --8<-- [start:predict]
@pipeline.predict
def predict(model, features):
    """Classify → gate to an activation → smooth → push to VHI.

    The probabilities themselves flow through untouched, for the UI.
    """
    proba = model.predict_proba(features.reshape(1, -1))[0]
    class_idx = int(np.argmax(proba))
    # `link.bus`, never `link.ensure()`: binding blocks on an RPC and this callback has a
    # deadline.
    if link.bus is None:
        return {"class": class_idx, "proba": proba}
    # Pushed raw: the bus gates it, so VHI is never handed a bare 0.73 as a finger position.
    activation = float(proba[CLASSES.index("Fist")])
    hand = link.bus.push(dict.fromkeys(FIST_ALIASES, activation))
    return {"class": class_idx, "proba": proba, "hand": hand}


# --8<-- [end:predict]


# --8<-- [start:layout]
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
steps = StepBar(["Connect", "Record", "Train", "Predict"], widget_id="emg_classification_steps")
participant = ParticipantPanel()
header = AppHeader("EMG classification", steps=steps, participant=participant)
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
viewer = SignalViewer("emg", show_connect=False)
simulator = SimulatorControls([("Rest", 0.0), ("Fist", 1.0)])
processes = ProcessLauncher(PROCESSES)
recording = RecordingControls(
    CLASSES,
    on_record=_on_record,
    on_stop=app.stop_recording,
    on_gesture=_on_gesture,
    show_header=False,
)
sessions = SessionManager("sessions", class_names=CLASSES)
train_button = TrainButton(pipeline, size=(-1, 0))
training_log = TrainingLog(pipeline, height=100)
predict_button = PredictButton(pipeline, size=(-1, 0))
prediction = PredictionLabel(pipeline, CLASSES)
log = LogPanel(title="Activity log")
connection = {"busy": False, "launch_error": ""}


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
    """Launch the generator and connect its named EMG stream in one compact card."""
    running = processes.running("EMG Generator")
    error = connection["launch_error"]
    tone = SUCCESS if running else DANGER if error else IDLE
    style = imgui.get_style()
    icon = fa.ICON_FA_STOP if running else fa.ICON_FA_PLAY
    action_width = imgui.calc_text_size(icon).x + 2 * style.frame_padding.x
    imgui.text_colored(muted(), "EMG Generator")
    with tinted_row(tone) as width:
        left = imgui.get_cursor_pos_x()
        imgui.align_text_to_frame_padding()
        detail = "Running" if running else "Launch failed" if error else "Not running"
        imgui.text_unformatted(fit_text(detail, width - action_width - style.item_spacing.x))
        imgui.set_item_tooltip(error or "Generates TestEMG1; Rest and Fist change its signal.")
        imgui.same_line()
        imgui.set_cursor_pos_x(left + width - action_width)
        imgui.begin_disabled(ctx.state != "idle")
        clicked = imgui.small_button(f"{icon}##emg_generator")
        imgui.end_disabled()
        imgui.set_item_tooltip("Stop the generator" if running else "Launch the generator")
        if clicked:
            if running:
                processes.stop("EMG Generator")
            else:
                try:
                    processes.launch("EMG Generator")
                    connection["launch_error"] = ""
                except Exception as exc:
                    connection["launch_error"] = str(exc)
                    ctx.log(f"EMG generator launch failed: {exc}")

    imgui.spacing()
    imgui.text_colored(muted(), "EMG stream · TestEMG1")
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


def model_ui() -> None:
    """Choose features, train on the selected takes and read the training log."""
    imgui.text_colored(muted(), "Features")
    features.ui()
    imgui.spacing()
    train_button.ui()
    training_log.ui()


def predict_ui() -> None:
    """Tune the output filter and inspect the live class while predicting."""
    output_filter.ui()
    imgui.spacing()
    prediction.ui()
    predict_button.ui()


def _step_done(ctx: Context) -> list[bool]:
    """Completion follows the connection, participant takes, model and prediction."""
    stream = ctx.streams.get("emg")
    return [
        stream is not None and stream.status == "connected" and stream.info is not None,
        bool(ctx.participant)
        and any(pathlib.Path("sessions", ctx.participant).glob(f"{ctx.participant}_*")),
        pipeline.model is not None,
        ctx.state == "predicting",
    ]


@app.ui
def demo_ui(ctx: Context) -> None:
    """Keep the signal, sessions and activity visible around the active step."""
    done = _step_done(ctx)
    with layout["header"]:
        active = header.ui(ctx, done)
    padding = imgui.get_style().window_padding
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding.x, ui_px(4)))
    # Recording state advances once per frame, even with another step open.
    if active != 1:
        recording.ui(ctx, visible=False)
    # Refresh the participant's selection before Train reads it this frame.
    with layout["sessions"]:
        pipeline.training_data = sessions.ui(participant=ctx.participant)
    with layout["step"]:
        stream = ctx.streams.get("emg")
        tone = SUCCESS if done[0] else DANGER if stream is not None and stream.last_error else IDLE
        panel_header(steps.steps[active], status=tone if active == 0 else None)
        if active == 0:
            connect_ui(ctx)
        elif active == 1:
            recording.ui(ctx)
        elif active == 2:
            model_ui()
        else:
            predict_ui()
    with layout["signal"]:
        viewer.ui(ctx)
    with layout["simulator"]:
        simulator.ui(ctx)
    with layout["log"]:
        log.ui(ctx)
    imgui.pop_style_var()
    with layout["status"]:
        status.ui(ctx)


# --8<-- [end:layout]


def main() -> None:
    try:
        app.run()
    finally:
        # Rest the hand and make that frame land before the outlet's thread dies.
        link.stop()
        vhi_control.stop()


if __name__ == "__main__":
    main()
