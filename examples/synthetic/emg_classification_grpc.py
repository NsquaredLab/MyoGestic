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

from myogestic import App, EdgeTrigger, Fr, Grid, Px, Stream, TrainingData
from myogestic.ml import Pipeline
from myogestic.ml.widgets import pipeline_panel
from myogestic.recipes.estimators import catboost_classifier
from myogestic.recipes.features import mav, rms, var, wl
from myogestic.session import iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.vhi.interfaces import virtual_hand
from myogestic.widgets import (
    FeatureSelector,
    FilterControl,
    VhiMovementPanel,
    app_logo,
    prediction_label,
    process_launcher,
    recording_controls,
    session_manager,
    signal_viewer,
)

ctrl_outlet = control_outlet()

vhi = virtual_hand()
vhi_outlet = vhi.outlet()
vhi_client = vhi.control_client()

HAND_REST = np.zeros(9, dtype=np.float32)
HAND_FIST = np.array([-1, 0, -1, -1, -1, -1, 0, 0, 0], dtype=np.float32)

# Output-side smoothing applied to the hand pose vector before pushing
# to VHI. Live-tunable via the FilterControl widget rendered in the UI.
output_filter = FilterControl(hz=32, default="one_euro")

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

WIN_SECONDS = 0.2
HOP_SECONDS = 0.1

app = App("EMG Classification (gRPC)", ui_scale=0.85)
app.streams(
    Stream("emg", source=LSLSource("TestEMG1"), window_seconds=WIN_SECONDS, buffer_seconds=60)
)
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
        data.paths, "emg", WIN_SECONDS, HOP_SECONDS, classes=data.classes
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


# SetMovement re-triggers VHI's animation, so only command VHI when the
# class actually changes. Two stages guard that:
#   1. _StableClass swallows tick-to-tick flicker — the predicted class only
#      "counts" once it has held for STABLE_TICKS predictions. Without it, the
#      ~0.2 s sliding-window transition after a gesture (Fist EMG → Rest EMG)
#      makes argmax oscillate, and the control hand visibly jumps between poses
#      before settling.
#   2. The EdgeTrigger dedupes per class name; the manual gesture button (below)
#      rebases both so a click + the next predict ticks don't re-fire.
STABLE_TICKS = 5  # ~100 ms at predict_hz=50


class _StableClass:
    """Emit a class only after it has held for ``k`` consecutive updates."""

    def __init__(self, k: int) -> None:
        self._k = k
        self._candidate: str | None = None
        self._count = 0
        self.stable: str | None = None

    def update(self, cls: str) -> str | None:
        """Feed the latest prediction; return the settled class (or None)."""
        if cls == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count = cls, 1
        if self._count >= self._k:
            self.stable = cls
        return self.stable

    def rebase(self, cls: str) -> None:
        """Force ``cls`` as the settled class (after a manual command)."""
        self._candidate, self._count, self.stable = cls, self._k, cls


stable_class = _StableClass(STABLE_TICKS)
movement_trigger: EdgeTrigger[str] = EdgeTrigger(vhi_client.set_movement)


@pipeline.predict
def predict(model, features):
    """Classify, then output it two ways: stream the hand pose to VHI's
    predicted hand (LSL), and on each class *change* command the control
    hand (gRPC)."""
    proba = model.predict_proba(features.reshape(1, -1))[0]
    class_idx = int(np.argmax(proba))

    hand = HAND_FIST.copy() if class_idx == 1 else HAND_REST.copy()
    hand = output_filter(hand).astype(np.float32)
    vhi_outlet.push(hand)

    # Only command the control hand once the class has settled (swallows the
    # window-transition flicker); the EdgeTrigger then dedupes repeats.
    settled = stable_class.update(CLASSES[class_idx])
    if settled is not None:
        movement_trigger.fire_if_changed(settled)

    return {"class": class_idx, "proba": proba, "hand": hand}


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


def _on_gesture(i: int) -> None:
    """Manual class button: drive the fake generator and the VHI control hand."""
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore
    vhi_client.set_movement(CLASSES[i])
    # Rebase both gates: the click already commanded this class, so the next
    # predict ticks (still on the old ~0.2 s window) must not re-fire / jump.
    stable_class.rebase(CLASSES[i])
    movement_trigger.rebase(CLASSES[i])


def _on_record() -> None:
    """While recording, VHI ignores its local keyboard — MyoGestic is sole authority."""
    app.start_recording()
    vhi_client.set_session_active(True)


def _on_stop() -> None:
    app.stop_recording()
    vhi_client.set_session_active(False)


# VhiMovementPanel owns its own state cache and the throttled background
# get_state() refresh, so the @app.ui body stays free of plumbing.
vhi_panel = VhiMovementPanel(vhi_client)


@app.ui
def demo_ui(ctx):
    with grid[0:9, 1:3]:
        signal_viewer(ctx, "emg")

    with grid[0, 0]:
        # No size cap — let the wordmark grow to the cell. The widget
        # fits-in-rect (preserving aspect), so the image always renders
        # at the largest aspect-preserving box that fits the current
        # cell dimensions and centres itself.
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
        features.ui()

    with grid[4, 0]:
        pipeline.training_data = session_manager("sessions", class_names=CLASSES)

    with grid[5, 0]:
        pipeline_panel(pipeline)

    with grid[6, 0]:
        output_filter.ui()

    with grid[7, 0]:
        prediction_label(pipeline, CLASSES)

    with grid[8, 0]:
        vhi_panel.ui()


def main() -> None:
    try:
        app.run()
    finally:
        vhi_client.stop()


if __name__ == "__main__":
    main()
