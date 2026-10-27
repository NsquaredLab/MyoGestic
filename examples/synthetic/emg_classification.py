"""Classification demo: fake EMG → numpy features → CatBoost, with an optional hand.

Run with:
    uv run python examples/synthetic/emg_classification.py

Workflow:
    1. Connect: launch "EMG Generator", then connect the EMG stream
    2. Set a participant, then click Rest/Fist to switch signal + set label
    3. Record Rest trial → Record Fist trial
    4. Select sessions → Train → Predict; optionally connect the Virtual Hand
       for a continuous LSL pose and discrete gRPC movements
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
from myogestic._theme import mono_font
from myogestic.controls import ControlLink, ControlLinkConnector, load_control_map
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
    VhiMovementPanel,
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

# --8<-- [start:poses]
vhi = virtual_hand()

# The left side is ours (`fist` and `gesture`), the right side is VHI's.
# Parsing needs no VHI or gRPC; resolving waits for an explicit Connect.
CONTROL_FILE = (
    pathlib.Path(__file__).resolve().parent.parent / "controls" / "classification_grpc.toml"
)
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

# --8<-- [end:poses]

# --8<-- [start:filter]
output_filter = PostProcessor(hz=32, compact=True)
# --8<-- [end:filter]

# Construct the optional gRPC clients only when Connect is clicked.
vhi_control = None
recording_aid = None
link = None
binder = None
vhi_panel = None


# Any callable of your own goes in this dict too — features are user code.
# --8<-- [start:features]
features = FeatureSelector(
    {"RMS": rms, "MAV": mav, "WL": wl, "VAR": var, "ZC": zc},
    default=["RMS", "MAV"],
    show_header=False,
)
# --8<-- [end:features]

# Missing VHI is a normal idle state, so never call the strict launcher here.
hand_processes = vhi.launchable()
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
    *hand_processes,
]

CLASSES = ["Rest", "Fist"]
CTRL_VALUES = [0.0, 1.0]

# --8<-- [start:setup]
WINDOW_MS = 200
HOP_MS = 100

app = App("EMG classification", require_participant=True)
app.streams(Stream("emg", source=LSLSource("TestEMG1"), window_ms=WINDOW_MS, buffer_ms=60000))
pipeline = Pipeline(app)
# --8<-- [end:setup]


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
    """Stream the predicted hand pose over LSL and gesture changes over gRPC."""
    proba = model.predict_proba(features.reshape(1, -1))[0]
    class_idx = int(np.argmax(proba))
    if link is None or link.bus is None:
        # `link.bus`, never `link.ensure()`: binding blocks on an RPC and this runs on the
        # predict thread.
        return {"class": class_idx, "proba": proba}

    # One frame carries both outputs. The bus applies the debounce the control file
    # declares, so the gesture reaches the control hand only once it has settled.
    values = link.bus.push({"fist": CTRL_VALUES[class_idx], "gesture": CLASSES[class_idx]})

    return {"class": class_idx, "proba": proba, "hand": values}


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


def _select_gesture(state: str) -> None:
    """Select a movement on the connected hand without probing an absent service."""
    bus = link.bus if link is not None else None
    if bus is not None:
        # Immediate selection also rebases the discrete output's debounce trigger.
        bus.select("gesture", state)


def _on_gesture(i: int) -> None:
    simulator.set(CTRL_VALUES[i])
    _select_gesture(CLASSES[i])


def _on_record() -> None:
    # A simulator preview may differ from the gesture selected for this take.
    if 0 <= app.ctx.current_label < len(CTRL_VALUES):
        simulator.set(CTRL_VALUES[app.ctx.current_label])
    app.start_recording()
    # No hand means no RPC or delay: acquisition is independent of this optional aid.
    if (
        link is not None
        and link.bus is not None
        and recording_aid is not None
        and not recording_aid.set_recording_session(True)
    ):
        app.ctx.log("VHI recording-session gate unavailable — keyboard is not blocked")


def _on_stop() -> None:
    app.stop_recording()
    if recording_aid is not None and recording_aid.available:
        recording_aid.set_recording_session(False)


# The Connect step owns acquisition; signal and simulator stay visible on every step.
viewer = SignalViewer("emg", show_connect=False)
simulator = SimulatorControls([("Rest", 0.0), ("Fist", 1.0)])
processes = ProcessLauncher(PROCESSES)
recording = RecordingControls(
    CLASSES,
    on_record=_on_record,
    on_stop=_on_stop,
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
hand_attempt = {"phase": "idle", "error": ""}


def _init_hand() -> bool:
    """Load optional gRPC support on demand; a lean install still runs every step."""
    global vhi_control, recording_aid, link, binder, vhi_panel
    if link is not None:
        return True
    try:
        control = vhi.control_client()
        aid = vhi.recording_client()
    except ModuleNotFoundError as exc:
        if exc.name not in {"grpc", "google", "google.protobuf"}:
            raise
        hand_attempt.update(phase="failed", error="Install the grpc extra to connect the hand.")
        return False
    vhi_control, recording_aid = control, aid
    link = ControlLink(
        CONTROL_MAP,
        [RemoteTarget(client=vhi_control, interface=vhi)],
        ctx=app.ctx,
        smoothing=output_filter,
        hz=pipeline.predict_hz,
    )
    binder = ControlLinkConnector(link)
    vhi_panel = VhiMovementPanel(recording_aid, _select_gesture)
    return True


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
        imgui.text_unformatted(
            "Connected"
            if connected
            else "Connecting…"
            if busy
            else "Connection failed"
            if stream.last_error
            else "Not connected"
        )
    if stream.last_error and not busy and not connected:
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped(stream.last_error)
        imgui.pop_style_color()
    imgui.begin_disabled(ctx.state != "idle" or busy)
    if primary_button(
        "Reconnect" if connected else "Retry" if stream.last_error else "Connect", size=(-1, 0)
    ):
        _connect()
    imgui.end_disabled()
    imgui.push_style_color(imgui.Col_.text, muted())
    imgui.text_wrapped(
        "Return to idle before changing the generator or connection."
        if ctx.state != "idle"
        else "Launch the generator, then connect to see the signal."
    )
    imgui.pop_style_color()
    imgui.spacing()
    hand_ui()


def model_ui() -> None:
    """Choose features, train on the selected takes and read the training log."""
    imgui.text_colored(muted(), "Features")
    features.ui()
    imgui.spacing()
    train_button.ui()
    training_log.ui()


def hand_ui() -> None:
    """Connect to an existing hand first, then launch one only if none answered.

    The operator's Connect arms the background binder. Stop cancels the attempt;
    a replacement connector waits for late cleanup before it can bind again.
    """
    global binder
    bound = link is not None and link.bus is not None
    running = processes.running(vhi.name)
    phase = hand_attempt["phase"]
    if phase == "stopping" and binder.finished:
        binder = ControlLinkConnector(link)
        phase = "stopped" if running else "idle"
        bound = link is not None and link.bus is not None
    if phase == "idle" and running and not bound and _init_hand():
        phase = "launched"
    if phase == "checking" and binder.finished:
        # The connection may have completed since this frame began.
        bound = link is not None and link.bus is not None
        if not bound:
            if binder.last_error is not None:
                # A responding but incompatible target must not spawn another.
                phase = "failed"
            elif running:
                phase = "launched"
            elif hand_processes:
                try:
                    processes.launch(vhi.name)
                    running = True
                    phase = "launched"
                    hand_attempt["error"] = ""
                except Exception as exc:
                    hand_attempt["error"] = str(exc)
                    app.ctx.log(f"Virtual Hand launch failed: {exc}")
                    phase = "failed"
            else:
                phase = "failed"
    if phase == "launched" and not bound and not binder.busy:
        binder.poll()
    if bound and phase != "stopping":
        phase = "bound"
    hand_attempt["phase"] = phase
    if bound and phase != "stopping":
        tone, detail = SUCCESS, "Connected · LSL + gRPC"
    elif phase == "stopping":
        tone, detail = WARNING, "Stopping…"
    elif phase in ("checking", "launched"):
        tone, detail = WARNING, binder.status or "Launched · waiting for the hand…"
    elif phase == "failed" and binder is not None:
        tone = DANGER
        detail = hand_attempt["error"] or (
            binder.status if binder.last_error is not None else "No Virtual Hand answered"
        )
        if not hand_processes and binder.last_error is None:
            detail += " · not installed here"
    elif phase == "failed":
        tone, detail = WARNING, hand_attempt["error"]
    else:
        tone, detail = IDLE, "Not running"
    if running or phase in ("checking", "launched", "stopping"):
        action = "Stop"
    elif bound:
        action = ""
    else:
        action = "Retry" if phase == "failed" else "Connect"
    mapping = "\n".join(
        f"{alias} → {', '.join(target.address for target in binding.targets)}"
        for alias, binding in CONTROL_MAP.bindings.items()
    )
    hint = f"{vhi.install_hint.strip()}\n\n" if not hand_processes else ""
    style = imgui.get_style()
    narrow = imgui.get_content_region_avail().x < ui_px(300)
    height = 2 * imgui.get_frame_height() + style.item_spacing.y + ui_px(8) if narrow else None
    with tinted_row(height=height) as width:
        right = imgui.get_cursor_pos_x() + width
        action_w = imgui.calc_text_size(action).x + 2 * style.frame_padding.x if action else 0.0
        imgui.align_text_to_frame_padding()
        imgui.text_colored(tone, fa.ICON_FA_CIRCLE)
        imgui.same_line()
        imgui.text_unformatted("Virtual Hand")
        if narrow:
            imgui.align_text_to_frame_padding()
        else:
            imgui.same_line()
        font = mono_font()
        if font is not None:
            imgui.push_font(font, style.font_size_base)
        available = max(0.0, right - action_w - style.item_spacing.x - imgui.get_cursor_pos_x())
        mono_text(fit_text(detail, available), muted())
        if font is not None:
            imgui.pop_font()
        imgui.set_item_tooltip(f"{detail}\n\n{hint}{mapping}")
        if action:
            imgui.same_line()
            imgui.set_cursor_pos_x(right - action_w)
            imgui.begin_disabled(phase == "stopping")
            if imgui.small_button(f"{action}##virtual_hand") and phase != "stopping":
                if action == "Stop":
                    binder.stop(timeout_s=0.0)
                    if running:
                        processes.stop(vhi.name)
                    hand_attempt["phase"] = "stopping"
                else:
                    hand_attempt["error"] = ""
                    if _init_hand():
                        binder.poll(force=True)
                        hand_attempt["phase"] = "checking"
            imgui.end_disabled()
            if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
                imgui.set_tooltip(
                    "Wait for the connection attempt to stop."
                    if phase == "stopping"
                    else "Stop connecting and close the hand launched here."
                    if action == "Stop"
                    else "Bind to a running Virtual Hand, or launch one if none answers."
                )

    # Keep the complete movement palette available without nesting its card header.
    label = fit_text(
        f"{fa.ICON_FA_HAND}  Hand movements…",
        imgui.get_content_region_avail().x - 2 * style.frame_padding.x,
    )
    if imgui.small_button(f"{label}##hand_movements"):
        imgui.open_popup("hand_movements")
    imgui.set_item_tooltip("Manually command the control hand through the gesture output.")
    imgui.set_next_window_size(imgui.ImVec2(ui_px(360), ui_px(320)))
    if imgui.begin_popup("hand_movements"):
        if vhi_panel is not None:
            vhi_panel.ui()
        else:
            imgui.text_wrapped("The hand is not running.")
            imgui.text_colored(muted(), "Connect it to load its movements.")
        imgui.end_popup()


def _pushed() -> list[tuple[str, str, str]]:
    """Return the two output routes and the values in the last delivered frame."""
    values = pipeline.predictions.get("hand")
    if not values:
        return []
    rows = []
    for alias, value in values.items():
        binding = CONTROL_MAP.bindings.get(alias)
        targets = ", ".join(target.address for target in binding.targets) if binding else "unmapped"
        label = (
            "fist · predicted hand (LSL)" if alias == "fist" else "gesture · control hand (gRPC)"
        )
        rows.append((label, value if isinstance(value, str) else f"{value:+.2f}", targets))
    return rows


def predict_ui() -> None:
    """Predict, smooth the continuous output and inspect both hand commands."""
    prediction.ui()
    predict_button.ui()
    imgui.spacing()
    output_filter.ui()
    imgui.spacing()
    imgui.text_colored(muted(), "Sent to the hand")
    rows = _pushed()
    if not rows:
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped("No commands sent yet. Connect the hand, then start predicting.")
        imgui.pop_style_color()
    style = imgui.get_style()
    for label, value, targets in rows:
        font = mono_font()
        if font is not None:
            imgui.push_font(font, style.font_size_base)
        value_width = imgui.calc_text_size(value).x
        if font is not None:
            imgui.pop_font()
        right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
        room = imgui.get_content_region_avail().x - value_width - style.item_spacing.x
        imgui.text_unformatted(fit_text(label, room))
        imgui.set_item_tooltip(f"{label} → {targets}")
        imgui.same_line()
        imgui.set_cursor_pos_x(right - value_width)
        mono_text(value)


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
        if binder is not None:
            binder.stop()
        if recording_aid is not None:
            if recording_aid.available:
                recording_aid.set_recording_session(False)
            recording_aid.stop()
        if vhi_control is not None:
            vhi_control.stop()


if __name__ == "__main__":
    main()
