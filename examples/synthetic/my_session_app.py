"""Copy this file for your own session app. Change the four numbered sections.

    uv run python examples/synthetic/my_session_app.py

Connect launches the synthetic EMG generator. Choose a participant in the header,
record each gesture, select the takes, train, then predict. Only NumPy is needed.
"""

import sys
import threading
from pathlib import Path

import numpy as np
from imgui_bundle import imgui

from myogestic import App, Context, Fr, Grid, Layout, Px, Stream, TrainingData
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PredictButton, TrainButton, TrainingLog
from myogestic.session import iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.widgets import (
    AppHeader,
    LogPanel,
    ParticipantPanel,
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
    panel_header,
    primary_button,
    tinted_row,
    ui_px,
)

# ── 1. Name your gesture classes (class 0 is rest) ──────────────────────────────
CLASSES = ["Rest", "Fist"]
WINDOW_MS, HOP_MS = 200, 100
app = App("My session app", require_participant=True)
app.streams(Stream("emg", source=LSLSource("MySessionEMG"), window_ms=WINDOW_MS, buffer_ms=60000))
pipeline = Pipeline(app)


# ── 2. Extract your features, identically during training and prediction ────────
@pipeline.extract
def extract(windows: dict[str, np.ndarray]) -> np.ndarray:
    """Reduce each channels-first EMG window to per-channel RMS."""
    return np.sqrt(np.mean(windows["emg"].astype(np.float64) ** 2, axis=1))


# ── 3. Fit your model on the selected, labelled recording windows ──────────────
@pipeline.train
def train(data: TrainingData) -> dict[int, np.ndarray]:
    """Keep one mean feature vector per class: a tiny nearest-centroid model."""
    grouped: dict[int, list[np.ndarray]] = {}
    for window, _ts, label in iter_labeled_windows(
        data.paths, "emg", WINDOW_MS, HOP_MS, classes=data.classes,
    ):
        grouped.setdefault(label, []).append(extract({"emg": window}))
    if len(grouped) < 2:
        raise ValueError("Record and select takes from at least two gesture classes.")
    return {label: np.mean(windows, axis=0) for label, windows in grouped.items()}


# ── 4. Predict; add your device's output call here if you need one ──────────────
@pipeline.predict
def predict(model: dict[int, np.ndarray], features: np.ndarray) -> dict[str, int]:
    """Return the original class index, even when only some classes were trained."""
    return {"class": min(model, key=lambda label: np.linalg.norm(model[label] - features))}


# The rest is the reusable session shell: acquisition and widgets, with no model logic.
processes = ProcessLauncher([("EMG Generator", [
    sys.executable, "-m", "myogestic.tools.emg_generator", "--name", "MySessionEMG",
    "--channels", "8", "--fs", "2048", "--classes", str(len(CLASSES)),
])])
connection = {"busy": False, "error": ""}
simulator = SimulatorControls([(name, float(i)) for i, name in enumerate(CLASSES)])


def _connect() -> None:
    """Launch and resolve off the GUI thread, with one attempt at a time."""
    if connection["busy"] or app.ctx.state != "idle":
        return
    connection.update(busy=True, error="")

    def connect() -> None:
        try:
            processes.launch("EMG Generator")
            app.ctx.streams["emg"].reconnect()
        except Exception as exc:
            connection["error"] = str(exc)
            app.ctx.log(f"Connection failed: {exc}")
        finally:
            connection["busy"] = False

    threading.Thread(target=connect, daemon=True).start()


def _on_record() -> None:
    """Restore the selected gesture after any simulator preview, then record."""
    simulator.set(float(app.ctx.current_label))
    app.start_recording()


steps = StepBar(["Connect", "Record", "Train", "Predict"], widget_id="my_session_steps")
participant = ParticipantPanel()
header = AppHeader("My session app", steps=steps, participant=participant)
viewer = SignalViewer("emg", show_connect=False)
recording = RecordingControls(
    CLASSES, on_record=_on_record, on_stop=app.stop_recording,
    on_gesture=lambda i: simulator.set(float(i)), show_header=False,
)
sessions = SessionManager("sessions", class_names=CLASSES)
train_button, predict_button = TrainButton(pipeline, size=(-1, 0)), PredictButton(pipeline, size=(-1, 0))
training_log = TrainingLog(pipeline, height=100)
prediction = PredictionLabel(pipeline, CLASSES)
log, status = LogPanel(title="Activity log"), StatusBar("emg", pipeline=pipeline)
layout = Layout(
    wide=Grid.areas(
        "header header\nsignal step\nsignal sessions\nsimulator sessions\nlog sessions\nstatus status",
        row_height=[Px(52), Fr(3), Fr(1), Px(76), Px(110), Px(26)],
        col_width=[Fr(1), Px(400)], bare=("header", "status"),
    ),
    narrow=Grid.areas(
        "header\nsignal\nsimulator\nstep\nsessions\nlog\nstatus",
        row_height=[Px(52), Fr(2), Px(92), Fr(3), Fr(1.5), Px(110), Px(26)],
        bare=("header", "status"),
    ),
    breakpoint=Px(1100),
)


def _step_done(ctx: Context) -> list[bool]:
    """Read completion from the live connection, participant's takes and model."""
    stream = ctx.streams["emg"]
    return [
        stream.status == "connected" and stream.info is not None,
        bool(ctx.participant) and any(Path("sessions", ctx.participant).glob(f"{ctx.participant}_*")),
        pipeline.model is not None, ctx.state == "predicting",
    ]


@app.ui
def ui(ctx: Context) -> None:
    """Keep acquisition, sessions and activity visible around the current step."""
    done = _step_done(ctx)
    with layout["header"]:
        active = header.ui(ctx, done)
    padding = imgui.get_style().window_padding
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding.x, ui_px(4)))
    if active != 1:
        recording.ui(ctx, visible=False)  # A timed take keeps advancing on other steps.
    with layout["sessions"]:
        pipeline.training_data = sessions.ui(participant=ctx.participant)
    with layout["step"]:
        panel_header(steps.steps[active])
        if active == 0:
            error = connection["error"] or ctx.streams["emg"].last_error
            busy = connection["busy"]
            tone = SUCCESS if done[0] else WARNING if busy else DANGER if error else IDLE
            with tinted_row(tone):
                imgui.text_unformatted("Connected" if done[0] else "Connecting…" if busy else
                                       "Connection failed" if error else "Not connected")
            if error:
                imgui.text_wrapped(error)
            imgui.begin_disabled(ctx.state != "idle" or busy)
            if primary_button("Reconnect" if done[0] else "Retry" if error else "Launch & connect",
                              size=(-1, 0)):
                _connect()
            imgui.end_disabled()
            imgui.text_wrapped("Return to idle to reconnect." if ctx.state != "idle" else
                               "Launch the generator, then try Rest/Fist under the signal.")
        elif active == 1:
            recording.ui(ctx)
        elif active == 2:
            train_button.ui()
            training_log.ui()
        else:
            prediction.ui()
            predict_button.ui()
    with layout["signal"]:
        viewer.ui(ctx)
    with layout["simulator"]:
        simulator.ui(ctx)
    with layout["log"]:
        log.ui(ctx)
    imgui.pop_style_var()
    with layout["status"]:
        status.ui(ctx)


if __name__ == "__main__":
    app.run()
