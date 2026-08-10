"""Classification demo: fake EMG → numpy features → CatBoost → VHI two ways.

One classification, output twice: `fist` streams continuously to VHI's predicted hand over
LSL, and on each predicted-class *change* `gesture` sends a discrete ``SetMovement`` to
VHI's control hand over gRPC. Where each one lands is declared in
../controls/classification_grpc.toml, not here.

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

import pathlib
import sys
import tomllib

import numpy as np

from myogestic import App, Fr, Grid, Px, Stream, TrainingData
from myogestic.controls import ControlLink, load_control_map
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PipelinePanel
from myogestic.recipes.estimators import catboost_classifier
from myogestic.recipes.features import mav, rms, var, wl
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
    VhiMovementPanel,
)

ctrl_outlet = control_outlet()

vhi = virtual_hand()
recording_aid = vhi.recording_client()
vhi_control = vhi.control_client()

# The left side is ours (`fist` and `gesture`), the right side is VHI's. Parsing needs no
# VHI; resolving does.
CONTROL_FILE = (
    pathlib.Path(__file__).resolve().parent.parent / "controls" / "classification_grpc.toml"
)
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

output_filter = PostProcessor(hz=32)

# These double as the states of the discrete `gesture` output, sent verbatim, so each must
# be a movement this VHI offers (see MovementDefinitions.cs). The fake generator has only
# two amplitude levels, so two classes is also all it can cleanly drive.
CLASSES = ["Rest", "Fist"]
# Amplitude for the generator and value for `fist`; the control file fans it out to six.
CTRL_VALUES = [0.0, 1.0]


# Any callable of your own goes in this dict too — features are user code.
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
    # `launchable`, never `launcher`: a VHI that cannot be launched must not stop this app
    # from opening, and one already running needs no button.
    *vhi.launchable(),
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


# Nothing is resolved here — this app launches VHI from its own UI. `link.ensure()` binds
# once VHI is up; until then `link.bus` is None. No hand and no stream is named either: the
# target looks this file's addresses up in VHI's manifest, one stream per address it drives.
link = ControlLink(
    CONTROL_MAP,
    [RemoteTarget(client=vhi_control, interface=vhi)],
    ctx=app.ctx,
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
    if link.bus is None:
        # `link.bus`, never `link.ensure()`: binding blocks on an RPC and this runs on the
        # predict thread.
        return {"class": class_idx, "proba": proba}

    # One frame carries both outputs. The bus applies the debounce the control file
    # declares, so the gesture reaches the control hand only once it has settled.
    values = link.bus.push({"fist": CTRL_VALUES[class_idx], "gesture": CLASSES[class_idx]})

    return {"class": class_idx, "proba": proba, "hand": values}


# The branding cell is Px in both axes so it stays sized to the wordmark, not the window.
LOGO_CELL_W = 300
WORDMARK_ASPECT = 800 / 540
grid = Grid(
    9,
    3,
    row_height=[Px(LOGO_CELL_W / WORDMARK_ASPECT), *[Fr(1)] * 8],
    col_width=[Px(LOGO_CELL_W), Fr(1), Fr(1)],
)


def _select_gesture(state: str) -> None:
    """Deliver a VHI movement from a click, resolving the control map first if needed.

    `select` delivers immediately and rebases the DOF's trigger, so the next predict
    ticks — still on the old ~0.2 s window — do not re-fire or jump.
    """
    bus = link.ensure()
    if bus is not None:
        bus.select("gesture", state)


def _on_gesture(i: int) -> None:
    """Manual class button: drive the fake generator and the VHI control hand."""
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore
    _select_gesture(CLASSES[i])


def _on_record() -> None:
    """The recording aid gates VHI's keyboard so MyoGestic is the sole authority."""
    link.ensure()
    app.start_recording()
    if not recording_aid.set_recording_session(True):
        app.ctx.log("VHI recording-session gate unavailable — keyboard is not blocked")


def _on_stop() -> None:
    app.stop_recording()
    recording_aid.set_recording_session(False)


# Clicks route through the `gesture` output, not straight at the target, so they pass the
# same debounce and rebase it — see `_select_gesture`.
vhi_panel = VhiMovementPanel(recording_aid, _select_gesture)

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

    with grid[8, 0]:
        vhi_panel.ui()


def main() -> None:
    global ctrl_outlet
    try:
        app.run()
    finally:
        link.stop()
        recording_aid.set_recording_session(False)
        recording_aid.stop()
        vhi_control.stop()
        # The pose stream is not listed: the target builds it, so `link.stop()` frees it.
        ctrl_outlet = None  # a raw StreamOutlet has no .stop(); dropping it releases it


if __name__ == "__main__":
    main()
