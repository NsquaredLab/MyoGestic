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
from myogestic.controls import ControlBus, load_dofs
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PipelinePanel
from myogestic.recipes.estimators import catboost_regressor
from myogestic.session import iter_aligned_windows, iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.vhi import VhiTarget, virtual_hand
from myogestic.vhi.legacy import decode_pose
from myogestic.widgets import (
    AppLogo,
    LogPanel,
    PostProcessor,
    ProcessLauncher,
    SessionManager,
    SignalViewer,
    StreamPanel,
)
from myogestic.widgets.panels.recording import RecordingControls

ctrl_outlet = control_outlet()
CLASSES = ["Rest", "Fist"]
CTRL_VALUES = [0.0, 1.0]

vhi = virtual_hand()
vhi_outlet = vhi.outlet()
vhi_client = vhi.control_client()

# Output-side smoothing, applied by the control bus to the canonical vector.
# Live-tunable via the PostProcessor widget rendered in the UI.
output_filter = PostProcessor(hz=32)

# The canonical control space this app commands. Five signed, normalized DOFs:
# +1 is the direction the name says (full flexion), -1 the opposite, 0 rest.
# Thumb abduction is left out to keep the regressor manageable on fake EMG.
#
# No VHI channel number appears here, and none should: `VhiTarget` owns the
# translation to whatever the hand happens to want on the wire.
# --8<-- [start:dofs]
CONTROLS = load_dofs(
    {
        "dofs": dict.fromkeys(
            [
                "thumb.flexion",
                "index.flexion",
                "middle.flexion",
                "ring.flexion",
                "little.flexion",
            ],
            "continuous",
        )
    }
)
DOF_NAMES = CONTROLS.channel_labels()
N_DOF = len(DOF_NAMES)
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

# --8<-- [start:bus]
# One bus owns the whole output path: substitute rest -> clip -> smooth ->
# clip again -> hand it to every target. `VhiTarget` is what turns canonical
# names into whatever this VHI renders.
#
# Passing a canonical client makes the target *ask* rather than assume: against a
# v2 VHI it negotiates the channel layout by name, and against an older one it
# falls back to the legacy pose on its own. Nothing below changes either way.
vhi_canonical = vhi.canonical_client()
vhi_target = VhiTarget(vhi_outlet, client=vhi_canonical)
bus = ControlBus(CONTROLS, targets=[vhi_target], smoothing=output_filter, hz=32)
# --8<-- [end:bus]

app = App("EMG Regression", ui_scale=0.85)
# Recordings then carry the space they were made under: a bare -1 does not say
# whether it was a full excursion or out of range.
app.ctx.control_space = CONTROLS
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
        # decode_pose reads VHI's recorded pose as canonical values, so the
        # training target is in exactly the space `predict` commands. It is a
        # signed negation, not the old `abs()` - which folded any extension the
        # operator did into flexion of the same magnitude.
        pose = decode_pose(aligned["vhi_control"])
        kin = np.array([pose[name] for name in DOF_NAMES], dtype=np.float64)
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
        # +1 is flexion under the canonical standard, so a Fist target is all 1s
        # and Rest is all 0s - the same numbers as before, now for a stated reason.
        kin = np.ones(N_DOF, dtype=np.float64) if ci == 1 else np.zeros(N_DOF, dtype=np.float64)
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
    """Regress the five canonical DOFs and hand them to the bus."""
    pred = model.predict(features.reshape(1, -1))[0]
    # The bus sanitises, smooths and renders. No clip here: each DOF's declared
    # range is the authority, and clipping before the smoother would let the
    # filter overshoot straight back out of it.
    return {"dof": bus.push(dict(zip(DOF_NAMES, pred, strict=True)))}


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


viewer = SignalViewer("emg", selectable=True)
streams = StreamPanel()
log = LogPanel()
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
    with grid[0:4, 1:3]:
        viewer.ui(ctx)

    with grid[4:6, 1:2]:
        streams.ui(ctx)

    with grid[4:6, 2:3]:
        log.ui(ctx)

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
        # Rest the hand first, and make that frame land: the outlet sends on a
        # paced thread, so a pose pushed at exit would otherwise never go out
        # and the hand would hold its last commanded position.
        bus.stop()
        vhi_client.stop()
        vhi_canonical.stop()


if __name__ == "__main__":
    main()
