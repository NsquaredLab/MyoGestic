"""Regression demo: same Rest/Fist workflow as ``emg_regression.py``, RaulNet model.

Same experiment as :file:`emg_regression.py` — fake 8-channel EMG, VHI control hand over
gRPC, recording while toggling Rest / Fist, regressing the 5-DOF kinematics target — but
the model is RaulNet V17, a PyTorch Lightning CNN from :mod:`myoverse.models.raul_net`,
instead of CatBoost.

The control space is declared in :file:`examples/controls/regression_raulnet.toml` — your
aliases on the left, VHI's addresses on the right — and resolves against a *running* VHI,
so nothing here hard-codes what a control means.

Run with:
    uv run --extra examples --extra grpc python examples/synthetic/emg_regression_raulnet.py

Workflow:
    1. Connect: launch EMG Generator + VHI Hand, then connect the EMG stream
    2. Set a participant, then Record: Rest or Fist drives the VHI control hand over gRPC
    3. Click Record → VHI's local keyboard is gated off for the session; the buttons
       above are the sole movement source → Stop Rec
    4. Repeat for several recordings (RaulNet wants more data than CatBoost)
    5. Select participant sessions → Train; follow the epoch log
    6. Predict → inspect the continuous output and try Simulated EMG on any step
"""

from __future__ import annotations

import sys
import threading
import tomllib
from pathlib import Path

import lightning as L
import numpy as np
import torch
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui
from lightning.pytorch.callbacks import ModelCheckpoint
from myoverse.models.raul_net.v17 import RaulNetV17

from myogestic import App, Context, Fr, Grid, Layout, Px, Stream, TrainingData
from myogestic.controls import ControlLink, load_control_map
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PredictButton, TrainButton, TrainingLog
from myogestic.remote import RemoteTarget
from myogestic.session import (
    iter_aligned_windows,
    iter_labeled_windows,
    split_sessions_by_stream,
)
from myogestic.sources import LSLSource
from myogestic.vhi import virtual_hand
from myogestic.vhi.pose import split_pose
from myogestic.widgets import (
    AppHeader,
    LogPanel,
    ParticipantPanel,
    PostProcessor,
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
    mono_text,
    muted,
    panel_header,
    primary_button,
    tinted_row,
    ui_px,
)

# ── Stream / window math ──────────────────────────────────────────────

STREAM_NAME = "TestEMG1"
N_CHANNELS = 8
FS = 2048
WINDOW_MS = 200  # analysis window the model sees each prediction
HOP_MS = 100  # training-window step (50% overlap)

N_WINDOW_SAMPLES = int(WINDOW_MS / 1000 * FS)
RMS_WINDOW_MS = 60  # sliding-RMS window, in ms (must be < WINDOW_MS)
RMS_WINDOW_SAMPLES = round(RMS_WINDOW_MS / 1000 * FS)
RMS_STRIDE_MS = 5  # sliding-RMS step, in ms
RMS_STRIDE_SAMPLES = max(1, round(RMS_STRIDE_MS / 1000 * FS))
INPUT_LENGTH = (N_WINDOW_SAMPLES - RMS_WINDOW_SAMPLES) // RMS_STRIDE_SAMPLES + 1
if RMS_WINDOW_SAMPLES >= N_WINDOW_SAMPLES:
    raise ValueError(
        f"RMS_WINDOW_MS={RMS_WINDOW_MS} must be < WINDOW_MS={WINDOW_MS}: "
        "the RMS kernel slides inside the analysis window."
    )

# ── The model's own geometry, checked here rather than inside torch ───
# RaulNetV17's second encoder conv has a kernel 18 wide, hard-coded in the model, so the
# event-search conv's output has to be at least that long: EVENT_SEARCH_STRIDE=8 collapsed
# this example's 29 feature samples to 4, and surfaced only as a torch shape error deep in
# a Lightning stack, after training had started and the windows had been cut.
EVENT_SEARCH_KERNEL = 31
EVENT_SEARCH_STRIDE = 1
_MIN_ENCODER_WIDTH = 18  # RaulNetV17's second conv kernel; not ours to change
_encoder_out = (
    INPUT_LENGTH + 2 * (EVENT_SEARCH_KERNEL // 2) - EVENT_SEARCH_KERNEL
) // EVENT_SEARCH_STRIDE + 1
if _encoder_out < _MIN_ENCODER_WIDTH:
    raise ValueError(
        f"RaulNet would see {_encoder_out} samples after its event-search conv, and its "
        f"next kernel is {_MIN_ENCODER_WIDTH} wide. INPUT_LENGTH={INPUT_LENGTH} "
        f"(WINDOW_MS={WINDOW_MS}, RMS_WINDOW_MS={RMS_WINDOW_MS}, "
        f"RMS_STRIDE_MS={RMS_STRIDE_MS}) at EVENT_SEARCH_STRIDE={EVENT_SEARCH_STRIDE}. "
        "Lower EVENT_SEARCH_STRIDE, shorten RMS_STRIDE_MS, or lengthen WINDOW_MS."
    )

# Training budget. What trains a network is steps, not epochs.
BATCH_SIZE = 8
MAX_EPOCHS = 300
MAX_STEPS = 4000

CLASSES = ["Rest", "Fist"]
CTRL_VALUES = [0.0, 1.0]


def sliding_rms(emg: np.ndarray) -> np.ndarray:
    """Per-channel sliding RMS, ``(n_channels, INPUT_LENGTH)`` always.

    Left-pads with zeros when the input is shorter than the RMS kernel, so the shape
    stays stable on the first frames, before the ring buffer has filled.
    """
    n_ch, n = emg.shape
    if n < RMS_WINDOW_SAMPLES:
        return np.zeros((n_ch, INPUT_LENGTH), dtype=np.float32)
    s = np.lib.stride_tricks.sliding_window_view(emg, RMS_WINDOW_SAMPLES, axis=1)
    if RMS_STRIDE_SAMPLES > 1:
        s = s[:, ::RMS_STRIDE_SAMPLES]
    out = np.sqrt(np.mean(s**2, axis=2)).astype(np.float32)
    if out.shape[1] >= INPUT_LENGTH:
        return out[:, -INPUT_LENGTH:]
    pad = np.zeros((n_ch, INPUT_LENGTH - out.shape[1]), dtype=np.float32)
    return np.concatenate([pad, out], axis=1)


def save_raulnet(model: L.LightningModule, path: str) -> None:
    """Save the trained RaulNet as a torch checkpoint with hparams."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "hparams": dict(model.hparams)}, path)


def load_raulnet(path: str) -> L.LightningModule:
    """Load a RaulNet checkpoint into eval mode on the best device."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    blob = torch.load(path, map_location=device, weights_only=False)
    model = RaulNetV17(**blob["hparams"])
    model.load_state_dict(blob["state_dict"])
    return model.to(device).eval().requires_grad_(False)


vhi = virtual_hand()
recording_aid = vhi.recording_client()
vhi_control = vhi.control_client()

# The aliases on the left are ours and must match regression_raulnet.toml; the names on
# the right are what `split_pose` calls the channels of a recorded VHI_Control frame.
DOF_TARGETS: dict[str, str] = {
    "thumb": "thumb.flexion",
    "index": "index.flexion",
    "middle": "middle.flexion",
    "ring": "ring.flexion",
    "little": "little.flexion",
}
DOF_NAMES = tuple(DOF_TARGETS)
N_DOF = len(DOF_NAMES)
GESTURE = "gesture"  # the alias the Rest / Fist buttons command

CONTROL_FILE = Path(__file__).resolve().parent.parent / "controls" / "regression_raulnet.toml"
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

output_filter = PostProcessor(hz=32)

PROCESSES = [
    (
        "EMG Generator",
        [
            sys.executable,
            "-m",
            "myogestic.tools.emg_generator",
            "--name",
            STREAM_NAME,
            "--channels",
            str(N_CHANNELS),
            "--fs",
            str(FS),
            "--control",
            "EMG_Control",
        ],
    ),
    # `launchable`, never `launcher`: a VHI that cannot be launched must not stop this app
    # from opening, and one already running needs no button.
    *vhi.launchable(),
]

app = App("EMG Regression — RaulNet", require_participant=True)
app.streams(
    Stream("emg", source=LSLSource(STREAM_NAME), window_ms=WINDOW_MS, buffer_ms=60000),
    Stream(
        "vhi_control",
        source=LSLSource(vhi.control_stream_name or "VHI_Control"),
        window_ms=1000,
        buffer_ms=60000,
    ),
)
pipeline = Pipeline(app, predict_hz=20)
pipeline.save_model = save_raulnet
pipeline.load_model = load_raulnet

# Lazy: the bus is built by `link.ensure()`, because every semantic the map needs — range,
# states, number vs held state — is VHI's to declare, and this app launches VHI itself.
link = ControlLink(
    CONTROL_MAP,
    [RemoteTarget(client=vhi_control, interface=vhi)],
    ctx=app.ctx,
    smoothing=output_filter,
    hz=32,
)


@pipeline.extract
def extract(windows) -> np.ndarray:
    """RMS-feature stack of shape ``(n_channels, INPUT_LENGTH)``."""
    return sliding_rms(windows["emg"])


class _TrainLogCallback(L.Callback):
    """Pipe Lightning's per-epoch loss into ``pipeline.train_log``.

    Lightning's progress bar is disabled for this app, so without this callback the
    Train step stays static until the whole fit finishes.
    """

    def __init__(self, log_list: list[str]) -> None:
        super().__init__()
        self._log = log_list

    def on_train_epoch_end(self, trainer: L.Trainer, pl_module: L.LightningModule) -> None:
        loss = trainer.callback_metrics.get("train/loss")
        loss_str = f"{float(loss):.4f}" if loss is not None else "—"
        self._log.append(
            f"  epoch {trainer.current_epoch + 1}/{trainer.max_epochs}  loss={loss_str}"
        )


@pipeline.train
def train(data: TrainingData) -> L.LightningModule:
    """Fit RaulNetV17 on EMG-feature → VHI-control kinematics windows.

    Sessions with a ``vhi_control`` stream use the recorded kinematics as target;
    sessions without it fall back to class-derived ones (Fist→all 1s, Rest→all 0s).
    """
    log = pipeline.train_log
    log.clear()
    log.append(f"Training from {len(data.paths)} sessions...")

    # Unreadable sessions come back rather than being logged inside the helper, so the
    # skip lands in *this* app's log where the user is looking.
    kin_paths, label_paths, unreadable = split_sessions_by_stream(data.paths, "vhi_control")
    for p, e in unreadable:
        log.append(f"  skip {p}: {e}")

    X_list: list[np.ndarray] = []
    y_list: list[np.ndarray] = []

    for emg_window, aligned, _ts in iter_aligned_windows(
        kin_paths,
        "emg",
        ["vhi_control"],
        WINDOW_MS,
        HOP_MS,
        n_alignment_samples=10,
    ):
        X_list.append(sliding_rms(emg_window))
        # A recorded pose is already control-standard: the training target lands in
        # exactly the space `predict` commands, signed, no abs().
        pose = split_pose(aligned["vhi_control"])
        y_list.append(np.array([pose[DOF_TARGETS[n]] for n in DOF_NAMES], dtype=np.float64))
    if kin_paths:
        log.append(f"  kinematics: {len(X_list)} windows from {len(kin_paths)} sessions")

    n_before_labels = len(X_list)
    for emg_window, _ts, ci in iter_labeled_windows(
        label_paths,
        "emg",
        WINDOW_MS,
        HOP_MS,
        classes=data.classes if data.classes else None,
    ):
        target = np.ones(N_DOF, dtype=np.float32) if ci == 1 else np.zeros(N_DOF, dtype=np.float32)
        X_list.append(sliding_rms(emg_window))
        y_list.append(target)
    if label_paths:
        log.append(
            f"  labels: {len(X_list) - n_before_labels} windows from {len(label_paths)} sessions"
        )

    if len(X_list) < 16:
        raise ValueError(
            f"Only {len(X_list)} windows — record more data. RaulNet wants "
            f"a few hundred for stable training."
        )

    X = np.stack(X_list).astype(np.float32)  # (N, n_ch, INPUT_LENGTH)
    y = np.stack(y_list).astype(np.float32)  # (N, n_dof)
    log.append(f"  X shape={X.shape}, y shape={y.shape}")

    # RaulNet wants an extra channel dim: (N, 1, n_ch, INPUT_LENGTH).
    X_tensor = torch.from_numpy(X).unsqueeze(1)
    y_tensor = torch.from_numpy(y)
    dataset = torch.utils.data.TensorDataset(X_tensor, y_tensor)
    # Small on purpose: a batch bigger than the whole demo set (37 windows) gave one step
    # per epoch — 50 updates at 1e-4, which lost to CatBoost unfitted, not outclassed.
    loader = torch.utils.data.DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=0,
        pin_memory=True,
    )
    log.append(
        f"  {len(dataset)} windows, batch {BATCH_SIZE} -> "
        f"{max(1, len(dataset) // BATCH_SIZE)} steps/epoch, "
        f"up to {MAX_EPOCHS} epochs (ceiling {MAX_STEPS} steps)"
    )

    model = RaulNetV17(
        learning_rate=1e-4,
        nr_of_input_channels=1,
        input_length__samples=INPUT_LENGTH,
        nr_of_outputs=N_DOF,
        nr_of_electrode_grids=1,
        nr_of_electrodes_per_grid=N_CHANNELS,
        cnn_encoder_channels=(64, 32, 32),
        mlp_encoder_channels=(128, 128),
        event_search_kernel_length=EVENT_SEARCH_KERNEL,
        event_search_kernel_stride=EVENT_SEARCH_STRIDE,
    )

    torch.set_float32_matmul_precision("medium")
    Path("data/logs").mkdir(parents=True, exist_ok=True)
    # precision="32-true": RaulNet's TorchScript backward graph has hard-coded dtype
    # checks; fp16-mixed and bf16-mixed both trip "mat1 and mat2 different dtype".
    trainer = L.Trainer(
        accelerator="auto",
        devices=1,
        precision="32-true",
        max_epochs=MAX_EPOCHS,
        # Whichever limit comes first wins: `max_epochs` is 50 updates on this demo set
        # and tens of thousands on a real one.
        max_steps=MAX_STEPS,
        # So callback_metrics is populated even when an epoch is a single batch.
        log_every_n_steps=1,
        # No StochasticWeightAveraging: at swa_epoch_start=0.5 it averaged the last 25
        # updates of an unconverged net and froze it. Restore once runs are long enough.
        callbacks=[
            ModelCheckpoint(
                monitor="train/loss",
                mode="min",
                save_top_k=1,
                save_last=True,
                dirpath="data/logs/raulnet/",
            ),
            _TrainLogCallback(log),
        ],
        enable_progress_bar=False,
        enable_model_summary=False,
        deterministic=False,
    )
    trainer.fit(model, train_dataloaders=loader)
    log.append("  done")
    return model.eval().requires_grad_(False)


@pipeline.predict
def predict(model: L.LightningModule, features: np.ndarray) -> dict:
    """Regress the five control DOFs and hand them to the bus."""
    with torch.inference_mode():
        x = torch.from_numpy(features).float().to(model.device)
        x = x.unsqueeze(0).unsqueeze(0)  # (1, 1, n_ch, INPUT_LENGTH)
        out = model(x).cpu().numpy()[0]  # (5,)
    # `link.bus`, never `link.ensure()`: binding blocks on an RPC and this runs on the
    # predict thread, where a stall is worse than a frame with no bus.
    bus = link.bus
    if bus is None:
        return {}  # nothing resolved yet; nothing to command
    # No clip: each DOF's declared range is the authority, and clipping before the
    # smoother lets the filter overshoot straight back out of it.
    return {"dof": bus.push(dict(zip(DOF_NAMES, out, strict=True)))}


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
        row_height=[Px(52), Fr(2), Px(76), Fr(5), Fr(1.5), Px(110), Px(26)],
        bare=("header", "status"),
    ),
    breakpoint=Px(1100),
)
steps = StepBar(["Connect", "Record", "Train", "Predict"], widget_id="emg_regression_raulnet_steps")
participant = ParticipantPanel()
header = AppHeader("EMG regression · RaulNet", steps=steps, participant=participant)
status = StatusBar("emg", pipeline=pipeline)


def _on_gesture(i: int) -> None:
    # A held state through the same bus the continuous DOFs use: the control hand snaps
    # and holds, so VHI_Control settles to a static value the regressor can map back to.
    bus = link.ensure()
    simulator.set(CTRL_VALUES[i])
    if bus is not None:
        # The states are VHI's own movement names, so "Fist" is not lowercased here.
        bus.select(GESTURE, CLASSES[i])


def _on_record() -> None:
    # The recording aid, not a control command: it gates VHI's local keyboard so the
    # gesture buttons are this session's only movement source.
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


# Connect owns acquisition; the signal and simulator stay visible on every step.
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
training_log = TrainingLog(pipeline, height=0, widget_id="raulnet_training")
predict_button = PredictButton(pipeline, size=(-1, 0))
log = LogPanel(title="Activity log")
connection = {"busy": False, "launch_errors": {}}


def _connect() -> None:
    """Resolve the synthetic EMG stream off the render thread."""
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
    """Keep a process's launch action beside its state, within the Connect card."""
    running = processes.running(name)
    error = connection["launch_errors"].get(name, "")
    tone = SUCCESS if running else DANGER if error else IDLE
    icon = fa.ICON_FA_STOP if running else fa.ICON_FA_PLAY
    style = imgui.get_style()
    action_width = imgui.calc_text_size(icon).x + 2 * style.frame_padding.x
    imgui.text_colored(muted(), fit_text(name, imgui.get_content_region_avail().x))
    imgui.set_item_tooltip(name)
    with tinted_row(tone) as width:
        left = imgui.get_cursor_pos_x()
        imgui.align_text_to_frame_padding()
        detail = "Running" if running else "Launch failed" if error else "Not running"
        imgui.text_unformatted(fit_text(detail, width - action_width - style.item_spacing.x))
        imgui.set_item_tooltip(error or f"Launch {name} before connecting.")
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
                    connection["launch_errors"].pop(name, None)
                except Exception as exc:
                    connection["launch_errors"][name] = str(exc)
                    ctx.log(f"{name} launch failed: {exc}")


def connect_ui(ctx: Context) -> None:
    """Launch the generator and hand, then connect the named EMG stream."""
    for name, _command in PROCESSES:
        _process_ui(ctx, name)
    if not any(name == vhi.name for name, _command in PROCESSES):
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped("Start the Virtual Hand externally to record its motion and drive it.")
        imgui.pop_style_color()
    imgui.spacing()
    caption = f"EMG stream · {STREAM_NAME}"
    imgui.text_colored(muted(), fit_text(caption, imgui.get_content_region_avail().x))
    imgui.set_item_tooltip(caption)
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
    """Keep the training state and epoch log visible throughout the deep-model fit."""
    ctx = app.ctx
    training = ctx.state == "training"
    failed = ctx.status_message.startswith("Training failed: ")
    tone = WARNING if training else DANGER if failed else SUCCESS if pipeline.model is not None else IDLE
    with tinted_row(tone):
        imgui.text_unformatted("Training…" if training else "Training failed" if failed else
                               "Trained" if pipeline.model is not None else "Not trained")
    imgui.push_style_color(imgui.Col_.text, muted())
    imgui.text_wrapped("RaulNet V17 · sliding RMS input. Training can take several minutes.")
    if failed and not training:
        imgui.text_wrapped(ctx.status_message.removeprefix("Training failed: "))
    imgui.pop_style_color()
    train_button.ui()
    imgui.spacing()
    imgui.text_colored(muted(), "Training log")
    training_log.ui()
    if not pipeline.train_log:
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped("Select recorded takes, then Train to follow epoch loss here.")
        imgui.pop_style_color()


def predict_ui() -> None:
    """Show the continuous five-DOF output sent to the hand, with its smoothing."""
    running = app.ctx.state == "predicting"
    with tinted_row(SUCCESS if running else IDLE):
        imgui.text_unformatted("Predicting" if running else "Not predicting")
    output_filter.ui()
    imgui.spacing()
    imgui.text_colored(muted(), "Sent to the hand")
    values = pipeline.predictions.get("dof", {})
    if values:
        for name in DOF_NAMES:
            if name not in values:
                continue
            text = f"{values[name]:+.2f}"
            # Reserve the numeric column so the name and signed value remain readable.
            value_width = imgui.calc_text_size("−0.00").x + ui_px(16)
            right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
            imgui.text_unformatted(fit_text(name, imgui.get_content_region_avail().x - value_width))
            imgui.same_line()
            imgui.set_cursor_pos_x(right - value_width)
            mono_text(text)
    else:
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.text_wrapped("No output yet. Train a model, connect the hand, then Predict.")
        imgui.pop_style_color()
    imgui.spacing()
    predict_button.ui()


def _step_done(ctx: Context) -> list[bool]:
    """Completion follows connection, participant takes, model and prediction."""
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
        link.stop()
        recording_aid.stop_trajectory()
        recording_aid.set_recording_session(False)
        recording_aid.stop()
        vhi_control.stop()


if __name__ == "__main__":
    main()
