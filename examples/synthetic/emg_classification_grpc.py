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

Where the two outputs *go* is declared in ../controls/classification_grpc.toml, not
here: this example names its outputs `fist` and `gesture`, and that file maps them onto
the control addresses VHI declares it exports.
"""

import pathlib
import sys
import tomllib

import numpy as np

from myogestic import App, Fr, Grid, Px, Stream, TrainingData
from myogestic.controls import ControlBus, connect_controls, load_control_map
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PipelinePanel
from myogestic.recipes.estimators import catboost_classifier
from myogestic.recipes.features import mav, rms, var, wl
from myogestic.session import iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.vhi import VhiTarget, virtual_hand
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
# The recording aid (session gate) and the control client.
recording_aid = vhi.recording_client()
vhi_control = vhi.control_client()

# Where this example's two outputs go. The left side of that file is ours (`fist` and
# `gesture`), the right side is VHI's — read it, it is commented. Parsing is all that
# happens here: what an address *means* is VHI's to declare, so nothing is resolved
# until it answers (see `_ensure_vhi`).
CONTROL_FILE = (
    pathlib.Path(__file__).resolve().parent.parent / "controls" / "classification_grpc.toml"
)
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

# Output-side smoothing applied to the hand pose vector before pushing
# to VHI. Live-tunable via the PostProcessor widget rendered in the UI.
output_filter = PostProcessor(hz=32)

# CLASSES double as the states of the discrete `gesture` output, and those states are
# VHI's movement names — so they are sent verbatim and must be movements this VHI
# offers (see MovementDefinitions.cs). "Rest" and "Fist" both are; the fake generator
# only produces two amplitude levels, so two classes is also what it can cleanly drive.
CLASSES = ["Rest", "Fist"]
# Per-class value for both the generator's amplitude and the `fist` output: 0 is an
# open hand, 1 fully closed. One scalar — the control file fans it out to six controls.
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
    # vhi.launchable() returns a [(name, argv)] entry; splat it so EMG Generator and VHI
    # Hand share one launcher panel. `launchable` rather than `launcher` because an
    # unlaunchable renderer must not stop this app from opening — a running one needs no
    # button, and the reason is logged either way.
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


# Both are built by `_ensure_vhi` rather than here: the control file says *where* each
# output goes, and VHI says what those addresses accept — so there is nothing to
# resolve until VHI is running, and this app launches it from its own UI.
vhi_target: VhiTarget | None = None
bus: ControlBus | None = None


@pipeline.predict
def predict(model, features):
    """Classify, then output it two ways: stream the hand pose to VHI's
    predicted hand (LSL), and on each class *change* command the control
    hand (gRPC)."""
    proba = model.predict_proba(features.reshape(1, -1))[0]
    class_idx = int(np.argmax(proba))
    if bus is None:
        # Nothing resolved yet, so nothing to command. Resolving here is not an option:
        # it blocks on an RPC and this runs on the predict thread.
        return {"class": class_idx, "proba": proba}

    # One frame carries both outputs: `fist` streams to the predicted hand, and the
    # gesture reaches the control hand only once it has settled. The bus applies the
    # debounce the control file declares, so there is no trigger to drive here.
    values = bus.push({"fist": CTRL_VALUES[class_idx], "gesture": CLASSES[class_idx]})

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
    """Bind the map once VHI can say what it exports. Idempotent; UI thread only.

    Never from `predict`: asking a renderer costs an RPC, and that callback has its own
    thread and a deadline.
    """
    global bus, vhi_target
    if bus is not None:
        return
    vhi_target = VhiTarget(vhi_outlet, client=vhi_control)
    bus = connect_controls(
        CONTROL_MAP, [vhi_target], ctx=app.ctx, smoothing=output_filter, hz=pipeline.predict_hz
    )



def _select_gesture(state: str) -> None:
    """Deliver a VHI movement from a click, resolving the control map first if needed.

    `select` delivers immediately and rebases the DOF's trigger, so the next predict
    ticks — still on the old ~0.2 s window — do not re-fire or jump.
    """
    _ensure_vhi()
    if bus is not None:
        bus.select("gesture", state)


def _on_gesture(i: int) -> None:
    """Manual class button: drive the fake generator and the VHI control hand."""
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore
    _select_gesture(CLASSES[i])


def _on_record() -> None:
    """The recording aid gates VHI's keyboard so MyoGestic is the sole authority."""
    _ensure_vhi()
    app.start_recording()
    if not recording_aid.set_recording_session(True):
        app.ctx.log("VHI recording-session gate unavailable — keyboard is not blocked")


def _on_stop() -> None:
    app.stop_recording()
    recording_aid.set_recording_session(False)


# VhiMovementPanel owns its own state cache and the throttled background
# get_state() refresh, so the @app.ui body stays free of plumbing.
# Clicks go through the `gesture` output, not straight at the renderer, so they pass
# through the same debounce and rebase it — see `_select_gesture`.
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
        if bus is not None:
            bus.stop()
        recording_aid.set_recording_session(False)
        recording_aid.stop()
        vhi_control.stop()
        # `vhi_outlet` is built at import time (line 58), before `_ensure_vhi` ever runs,
        # so it needs stopping here even on a run where `bus` never got built — otherwise
        # the un-stopped LSL stream stays resolvable by name and a later consumer (a test,
        # another example) can resolve this dead outlet instead of a live one.
        vhi_outlet.stop()


if __name__ == "__main__":
    main()
