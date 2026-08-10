"""Classification demo: fake EMG → numpy features → CatBoost → VHI hand.

Run with:
    uv run python examples/synthetic/emg_classification.py

Workflow:
    1. Launch "EMG Generator" → signal appears
    2. Click Rest/Fist to switch signal + set label
    3. Record Rest trial → Record Fist trial
    4. Select sessions → Train → Predict → VHI hand moves
"""

import pathlib
import sys
import tomllib

import numpy as np

from myogestic import App, Fr, Grid, Px, Stream, TrainingData
from myogestic.controls import ControlLink, load_control_map
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PipelinePanel
from myogestic.recipes.estimators import catboost_classifier
from myogestic.recipes.features import mav, rms, var, wl, zc
from myogestic.remote import RemoteTarget
from myogestic.session import iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.vhi import virtual_hand
from myogestic.widgets import (
    AppLogo,
    FeatureSelector,
    PostProcessor,
    PredictionLabel,
    ProcessLauncher,
    RecordingControls,
    SessionManager,
    SignalViewer,
)

ctrl_outlet = control_outlet()

# --8<-- [start:poses]
vhi = virtual_hand()

# The left side is ours, the right side is VHI's. Parsing needs no VHI; resolving does.
CONTROL_FILE = pathlib.Path(__file__).resolve().parent.parent / "controls" / "classification.toml"
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

# Both aliases declare a `threshold_fraction` in the file, so a probability is gated to
# 0 or 1 there and reaches the hand as an ordinary control value — same path as regression.
FIST_ALIASES = ("fist", "thumb_spread")

# --8<-- [end:poses]

# --8<-- [start:filter]
output_filter = PostProcessor(hz=32)
# --8<-- [end:filter]

vhi_control = vhi.control_client()


# Any callable of your own goes in this dict too — features are user code.
# --8<-- [start:features]
features = FeatureSelector(
    {"RMS": rms, "MAV": mav, "WL": wl, "VAR": var, "ZC": zc},
    default=["RMS", "MAV"],
)
# --8<-- [end:features]

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

# --8<-- [start:setup]
WINDOW_MS = 200
HOP_MS = 100

app = App("EMG Classification", ui_scale=0.85)
app.streams(Stream("emg", source=LSLSource("TestEMG1"), window_ms=WINDOW_MS, buffer_ms=60000))
pipeline = Pipeline(app)
# --8<-- [end:setup]

# Nothing is resolved here — this script launches VHI itself. `link.ensure()` binds on the
# first click that finds VHI up; `link.bus` is None until then, and `RemoteTarget` refuses
# a VHI it cannot fully drive rather than guessing.
link = ControlLink(
    CONTROL_MAP,
    # No hand and no stream is named: the target looks this file's addresses up in VHI's
    # manifest and publishes one one-channel stream per address it drives.
    [RemoteTarget(client=vhi_control, interface=vhi)],
    ctx=app.ctx,
    smoothing=output_filter,
    hz=32,
)


# --8<-- [start:extract]
@pipeline.extract
def extract(windows: dict[str, np.ndarray]) -> np.ndarray:
    """Active features stacked along axis 0 → flat feature vector."""
    return features(windows["emg"])


# --8<-- [end:extract]


# --8<-- [start:train]
@pipeline.train
def train(data: TrainingData):
    """Train a CatBoost classifier on numpy features from selected sessions.

    Every feature here reduces a window to one scalar per channel, so the feature
    dimension is ``n_active_features * n_channels``.
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
        data.paths, "emg", WINDOW_MS, HOP_MS, classes=data.classes
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


# --8<-- [end:train]


# --8<-- [start:predict]
@pipeline.predict
def predict(model, features):
    """Classify → gate to an activation → smooth → push to VHI.

    The probabilities themselves flow through untouched, for the UI.
    """
    proba = model.predict_proba(features.reshape(1, -1))[0]
    class_idx = int(np.argmax(proba))
    # `link.bus`, never `link.ensure()`: binding blocks on an RPC and this callback has a
    # deadline.
    if link.bus is None:
        return {"class": class_idx, "proba": proba}
    # Pushed raw: the bus gates it, so VHI is never handed a bare 0.73 as a finger position.
    activation = float(proba[CLASSES.index("Fist")])
    hand = link.bus.push(dict.fromkeys(FIST_ALIASES, activation))
    return {"class": class_idx, "proba": proba, "hand": hand}


# --8<-- [end:predict]


# The branding cell is Px in both axes so it stays sized to the wordmark, not the window.
# --8<-- [start:layout]
LOGO_CELL_W = 300
WORDMARK_ASPECT = 800 / 540
grid = Grid(
    8,
    3,
    row_height=[Px(LOGO_CELL_W / WORDMARK_ASPECT), *[Fr(1)] * 7],
    col_width=[Px(LOGO_CELL_W), Fr(1), Fr(1)],
)


def _on_gesture(i: int) -> None:
    link.ensure()
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore


def _on_record() -> None:
    link.ensure()
    app.start_recording()


viewer = SignalViewer("emg")
logo = AppLogo()
processes = ProcessLauncher(PROCESSES)
recording = RecordingControls(
    CLASSES,
    on_record=_on_record,
    on_stop=app.stop_recording,
    on_gesture=_on_gesture,
)
sessions = SessionManager("sessions", class_names=CLASSES)
panel = PipelinePanel(pipeline)
prediction = PredictionLabel(pipeline, CLASSES)


@app.ui
def demo_ui(ctx):
    with grid[0:8, 1:3]:
        viewer.ui(ctx)

    with grid[0, 0]:
        # No size cap: the widget fits-in-rect, preserving aspect, and centres itself.
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


# --8<-- [end:layout]


def main() -> None:
    try:
        app.run()
    finally:
        # Rest the hand and make that frame land before the outlet's thread dies.
        link.stop()
        vhi_control.stop()


if __name__ == "__main__":
    main()
