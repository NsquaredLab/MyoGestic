"""Regression demo: same Rest/Fist workflow as ``emg_regression.py``, RaulNet model.

Identical experiment to :file:`emg_regression.py` — fake 8-channel EMG +
VHI control hand driven via gRPC, recording while toggling Rest / Fist,
regressing the 5-DOF kinematics target — but the model is RaulNet V17
(a PyTorch Lightning CNN from :mod:`myoverse.models.raul_net`) instead of
CatBoost. Use this to compare a neural-net regressor against the
tree-based one on the same data.

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
from pathlib import Path

import lightning as L
import numpy as np
import torch
from lightning.pytorch.callbacks import ModelCheckpoint, StochasticWeightAveraging
from myoverse.models.raul_net.v17 import RaulNetV17

from myogestic import App, Fr, Grid, Px, Stream, TrainingData
from myogestic.ml import Pipeline
from myogestic.ml.widgets import pipeline_panel
from myogestic.session import iter_aligned_windows, iter_labeled_windows, open_session_store
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.vhi.interfaces import virtual_hand
from myogestic.widgets import (
    FilterControl,
    app_logo,
    process_launcher,
    recording_controls,
    session_manager,
    signal_viewer,
)

# ── Stream / window math ──────────────────────────────────────────────
# Same 8-channel 2048 Hz synthetic EMG the other examples use, with a
# 0.2 s analysis window. RaulNet's sliding-RMS feature uses an RMS_WINDOW_MS
# window (stride 1), shortening it to (8, INPUT_LENGTH) fed to the CNN.

STREAM_NAME = "TestEMG1"
N_CHANNELS = 8
FS = 2048
WIN_SECONDS = 0.2
HOP_SECONDS = 0.1  # 50% overlap

N_WINDOW_SAMPLES = int(WIN_SECONDS * FS)
RMS_WINDOW_MS = 60  # sliding-RMS window, in ms
RMS_WINDOW_SAMPLES = round(RMS_WINDOW_MS / 1000 * FS)
RMS_STRIDE = 1
INPUT_LENGTH = (N_WINDOW_SAMPLES - RMS_WINDOW_SAMPLES) // RMS_STRIDE + 1

# 5 VHI DOFs (mosaic-2.0 registry): wrist rotation + index/middle/ring/pinky.
VHI_DOF_INDICES = [0, 2, 3, 4, 5]
N_DOF = len(VHI_DOF_INDICES)

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
    if RMS_STRIDE > 1:
        s = s[:, ::RMS_STRIDE]
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
vhi_client = vhi.control_client()

# Output-side smoothing applied to the 9-DOF hand vector before pushing
# to VHI. Live-tunable via the FilterControl widget rendered in the UI.
output_filter = FilterControl(hz=32, default="one_euro")

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
    # vhi.launcher() returns a [(name, argv)] entry; splat it so EMG
    # Generator and VHI Hand share a single launcher panel.
    *vhi.launcher(),
]

app = App("EMG Regression — RaulNet", ui_scale=0.85)
app.streams(
    Stream("emg", source=LSLSource(STREAM_NAME), window_seconds=WIN_SECONDS, buffer_seconds=60),
    Stream(
        "vhi_control",
        source=LSLSource(vhi.control_stream or "VHI_Control"),
        window_seconds=1.0,
        buffer_seconds=60,
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
        if "vhi_control" in sess.stores:
            kin_paths.append(p)
        else:
            label_paths.append(p)

    X_list: list[np.ndarray] = []
    y_list: list[np.ndarray] = []

    for emg_window, aligned, _ts in iter_aligned_windows(
        kin_paths,
        "emg",
        ["vhi_control"],
        WIN_SECONDS,
        HOP_SECONDS,
        align_window_samples=10,
    ):
        X_list.append(sliding_rms(emg_window))
        y_list.append(np.abs(aligned["vhi_control"][VHI_DOF_INDICES]))
    if kin_paths:
        log.append(f"  kinematics: {len(X_list)} windows from {len(kin_paths)} sessions")

    n_before_labels = len(X_list)
    for emg_window, _ts, ci in iter_labeled_windows(
        label_paths,
        "emg",
        WIN_SECONDS,
        HOP_SECONDS,
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
    """Regress 5-DOF → expand to 9-DOF (negated) → smooth → push to VHI."""
    with torch.inference_mode():
        x = torch.from_numpy(features).float().to(model.device)
        x = x.unsqueeze(0).unsqueeze(0)  # (1, 1, n_ch, INPUT_LENGTH)
        out = model(x).cpu().numpy()[0]  # (5,)
    pred_5dof = np.clip(out, 0, 1)

    pred_9dof = np.zeros(9, dtype=np.float32)
    for i, vhi_idx in enumerate(VHI_DOF_INDICES):
        pred_9dof[vhi_idx] = -pred_5dof[i]

    pred_9dof = output_filter(pred_9dof).astype(np.float32)
    vhi_outlet.push(pred_9dof)
    return {"dof": pred_5dof, "hand": pred_9dof}


LOGO_CELL_W = 300
WORDMARK_ASPECT = 800 / 540
grid = Grid(
    6,
    3,
    row_height=[Px(LOGO_CELL_W / WORDMARK_ASPECT), *[Fr(1)] * 5],
    col_width=[Px(LOGO_CELL_W), Fr(1), Fr(1)],
)


def _on_gesture(i: int) -> None:
    # cycle=False: snap to the movement's end pose and hold it. VHI_Control
    # settles to a static kinematic value per gesture, which the regressor
    # learns to map back from the corresponding EMG amplitude.
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore
    vhi_client.set_movement(CLASSES[i], cycle=False)


def _on_record() -> None:
    # While recording, VHI ignores its local keyboard so MyoGestic's gesture
    # buttons are the sole movement source for the session.
    app.start_recording()
    vhi_client.set_session_active(True)


def _on_stop() -> None:
    app.stop_recording()
    vhi_client.set_session_active(False)


@app.ui
def demo_ui(ctx):
    with grid[0:6, 1:3]:
        signal_viewer(ctx, "emg")

    with grid[0, 0]:
        app_logo()

    with grid[1, 0]:
        process_launcher(PROCESSES)

    with grid[2, 0]:
        recording_controls(
            ctx,
            CLASSES,
            on_record=_on_record,
            on_stop=_on_stop,
            on_gesture=_on_gesture,
        )

    with grid[3, 0]:
        pipeline.training_data = session_manager("sessions", class_names=CLASSES)

    with grid[4, 0]:
        pipeline_panel(pipeline)

    with grid[5, 0]:
        output_filter.ui()


def main() -> None:
    try:
        app.run()
    finally:
        vhi_client.stop()


if __name__ == "__main__":
    main()
