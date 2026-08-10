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

The control space lives in `examples/controls/regression.toml` — our aliases on the left,
VHI's addresses on the right. VHI declares what they accept, so nothing resolves until it runs.
"""

import pathlib
import sys
import tomllib

import numpy as np
import torch
from myoverse.transforms import MAV, RMS, WaveformLength

from myogestic import App, Fr, Grid, Px, Stream, TrainingData
from myogestic.controls import ControlLink, load_control_map
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PipelinePanel
from myogestic.recipes.estimators import catboost_regressor
from myogestic.remote import RemoteTarget
from myogestic.session import (
    iter_aligned_windows,
    iter_labeled_windows,
    split_sessions_by_stream,
)
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.vhi import virtual_hand
from myogestic.vhi.pose import ADDRESS_CHANNELS, POSE_DOFS, split_pose
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
LOGO_CELL_W = 300
WORDMARK_ASPECT = 800 / 540
grid = Grid(
    6,
    3,
    row_height=[Px(LOGO_CELL_W / WORDMARK_ASPECT), *[Fr(1)] * 5],
    col_width=[Px(LOGO_CELL_W), Fr(1), Fr(1)],
)
# --8<-- [end:grid]


# --8<-- [start:gesture]
def _on_gesture(i: int) -> None:
    # Holding the pose makes VHI_Control settle to one static value per gesture — that
    # constant is what the regressor learns to map EMG amplitude back to. `bus.select`
    # skips the debounce and rebases the trigger so the next push does not re-fire it.
    bus = link.ensure()
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore
    if bus is not None:
        # `CLASSES` must name VHI's own movements; `select` returns False if one does not.
        bus.select("gesture", CLASSES[i])
# --8<-- [end:gesture]


# --8<-- [start:record]
def _on_record() -> None:
    # Gates VHI's local keyboard so the gesture buttons are the session's only movement
    # source. False means this VHI has no v2 aid — an ungated take picks up stray keys.
    link.ensure()
    app.start_recording()
    if not recording_aid.set_recording_session(True):
        app.ctx.log("VHI recording-session gate unavailable — keyboard is not blocked")


def _on_stop() -> None:
    app.stop_recording()
    recording_aid.set_recording_session(False)
# --8<-- [end:record]


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
        # `link.stop()` first, and it waits: the outlet sends on a paced thread, so the rest
        # pose it pushes at exit would otherwise never go out and the hand would hold.
        link.stop()
        recording_aid.stop_trajectory()      # no-op unless a trajectory was started
        recording_aid.set_recording_session(False)
        recording_aid.stop()
        vhi_control.stop()


if __name__ == "__main__":
    main()
