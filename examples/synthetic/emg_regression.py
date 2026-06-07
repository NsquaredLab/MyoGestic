"""Regression demo: EMG + VHI control hand → MyoVerse features → CatBoost Regressor → VHI predicted hand.

Run with:
    uv run --extra examples --extra grpc python examples/synthetic/emg_regression.py

Workflow:
    1. Launch EMG Generator + VHI Hand
    2. Click a gesture button → MyoGestic drives the VHI control hand over gRPC
    3. Click Record → VHI's local keyboard control is disabled for the session,
       so the gesture buttons are the sole movement source → Stop Rec
    4. Select sessions → Train (regression on kinematics)
    5. Predict → VHI predicted hand mirrors control hand
"""

import sys

import numpy as np
import torch
from myoverse.transforms import MAV, RMS, WaveformLength

from myogestic import App, Fr, Grid, Px, Stream, TrainingData
from myogestic.ml import Pipeline
from myogestic.ml.widgets import pipeline_panel
from myogestic.recipes.estimators import catboost_regressor
from myogestic.session import iter_aligned_windows, iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.vhi.interfaces import virtual_hand
from myogestic.widgets import (
    app_logo,
    log_panel,
    process_launcher,
    session_manager,
    signal_viewer,
    stream_panel,
)
from myogestic.widgets.panels.filter_controls import FilterControl
from myogestic.widgets.panels.recording import recording_controls

ctrl_outlet = control_outlet()
CLASSES = ["Rest", "Fist"]
CTRL_VALUES = [0.0, 1.0]

vhi = virtual_hand()
vhi_outlet = vhi.outlet()
vhi_client = vhi.control_client()

# Output-side smoothing applied to the 9-DOF hand vector before pushing
# to VHI. Live-tunable via the FilterControl widget rendered in the UI.
output_filter = FilterControl(hz=32, default="one_euro")

# Mosaic-2.0 registry indices; selecting these from VHI_Control during
# training gives a 5-DOF target (WristRot + 4 fingers) instead of the full
# 9-DOF vector, which keeps the regressor manageable for a fake-EMG demo.
# --8<-- [start:dofs]
VHI_DOF_INDICES = [0, 2, 3, 4, 5]
N_DOF = len(VHI_DOF_INDICES)
# --8<-- [end:dofs]

# MyoVerse transforms — preferred over hand-rolled numpy here so the feature
# extraction stays compatible with downstream MyoGestic models.
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
    # vhi.launcher() returns a [(name, argv)] entry; splat it so EMG
    # Generator and VHI Hand share a single launcher panel.
    *vhi.launcher(),
]

app = App("EMG Regression", ui_scale=0.85)
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
    """Train CatBoost regressor: EMG features → 5-DOF kinematics.

    For sessions with `vhi_control` kinematics: use iter_aligned_windows
    (EMG window → kinematics target via timestamp alignment).

    For sessions without kinematics (labels-only): use iter_labeled_windows
    with a synthetic target (rest=0, fist=1).

    Both helpers transparently handle folder + .session.zip layouts.
    """
    log = pipeline.train_log
    log.clear()
    log.append(f"Training from {len(data.paths)} sessions...")

    all_X: list[np.ndarray] = []
    all_y: list[np.ndarray] = []

    # Sessions with kinematics — primary input EMG, regress to kinematics
    kin_paths = []
    label_paths = []
    for p in data.paths:
        try:
            from myogestic.session import open_session_store

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

    # Kinematics path
    # --8<-- [start:kin_loop]
    for emg_window, aligned, _ts in iter_aligned_windows(
        kin_paths,
        "emg",
        ["vhi_control"],
        WINDOW_MS,
        HOP_MS,
        n_alignment_samples=10,
    ):
        kin = np.abs(aligned["vhi_control"][VHI_DOF_INDICES])
        all_X.append(extract_features(emg_window))
        all_y.append(kin)
    # --8<-- [end:kin_loop]
    if kin_paths:
        log.append(f"  kinematics: {len(all_X)} windows from {len(kin_paths)} sessions")

    # Label fallback: synthetic targets (class==1 → all 1s, else 0s).
    # Honor the class chips here too — synthetic targets only get computed
    # for active classes.
    n_before_labels = len(all_X)
    # --8<-- [start:label_loop]
    for emg_window, _ts, ci in iter_labeled_windows(
        label_paths,
        "emg",
        WINDOW_MS,
        HOP_MS,
        classes=data.classes if data.classes else None,
    ):
        kin = np.ones(5, dtype=np.float64) if ci == 1 else np.zeros(5, dtype=np.float64)
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
    """Regress 5-DOF → expand to 9-DOF → smooth → push to VHI."""
    pred_5dof = model.predict(features.reshape(1, -1))[0]
    pred_5dof = np.clip(pred_5dof, 0, 1)

    # Expand to 9-DOF and negate for VHI
    # --8<-- [start:expand]
    pred_9dof = np.zeros(9, dtype=np.float32)
    for i, vhi_idx in enumerate(VHI_DOF_INDICES):
        pred_9dof[vhi_idx] = -pred_5dof[i]
    # --8<-- [end:expand]

    pred_9dof = output_filter(pred_9dof).astype(np.float32)
    vhi_outlet.push(pred_9dof)
    return {"dof": pred_5dof, "hand": pred_9dof}
# --8<-- [end:predict]


# Branding cell pinned to the wordmark aspect; cols 1+2 are Fr so the
# signal viewer + stream/log panels grow with window width.
# --8<-- [start:grid]
LOGO_CELL_W = 300
WORDMARK_ASPECT = 800 / 540
grid = Grid(
    6,
    3,
    row_height=[Px(LOGO_CELL_W / WORDMARK_ASPECT), *[Fr(1)] * 5],
    col_width=[Px(LOGO_CELL_W), Fr(1), Fr(1)],
)
# --8<-- [end:grid]


def _on_gesture(i: int) -> None:
    # cycle=False: snap to the movement's end pose and hold it. VHI_Control
    # settles to a static kinematic value per gesture (e.g. all-flexed for
    # Fist, all-zero for Rest), which the regressor learns to map back from
    # the corresponding EMG amplitude. CLASSES names are sent verbatim to
    # VHI; unknown names are rejected harmlessly (client logs the ack).
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
    with grid[0:4, 1:3]:
        signal_viewer(ctx, "emg", selectable=True)

    with grid[4:6, 1:2]:
        stream_panel(ctx)

    with grid[4:6, 2:3]:
        log_panel(ctx)

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
