"""Regression demo: EMG + VHI control hand → MyoVerse features → CatBoost Regressor → VHI predicted hand.

Run with:
    uv run --extra examples --extra grpc python examples/synthetic/emg_regression.py

Workflow:
    1. Connect: launch EMG Generator + VHI Hand, then connect their streams
    2. Click a gesture button → MyoGestic drives the VHI control hand over gRPC
    3. Click Record → VHI's local keyboard control is disabled for the session,
       so the gesture buttons are the sole movement source → Stop Rec
    4. Select sessions → Train (regression on kinematics)
    5. Predict → VHI predicted hand mirrors control hand
    6. Use Simulated EMG on any step to try Rest/Fist while predicting

The control space lives in `examples/controls/regression.toml` — our aliases on the left,
VHI's addresses on the right. VHI declares what they accept, so nothing resolves until it runs.
"""

import pathlib
import sys
import tomllib

import numpy as np
import torch
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui
from myoverse.transforms import MAV, RMS, WaveformLength

from myogestic import App, Context, Fr, Grid, Layout, Px, Stream, TrainingData
from myogestic._theme import mono_font
from myogestic.controls import ControlLink, load_control_map
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PredictButton, TrainButton, TrainingLog
from myogestic.recipes.estimators import catboost_regressor
from myogestic.remote import RemoteTarget
from myogestic.session import (
    iter_aligned_windows,
    iter_labeled_windows,
    split_sessions_by_stream,
)
from myogestic.sources import LSLSource
from myogestic.vhi import virtual_hand
from myogestic.vhi.pose import ADDRESS_CHANNELS, POSE_DOFS, split_pose
from myogestic.widgets import (
    AppHeader,
    LogPanel,
    ParticipantPanel,
    PostProcessor,
    ProcessLauncher,
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
    fit_text,
    mono_text,
    muted,
    panel_header,
    tinted_row,
    ui_px,
)
from myogestic.widgets.panels.recording import RecordingControls

CLASSES = ["Rest", "Fist"]
CTRL_VALUES = [0.0, 1.0]

vhi = virtual_hand()
recording_aid = vhi.recording_client()

output_filter = PostProcessor(hz=32)

# No VHI channel number appears here: `RemoteTarget` owns the translation to the wire.
# --8<-- [start:dofs]
CONTROL_FILE = pathlib.Path(__file__).resolve().parent.parent / "controls" / "regression.toml"
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

# Which recorded column each alias learns from. `ADDRESS_CHANNELS` is a table, not a manifest
# lookup, so training needs no running VHI; `gesture` is not a pose channel and drops out here.
DOF_TARGETS: dict[str, str] = {
    alias: POSE_DOFS[ADDRESS_CHANNELS[binding.targets[0].address]]
    for alias, binding in CONTROL_MAP.bindings.items()
    if binding.targets and binding.targets[0].address in ADDRESS_CHANNELS
}
DOF_NAMES = tuple(DOF_TARGETS)
# --8<-- [end:dofs]

# MyoVerse transforms rather than hand-rolled numpy: compatible with downstream MyoGestic models.
rms_transform = RMS(window_size=32)
mav_transform = MAV(window_size=32)
wl_transform = WaveformLength(window_size=32)

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
    # `launchable`, never `launcher`: a VHI that cannot be launched must not stop this app
    # from opening, and one already running needs no button.
    *vhi.launchable(),
]

vhi_control = vhi.control_client()

app = App("EMG Regression")
app.streams(
    Stream("emg", source=LSLSource("TestEMG1"), window_ms=1000, buffer_ms=60000),
    Stream(
        "vhi_control",
        source=LSLSource(vhi.control_stream_name or "VHI_Control"),
        window_ms=1000,
        buffer_ms=60000,
    ),
)
pipeline = Pipeline(app)

# --8<-- [start:bus]
# Resolving the control file needs VHI to say what its addresses accept, and VHI is launched
# from this app's own ProcessLauncher — so `link.bus` stays None until the first `ensure()`.
link = ControlLink(
    CONTROL_MAP,
    [RemoteTarget(client=vhi_control, interface=vhi)],
    ctx=app.ctx,
    smoothing=output_filter,
    hz=32,
)
# --8<-- [end:bus]


def extract_features(emg: np.ndarray) -> np.ndarray:
    """MyoVerse RMS + MAV + WL from EMG window → (n_features,)."""
    tensor = torch.from_numpy(emg).float()
    rms = rms_transform(tensor).numpy().flatten()
    mav = mav_transform(tensor).numpy().flatten()
    wl = wl_transform(tensor).numpy().flatten()
    return np.concatenate([rms, mav, wl])


@pipeline.extract
def extract(windows) -> np.ndarray:
    return extract_features(windows["emg"])


WINDOW_MS = 200
HOP_MS = 100


@pipeline.train
def train(data: TrainingData):
    """Train CatBoost regressor: EMG features → one column per continuous alias.

    Sessions with recorded `vhi_control` kinematics regress to the aligned pose; sessions
    without fall back to a synthetic target (rest=0, fist=1).
    """
    log = pipeline.train_log
    log.clear()

    aliases = DOF_NAMES
    n_dof = len(aliases)
    pose_keys = [DOF_TARGETS[a] for a in aliases]
    log.append(f"Training from {len(data.paths)} sessions, targets: {', '.join(aliases)}")

    all_X: list[np.ndarray] = []
    all_y: list[np.ndarray] = []

    kin_paths, label_paths, unreadable = split_sessions_by_stream(data.paths, "vhi_control")
    for p, e in unreadable:
        log.append(f"  skip {p}: {e}")

    # --8<-- [start:kin_loop]
    for emg_window, aligned, _ts in iter_aligned_windows(
        kin_paths,
        "emg",
        ["vhi_control"],
        WINDOW_MS,
        HOP_MS,
        n_alignment_samples=10,
    ):
        # A recorded pose is already in the space `predict` commands, so this only names channels.
        pose = split_pose(aligned["vhi_control"])
        kin = np.array([pose[key] for key in pose_keys], dtype=np.float64)
        all_X.append(extract_features(emg_window))
        all_y.append(kin)
    # --8<-- [end:kin_loop]
    if kin_paths:
        log.append(f"  kinematics: {len(all_X)} windows from {len(kin_paths)} sessions")

    n_before_labels = len(all_X)
    # --8<-- [start:label_loop]
    for emg_window, _ts, ci in iter_labeled_windows(
        label_paths,
        "emg",
        WINDOW_MS,
        HOP_MS,
        classes=data.classes if data.classes else None,
    ):
        # +1 is flexion under the control standard: a Fist target is all 1s, Rest all 0s.
        kin = np.ones(n_dof, dtype=np.float64) if ci == 1 else np.zeros(n_dof, dtype=np.float64)
        all_X.append(extract_features(emg_window))
        all_y.append(kin)
    # --8<-- [end:label_loop]
    if label_paths:
        log.append(
            f"  labels: {len(all_X) - n_before_labels} windows from {len(label_paths)} sessions"
        )

    log.append(f"Total: {len(all_X)} samples")

    if len(all_X) < 2:
        raise ValueError(f"Need at least 2 samples, got {len(all_X)}")

    X = np.stack(all_X)
    y = np.stack(all_y)
    log.append(f"X: {X.shape}, y: {y.shape}")

    reg = catboost_regressor(iterations=200, loss_function="MultiRMSE")
    reg.fit(X, y)
    log.append("Training complete")
    return reg


# --8<-- [start:predict]
@pipeline.predict
def predict(model, features):
    """Regress the continuous aliases and hand them to the bus."""
    # `link.bus`, never `link.ensure()`: binding blocks on an RPC and this callback runs
    # on the predict thread, where a stall is worse than a frame with no bus.
    bus = link.bus
    if bus is None:
        return None
    pred = model.predict(features.reshape(1, -1))[0]
    # No clip here: each alias's resolved range is the authority, and clipping before the
    # smoother would let the filter overshoot straight back out of it.
    return {"dof": bus.push(dict(zip(DOF_NAMES, pred, strict=True)))}


# --8<-- [end:predict]


# --8<-- [start:grid]
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
steps = StepBar(["Connect", "Record", "Train", "Predict"], widget_id="emg_regression_steps")
participant = ParticipantPanel()
header = AppHeader("EMG regression", steps=steps, participant=participant)
status = StatusBar("emg", pipeline=pipeline)
# --8<-- [end:grid]


# --8<-- [start:gesture]
def _on_gesture(i: int) -> None:
    # Holding the pose makes VHI_Control settle to one static value per gesture — that
    # constant is what the regressor learns to map EMG amplitude back to. `bus.select`
    # skips the debounce and rebases the trigger so the next push does not re-fire it.
    bus = link.ensure()
    simulator.set(CTRL_VALUES[i])
    if bus is not None:
        # `CLASSES` must name VHI's own movements; `select` returns False if one does not.
        bus.select("gesture", CLASSES[i])


# --8<-- [end:gesture]


# --8<-- [start:record]
def _on_record() -> None:
    # Gates VHI's local keyboard so the gesture buttons are the session's only movement
    # source. False means this VHI has no v2 aid — an ungated take picks up stray keys.
    link.ensure()
    # A simulator preview may differ from the gesture selected for this take.
    if 0 <= app.ctx.current_label < len(CTRL_VALUES):
        simulator.set(CTRL_VALUES[app.ctx.current_label])
    app.start_recording()
    if not recording_aid.set_recording_session(True):
        app.ctx.log("VHI recording-session gate unavailable — keyboard is not blocked")


def _on_stop() -> None:
    app.stop_recording()
    recording_aid.set_recording_session(False)


# --8<-- [end:record]


# Connect owns both stream connections; the signal and simulator stay visible.
viewer = SignalViewer("emg", selectable=True, show_connect=False)
simulator = SimulatorControls([("Rest", 0.0), ("Fist", 1.0)])
streams = StreamPanel(show_header=False)
log = LogPanel(title="Activity log")
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
launch_errors: dict[str, str] = {}


def connect_ui(ctx: Context) -> None:
    """Launch the configured processes and connect EMG and optional kinematics."""
    for name, _command in PROCESSES:
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
            imgui.set_item_tooltip(error or f"Launch {name}, then connect its stream below.")
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
    imgui.spacing()
    imgui.text_colored(muted(), "Streams")
    streams.ui(ctx)
    imgui.push_style_color(imgui.Col_.text, muted())
    imgui.text_wrapped(
        "Return to idle before changing processes."
        if ctx.state != "idle"
        else "Launch the sources, then connect. VHI kinematics are optional; "
        "takes without them train from Rest/Fist labels."
    )
    if ctx.state == "recording":
        imgui.text_wrapped("Stop recording before changing connections.")
    imgui.pop_style_color()


def model_ui() -> None:
    """Train the fixed MyoVerse features on selected takes and show the fit log."""
    imgui.text_colored(muted(), "Features")
    imgui.text_wrapped("RMS · MAV · WL (MyoVerse)")
    imgui.spacing()
    train_button.ui()
    training_log.ui()


def predict_ui() -> None:
    """Tune smoothing and read the continuous controls sent to the hand."""
    output_filter.ui()
    imgui.spacing()
    imgui.text_colored(muted(), "Sent to the hand")
    outputs = pipeline.predictions.get("dof") or {}
    if not outputs:
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped("No output yet — train a model, then start predicting.")
        imgui.pop_style_color()
    for alias in DOF_NAMES:
        if alias not in outputs:
            continue
        value = f"{outputs[alias]:+.2f}"
        style = imgui.get_style()
        imgui.push_font(mono_font(), style.font_size_base)
        value_width = imgui.calc_text_size(value).x
        imgui.pop_font()
        right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
        room = imgui.get_content_region_avail().x - value_width - style.item_spacing.x
        imgui.text_unformatted(fit_text(alias, max(0.0, room)))
        imgui.set_item_tooltip(alias)
        imgui.same_line()
        imgui.set_cursor_pos_x(right - value_width)
        mono_text(value)
    imgui.spacing()
    predict_button.ui()


def _step_done(ctx: Context) -> list[bool]:
    """Completion follows EMG, participant takes, the model and live prediction."""
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


def main() -> None:
    try:
        app.run()
    finally:
        # `link.stop()` first, and it waits: the outlet sends on a paced thread, so the rest
        # pose it pushes at exit would otherwise never go out and the hand would hold.
        link.stop()
        recording_aid.stop_trajectory()  # no-op unless a trajectory was started
        recording_aid.set_recording_session(False)
        recording_aid.stop()
        vhi_control.stop()


if __name__ == "__main__":
    main()
