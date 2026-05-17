"""Classification demo: fake EMG → numpy features → CatBoost → VHI hand.

Run with:
    uv run python examples/synthetic/emg_classification.py

Workflow:
    1. Launch "EMG Generator" → signal appears
    2. Click Rest/Fist to switch signal + set label
    3. Record Rest trial → Record Fist trial
    4. Select sessions → Train → Predict → VHI hand moves
"""

import sys

import numpy as np

from myogestic import App, Fr, Grid, Px, Stream, TrainingData
from myogestic.contrib.features import mav, rms, var, wl, zc
from myogestic.interfaces import virtual_hand
from myogestic.ml import Pipeline
from myogestic.ml.widgets import pipeline_panel
from myogestic.models import catboost_classifier
from myogestic.session import iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.widgets import (
    FeatureSelector,
    FilterControl,
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
HAND_REST = np.zeros(9, dtype=np.float32)
HAND_FIST = np.array([-1, 0, -1, -1, -1, -1, 0, 0, 0], dtype=np.float32)

# Output-side smoothing applied to the hand pose vector before pushing
# to VHI. Live-tunable via the FilterControl widget rendered in the UI.
output_filter = FilterControl(hz=32, default="one_euro")

# Reference RMS / MAV / WL / VAR / ZC live in myogestic.contrib.features; mix
# with your own callables here — feature engineering is user code, this is
# the seam where you'd add custom ones.
features = FeatureSelector(
    {"RMS": rms, "MAV": mav, "WL": wl, "VAR": var, "ZC": zc},
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
]

CLASSES = ["Rest", "Fist"]
CTRL_VALUES = [0.0, 1.0]

WIN_SECONDS = 0.2
HOP_SECONDS = 0.1

app = App("EMG Classification", ui_scale=0.85)
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
    """Train CatBoost classifier on numpy features from selected sessions.

    Each labeled trial is chopped into fixed-size windows (0.2s) so the
    feature vectors all share a shape - all features here reduce a
    window to one scalar per channel, so total feature dim is
    ``n_active_features * n_channels``.
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
        data.paths, "emg", WIN_SECONDS, HOP_SECONDS, classes=data.classes
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


@pipeline.predict
def predict(model, features):
    """Classify → map to hand pose → smooth → push to VHI.

    Filter applies only to the physical-control vector; class probabilities
    flow through unchanged for the UI / debug overlay.
    """
    proba = model.predict_proba(features.reshape(1, -1))[0]
    class_idx = int(np.argmax(proba))
    hand = HAND_FIST.copy() if class_idx == 1 else HAND_REST.copy()
    hand = output_filter(hand).astype(np.float32)
    vhi_outlet.push(hand)
    return {"class": class_idx, "proba": proba, "hand": hand}


# Branding cell is FIXED-pixel in both axes so it stays sized to the
# wordmark regardless of window dimensions:
#   * col 0 → Px(300) wide
#   * row 0 → Px(300 / 1.48) ≈ Px(203) tall (matches the wordmark aspect)
# Everything else uses Fr (CSS-grid "fraction unit") to share the leftover
# space: cols 1+2 split the remaining width equally, rows 1-7 split the
# remaining height equally.
LOGO_CELL_W = 300
WORDMARK_ASPECT = 800 / 540
grid = Grid(
    8,
    3,
    row_height=[Px(LOGO_CELL_W / WORDMARK_ASPECT), *[Fr(1)] * 7],
    col_width=[Px(LOGO_CELL_W), Fr(1), Fr(1)],
)


def _on_gesture(i: int) -> None:
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]


@app.ui
def demo_ui(ctx):
    with grid[0:8, 1:3]:
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
            on_record=app.start_recording,
            on_stop=app.stop_recording,
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


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
