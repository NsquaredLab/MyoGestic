"""Regression demo: same Rest/Fist workflow as ``emg_regression.py``, RaulNet model.

Identical experiment to :file:`emg_regression.py` — fake 8-channel EMG +
VHI control hand driven via gRPC, recording while toggling Rest / Fist,
regressing the 5-DOF kinematics target — but the model is RaulNet V17
(a PyTorch Lightning CNN from :mod:`myoverse.models.raul_net`) instead of
CatBoost. Use this to compare a neural-net regressor against the
tree-based one on the same data.

The control space is declared in :file:`examples/controls/regression_raulnet.toml` — your
aliases on the left, VHI's addresses on the right — and resolves against a *running* VHI,
so nothing here hard-codes what a control means.

Run with:
    uv run --extra examples --extra grpc python examples/synthetic/emg_regression_raulnet.py

Workflow (mirrors examples/synthetic/emg_regression.py):
    1. Launch EMG Generator + VHI Hand
    2. Click Rest or Fist → MyoGestic drives the VHI control hand over
       gRPC and snaps it to the end pose
    3. Click Record → VHI's local keyboard is gated off for the session;
       the buttons above are the sole movement source → Stop Rec
    4. Repeat for several recordings (RaulNet wants more data than CatBoost)
    5. Tick the sessions → Train (CNN, ~50 epochs)
    6. Predict → VHI predicted hand mirrors the control hand

Requirements:
    uv sync --extra examples --extra grpc
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import lightning as L
import numpy as np
import torch
from lightning.pytorch.callbacks import ModelCheckpoint, StochasticWeightAveraging
from myoverse.models.raul_net.v17 import RaulNetV17

from myogestic import App, Fr, Grid, Px, Stream, TrainingData
from myogestic.controls import ControlBus, load_control_map, resolve
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PipelinePanel
from myogestic.session import iter_aligned_windows, iter_labeled_windows, open_session_store
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.vhi import VhiTarget, virtual_hand
from myogestic.vhi.legacy import decode_pose
from myogestic.widgets import (
    AppLogo,
    PostProcessor,
    ProcessLauncher,
    RecordingControls,
    SessionManager,
    SignalViewer,
)

# ── Stream / window math ──────────────────────────────────────────────
# Same 8-channel 2048 Hz synthetic EMG the other examples use, with a
# 200 ms analysis window. RaulNet's sliding-RMS feature runs an RMS_WINDOW_MS
# window at an RMS_STRIDE_MS step, shortening it to (8, INPUT_LENGTH) for the CNN.

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

CLASSES = ["Rest", "Fist"]
CTRL_VALUES = [0.0, 1.0]


def sliding_rms(emg: np.ndarray) -> np.ndarray:
    """Per-channel sliding RMS, ``(n_channels, INPUT_LENGTH)`` always.

    Left-pads with zeros when the input was shorter than the RMS kernel
    or shorter than ``INPUT_LENGTH`` — keeps the model's input shape
    stable even on the first frames where the ring buffer isn't full yet.
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


ctrl_outlet = control_outlet()

vhi = virtual_hand()
vhi_outlet = vhi.outlet()
# The recording aid (session gate, trajectory playback) and the control client.
recording_aid = vhi.recording_client()
vhi_control = vhi.control_client()

# Which control each of the network's five outputs drives. The aliases on the left are
# ours and must match regression_raulnet.toml; the names on the right are what
# `decode_pose` calls the channels of a recorded VHI_Control frame, i.e. the training
# target. There is no wrist on that wire at all — channel 0 is thumb flexion.
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

# Output-side smoothing, applied by the control bus to the control vector.
# Live-tunable via the PostProcessor widget rendered in the UI.
output_filter = PostProcessor(hz=32)

# The bus is built lazily, in `_ensure_vhi`. Every semantic the map needs — whether an
# address takes a number or a held state, its range, its states — is VHI's to declare, and
# VHI does not exist yet: this app launches it from its own ProcessLauncher.
vhi_target = None
bus = None

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
    # vhi.launchable() returns a [(name, argv)] entry; splat it so EMG Generator and VHI
    # Hand share one launcher panel. `launchable` rather than `launcher` because an
    # unlaunchable renderer must not stop this app from opening — a running one needs no
    # button, and the reason is logged either way.
    *vhi.launchable(),
]

app = App("EMG Regression — RaulNet", ui_scale=0.85)
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


@pipeline.extract
def extract(windows) -> np.ndarray:
    """RMS-feature stack of shape ``(n_channels, INPUT_LENGTH)``."""
    return sliding_rms(windows["emg"])


class _TrainLogCallback(L.Callback):
    """Pipe Lightning's per-epoch loss into ``pipeline.train_log``.

    Lightning's default progress bar is disabled for this app (it spams
    stdout); the in-UI log is the only place the user sees training
    progress, so without this callback the MODEL panel stays static
    until the whole 50-epoch fit finishes.
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

    Mirrors ``emg_regression.py``: sessions with a ``vhi_control`` stream
    use ``iter_aligned_windows`` for the real kinematics target; sessions
    without it fall back to synthetic class-derived targets (Fist→all 1s,
    Rest→all 0s).
    """
    log = pipeline.train_log
    log.clear()
    log.append(f"Training from {len(data.paths)} sessions...")

    kin_paths: list[str] = []
    label_paths: list[str] = []
    for p in data.paths:
        try:
            sess = open_session_store(p)
        except Exception as e:
            log.append(f"  skip {p}: {e}")
            continue
        has_kin = "vhi_control" in sess.stores
        sess.close()  # only needed the store list — release the .session.zip handle
        if has_kin:
            kin_paths.append(p)
        else:
            label_paths.append(p)

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
        # decode_pose reads the recorded pose as control values, so the training
        # target is in exactly the space `predict` commands. A signed negation, not
        # the old abs() — which folded extension into flexion of equal magnitude.
        pose = decode_pose(aligned["vhi_control"])
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
    loader = torch.utils.data.DataLoader(
        dataset,
        batch_size=64,
        shuffle=True,
        num_workers=0,
        pin_memory=True,
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
        event_search_kernel_length=31,
        event_search_kernel_stride=8,
    )

    torch.set_float32_matmul_precision("medium")
    Path("data/logs").mkdir(parents=True, exist_ok=True)
    # precision="32-true": RaulNet's TorchScript-compiled backward graph
    # has hard-coded dtype checks that don't tolerate ANY mixed-precision
    # autocast — both fp16-mixed and bf16-mixed trip the same
    # "mat1 and mat2 different dtype" assertion. Full fp32 sidesteps it.
    # On Apple Silicon (MPS) the loss-of-bf16 throughput is small; on CUDA
    # bump to fp16-mixed if you've patched RaulNet's traced ops.
    trainer = L.Trainer(
        accelerator="auto",
        devices=1,
        precision="32-true",
        max_epochs=50,
        # log_every_n_steps=1 so callback_metrics is populated even when
        # an epoch is a single batch (small training-set demo case).
        log_every_n_steps=1,
        callbacks=[
            StochasticWeightAveraging(
                swa_lrs=1e-4,
                swa_epoch_start=0.5,
                annealing_epochs=5,
            ),
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
    if bus is None:
        return {}  # nothing resolved yet; nothing to command
    # No clip: each DOF's declared range is the authority, and clipping before the
    # smoother lets the filter overshoot straight back out of it.
    return {"dof": bus.push(dict(zip(DOF_NAMES, out, strict=True)))}


LOGO_CELL_W = 300
WORDMARK_ASPECT = 800 / 540
grid = Grid(
    6,
    3,
    row_height=[Px(LOGO_CELL_W / WORDMARK_ASPECT), *[Fr(1)] * 5],
    col_width=[Px(LOGO_CELL_W), Fr(1), Fr(1)],
)


def _ensure_vhi() -> None:
    """Resolve the control map once VHI is up and can say what it exports."""
    global bus, vhi_target
    if bus is not None:
        return
    capabilities = vhi_control.capabilities()
    if capabilities is None:
        app.ctx.log("VHI not reachable yet — controls stay unresolved")
        return
    controls = resolve(CONTROL_MAP, capabilities)
    unknown = [name for name in (*DOF_NAMES, GESTURE) if name not in controls.dofs]
    if unknown:
        # Caught here rather than as a hand that quietly holds rest: the bus substitutes
        # rest for an alias it does not know, so a renamed alias would look like a model
        # predicting nothing.
        raise ValueError(
            f"{CONTROL_FILE.name} does not declare {unknown}, but this example pushes "
            f"those aliases. It declares: {sorted(controls.dofs)}."
        )
    vhi_target = VhiTarget(vhi_outlet, client=vhi_control)
    # One bus owns the output path: substitute rest -> clip -> smooth -> clip again ->
    # deliver. VhiTarget negotiates the space and refuses a VHI it cannot fully drive.
    bus = ControlBus(controls, targets=[vhi_target], smoothing=output_filter, hz=32)
    # Recordings then carry the space they were made under: a bare -1 does not say
    # whether it was a full excursion or out of range.
    app.ctx.control_space = CONTROL_MAP
    app.ctx.log(f"resolved {len(controls.dofs)} controls against VHI")


def _on_gesture(i: int) -> None:
    # A discrete held state through the same bus the continuous DOFs use. The
    # control hand snaps to the pose and holds it, so VHI_Control settles to a static
    # kinematic value the regressor can map back from EMG amplitude.
    _ensure_vhi()
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore
    if bus is not None:
        # The states are VHI's own movement names, so "Fist" is not lowercased here.
        bus.select(GESTURE, CLASSES[i])


def _on_record() -> None:
    # The recording aid, not a control command: it gates VHI's local keyboard so the
    # gesture buttons are this session's only movement source.
    _ensure_vhi()
    app.start_recording()
    if not recording_aid.set_recording_session(True):
        app.ctx.log("VHI recording-session gate unavailable — keyboard is not blocked")


def _on_stop() -> None:
    app.stop_recording()
    recording_aid.set_recording_session(False)


viewer = SignalViewer("emg")
logo = AppLogo()
processes = ProcessLauncher(PROCESSES)
recording = RecordingControls(
    CLASSES,
    on_record=_on_record,
    on_stop=_on_stop,
    on_gesture=_on_gesture,
)
sessions = SessionManager("sessions", class_names=CLASSES)
panel = PipelinePanel(pipeline)


@app.ui
def demo_ui(ctx):
    with grid[0:6, 1:3]:
        viewer.ui(ctx)

    with grid[0, 0]:
        logo.ui()

    with grid[1, 0]:
        processes.ui()

    with grid[2, 0]:
        recording.ui(ctx)

    with grid[3, 0]:
        pipeline.training_data = sessions.ui()

    with grid[4, 0]:
        panel.ui()

    with grid[5, 0]:
        output_filter.ui()


def main() -> None:
    try:
        app.run()
    finally:
        if bus is not None:
            bus.stop()
        recording_aid.stop_trajectory()
        recording_aid.set_recording_session(False)
        recording_aid.stop()
        vhi_control.stop()


if __name__ == "__main__":
    main()
