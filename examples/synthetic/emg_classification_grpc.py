"""Classification demo: fake EMG → numpy features → CatBoost → VHI two ways.

A normal MyoGestic classification example — it streams the classified hand
*pose* to VHI's predicted hand over LSL (``MyoGestic_Output``) — that ALSO
showcases the gRPC control plane: on each predicted-class *change* it sends a
discrete ``SetMovement`` command to VHI's control hand. Same classification,
output both ways — the continuous LSL stream and the discrete gRPC command.

Run with:
    uv run --extra examples --extra grpc python examples/synthetic/emg_classification_grpc.py

Workflow:
    1. Launch "EMG Generator" + "VHI Hand"
    2. Click Rest/Fist (or any button in the VHI Movements palette) → drives the
       fake signal and the VHI control hand
    3. Record Rest trial → Record Fist trial  (while recording, VHI's local
       keyboard is disabled so MyoGestic is the sole movement source)
    4. Select sessions → Train → Predict → the predicted hand follows the
       classification (LSL), and each class *change* also commands the control
       hand (gRPC)
"""

import sys

import numpy as np

from myogestic import App, Fr, Grid, Px, Stream, TrainingData
from myogestic.controls import ControlBus, load_dofs
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PipelinePanel
from myogestic.recipes.estimators import catboost_classifier
from myogestic.recipes.features import mav, rms, var, wl
from myogestic.session import iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.vhi import VhiTarget, virtual_hand
from myogestic.vhi.legacy import LEGACY_POSE_DOFS
from myogestic.widgets import (
    AppLogo,
    FeatureSelector,
    PostProcessor,
    PredictionLabel,
    ProcessLauncher,
    RecordingControls,
    SessionManager,
    SignalViewer,
    VhiMovementPanel,
)

ctrl_outlet = control_outlet()

vhi = virtual_hand()
vhi_outlet = vhi.outlet()
# The v2 recording aid (session gate) and the canonical client. `vhi_legacy` renders
# the discrete gesture only on a pre-v2 VHI; it goes away with v1.
training_aid = vhi.training_client()
vhi_canonical = vhi.canonical_client()
vhi_legacy = vhi.control_client()

# Per-class poses in canonical DOF values: +1 is the direction the name says, 0 is
# rest. The fist abducts the thumb — channel 1 used to be written as 0 here, but
# recorded VHI sessions have it at full excursion.
HAND_REST: dict[str, float] = {}
HAND_FIST = dict.fromkeys(LEGACY_POSE_DOFS, 1.0)

# Output-side smoothing applied to the hand pose vector before pushing
# to VHI. Live-tunable via the PostProcessor widget rendered in the UI.
output_filter = PostProcessor(hz=32)

# CLASSES are sent verbatim to VHI as movement names — keep them in sync
# with VHI's movement set (see MovementDefinitions.cs). "Rest" and "Fist"
# are both valid VHI movements; the fake generator only produces two
# amplitude levels, so two classes is also what it can cleanly drive.
CLASSES = ["Rest", "Fist"]
CTRL_VALUES = [0.0, 1.0]


# Reference RMS / MAV / WL / VAR live in myogestic.recipes.features; mix
# with your own callables here — feature engineering is user code, this is
# the seam where you'd add custom ones.
features = FeatureSelector(
    {"RMS": rms, "MAV": mav, "WL": wl, "VAR": var},
    default=["RMS", "MAV"],
)

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

WINDOW_MS = 200
HOP_MS = 100

app = App("EMG Classification (gRPC)", ui_scale=0.85)
app.streams(Stream("emg", source=LSLSource("TestEMG1"), window_ms=WINDOW_MS, buffer_ms=60000))
pipeline = Pipeline(app)


@pipeline.extract
def extract(windows: dict[str, np.ndarray]) -> np.ndarray:
    """Active features stacked along axis 0 → flat feature vector."""
    return features(windows["emg"])


@pipeline.train
def train(data: TrainingData):
    """Train a CatBoost classifier on numpy features from selected sessions."""
    if data.is_empty:
        raise ValueError("No sessions selected. Load some and tick the checkboxes.")
    if len(data.classes) < 2:
        raise ValueError(
            f"Classification needs ≥2 active classes — got {len(data.classes)}. "
            f"Toggle more class chips on."
        )
    if features.n_active == 0:
        raise ValueError("No features ticked in the FEATURES panel (RMS+MAV is the default).")

    all_X: list[np.ndarray] = []
    all_y: list[int] = []
    for window, _ts, class_idx in iter_labeled_windows(
        data.paths, "emg", WINDOW_MS, HOP_MS, classes=data.classes
    ):
        all_X.append(extract({"emg": window}))
        all_y.append(class_idx)

    print(f"[train] {len(all_X)} windows from {len(data.paths)} sessions")
    if len(all_X) < 2:
        raise ValueError(f"Need at least 2 windows, got {len(all_X)}")

    X = np.stack(all_X)
    y = np.array(all_y)
    if len(np.unique(y)) < 2:
        raise ValueError(f"Need at least 2 classes, got {len(np.unique(y))}")

    clf = catboost_classifier(iterations=100)
    clf.fit(X, y)
    print(f"[train] done — train accuracy: {clf.score(X, y):.2%}")
    return clf


# Commanding a movement re-triggers VHI's animation, so it must happen only when the
# class actually changes *and has settled*: the tick-to-tick argmax flickers during
# the ~0.2 s sliding-window transition after a gesture, and without a debounce the
# control hand visibly jumps between poses before settling.
#
# That debounce is a property of the DOF, so it is declared on the DOF rather than
# hand-rolled around the client — the bus owns the edge detection, the dedupe, and
# the rebase-on-manual-click that used to live in this file.
STABLE_SECONDS = 0.1
CONTROLS = load_dofs(
    {
        "dofs": {
            **dict.fromkeys(LEGACY_POSE_DOFS, "continuous"),
            "hand.gesture": {
                "kind": "discrete",
                "states": [c.lower() for c in CLASSES],
                "rest": CLASSES[0].lower(),
                "debounce_s": STABLE_SECONDS,
            },
        }
    }
)
vhi_target = VhiTarget(vhi_outlet, client=vhi_canonical, legacy_client=vhi_legacy)
bus = ControlBus(
    CONTROLS,
    targets=[vhi_target],
    smoothing=output_filter,
    hz=pipeline.predict_hz,
)


@pipeline.predict
def predict(model, features):
    """Classify, then output it two ways: stream the hand pose to VHI's
    predicted hand (LSL), and on each class *change* command the control
    hand (gRPC)."""
    proba = model.predict_proba(features.reshape(1, -1))[0]
    class_idx = int(np.argmax(proba))

    # One frame carries both outputs: the pose streams to the predicted hand, and
    # the gesture is delivered to the control hand only when it has settled. The bus
    # does the debounce declared on the DOF, so there is no trigger to drive here.
    pose = HAND_FIST if class_idx == 1 else HAND_REST
    values = bus.push({**pose, "hand.gesture": CLASSES[class_idx].lower()})

    return {"class": class_idx, "proba": proba, "hand": values}


# Branding cell is FIXED-pixel in both axes so it stays sized to the
# wordmark regardless of window dimensions:
#   * col 0 → Px(300) wide
#   * row 0 → Px(300 / 1.48) ≈ Px(203) tall (matches the wordmark aspect)
# Everything else uses Fr to share leftover space: cols 1+2 split width
# equally, rows 1-8 split height equally.
LOGO_CELL_W = 300
WORDMARK_ASPECT = 800 / 540
grid = Grid(
    9,
    3,
    row_height=[Px(LOGO_CELL_W / WORDMARK_ASPECT), *[Fr(1)] * 8],
    col_width=[Px(LOGO_CELL_W), Fr(1), Fr(1)],
)


def _ensure_vhi() -> None:
    """Settle the target's contract once VHI is up — bind ran before it existed."""
    if not vhi_target.negotiate():
        app.ctx.log("VHI not reachable yet — gestures will not render until it is")


def _on_gesture(i: int) -> None:
    """Manual class button: drive the fake generator and the VHI control hand."""
    _ensure_vhi()
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore
    # `select` delivers immediately and rebases the DOF's trigger, so the next
    # predict ticks — still on the old ~0.2 s window — do not re-fire or jump.
    bus.select("hand.gesture", CLASSES[i].lower())


def _on_record() -> None:
    """The recording aid gates VHI's keyboard so MyoGestic is the sole authority."""
    _ensure_vhi()
    app.start_recording()
    if not training_aid.set_recording_session(True):
        app.ctx.log("VHI recording-session gate unavailable — keyboard is not blocked")


def _on_stop() -> None:
    app.stop_recording()
    training_aid.set_recording_session(False)


# VhiMovementPanel owns its own state cache and the throttled background
# get_state() refresh, so the @app.ui body stays free of plumbing.
vhi_panel = VhiMovementPanel(
    training_aid,
    # Clicks go through the canonical DOF, not straight at the renderer: `select`
    # delivers immediately and rebases the DOF's debounce so the next predict ticks
    # do not re-fire.
    lambda state: bus.select("hand.gesture", state.lower()),
)

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
prediction = PredictionLabel(pipeline, CLASSES)


@app.ui
def demo_ui(ctx):
    with grid[0:9, 1:3]:
        viewer.ui(ctx)

    with grid[0, 0]:
        # No size cap — let the wordmark grow to the cell. The widget
        # fits-in-rect (preserving aspect), so the image always renders
        # at the largest aspect-preserving box that fits the current
        # cell dimensions and centres itself.
        logo.ui()

    with grid[1, 0]:
        processes.ui()

    with grid[2, 0]:
        recording.ui(ctx)

    with grid[3, 0]:
        features.ui()

    with grid[4, 0]:
        pipeline.training_data = sessions.ui()

    with grid[5, 0]:
        panel.ui()

    with grid[6, 0]:
        output_filter.ui()

    with grid[7, 0]:
        prediction.ui()

    with grid[8, 0]:
        vhi_panel.ui()


def main() -> None:
    try:
        app.run()
    finally:
        bus.stop()
        training_aid.set_recording_session(False)
        training_aid.stop()
        vhi_canonical.stop()
        vhi_legacy.stop()


if __name__ == "__main__":
    main()
