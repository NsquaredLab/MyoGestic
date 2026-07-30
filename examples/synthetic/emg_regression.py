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

The control space lives in `examples/controls/regression.toml`: the aliases on its left
are this script's own vocabulary, the addresses on its right are VHI's. It cannot be
resolved before VHI runs — VHI is what declares what those addresses accept — so the
bus is built on the first click that needs it.
"""

import pathlib
import sys
import tomllib

import numpy as np
import torch
from myoverse.transforms import MAV, RMS, WaveformLength

from myogestic import App, Fr, Grid, Px, Stream, TrainingData
from myogestic.controls import ControlBus, load_control_map, resolve
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PipelinePanel
from myogestic.recipes.estimators import catboost_regressor
from myogestic.session import iter_aligned_windows, iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.vhi import VhiTarget, virtual_hand
from myogestic.vhi.legacy import LEGACY_ADDRESS_CHANNELS, LEGACY_POSE_DOFS, decode_pose
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
# The v2 recording aid — the session gate and, if you want a swept trajectory
# instead of held poses, trajectory playback. Not a control plane; see
# `recording_client` for why that separation matters.
recording_aid = vhi.recording_client()

# Output-side smoothing, applied by the control bus to the control vector.
# Live-tunable via the PostProcessor widget rendered in the UI.
output_filter = PostProcessor(hz=32)

# The control space this app commands, as a *mapping* rather than a declaration: five
# continuous aliases for the digits plus one discrete gesture, each pointed at an address
# VHI declares. What an address means — number or held state, its range, its states — is
# VHI's to say, so this stays unresolved until VHI answers (see `_ensure_vhi`).
#
# No VHI channel number appears here, and none should: `VhiTarget` owns the
# translation to whatever the hand happens to want on the wire.
# --8<-- [start:dofs]
CONTROL_FILE = pathlib.Path(__file__).resolve().parent.parent / "controls" / "regression.toml"
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))
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
    # vhi.launchable() returns a [(name, argv)] entry; splat it so EMG Generator and VHI
    # Hand share one launcher panel. `launchable` rather than `launcher` because an
    # unlaunchable renderer must not stop this app from opening — a running one needs no
    # button, and the reason is logged either way.
    *vhi.launchable(),
]

# --8<-- [start:bus]
# The bus cannot exist yet. Resolving the control file needs VHI to say what its
# addresses accept, and VHI is launched from this app's own ProcessLauncher — so these
# stay None until `_ensure_vhi` runs, on the first click that needs them.
#
# Once built, one bus owns the whole output path: substitute rest -> clip -> smooth ->
# clip again -> hand it to every target. `VhiTarget` is what turns resolved aliases into
# whatever this VHI renders on the wire.
vhi_control = vhi.control_client()
vhi_target = None
bus = None
controls = None
# --8<-- [end:bus]

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
    """Train CatBoost regressor: EMG features → one column per continuous alias.

    For sessions with `vhi_control` kinematics: use iter_aligned_windows
    (EMG window → kinematics target via timestamp alignment).

    For sessions without kinematics (labels-only): use iter_labeled_windows
    with a synthetic target (rest=0, fist=1).

    Both helpers transparently handle folder + .session.zip layouts.
    """
    log = pipeline.train_log
    log.clear()

    # The target vector is named in the alias vocabulary, so the map has to be resolved
    # first — the same handler-side resolve the buttons do, here on the training thread.
    # (Never on the predict thread: `capabilities` blocks on an RPC.)
    _ensure_vhi()
    if controls is None:
        raise ValueError(
            "controls are not resolved yet — launch VHI, then train. Its manifest is what "
            "says which aliases are continuous, and those are the regression targets."
        )
    aliases = controls.channel_labels()
    n_dof = len(aliases)
    # The recorded control hand is VHI's legacy 9-channel pose, and `decode_pose` keys it
    # by pose channel — so each alias finds its column through the address it routes to.
    # The aliases stay the vocabulary; the addresses only do the lookup. One route each
    # here; an alias fanned out to several controls would need a rule for which to learn
    # from, so this takes the first deliberately rather than by accident.
    pose_keys = [
        LEGACY_POSE_DOFS[LEGACY_ADDRESS_CHANNELS[controls.routes[a][0].address]] for a in aliases
    ]
    log.append(f"Training from {len(data.paths)} sessions, targets: {', '.join(aliases)}")

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
        # decode_pose reads VHI's recorded pose as control values, so the
        # training target is in exactly the space `predict` commands. It is a
        # signed negation, not the old `abs()` - which folded any extension the
        # operator did into flexion of the same magnitude.
        pose = decode_pose(aligned["vhi_control"])
        kin = np.array([pose[key] for key in pose_keys], dtype=np.float64)
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
        # +1 is flexion under the control standard, so a Fist target is all 1s
        # and Rest is all 0s - the same numbers as before, now for a stated reason.
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
    if bus is None:
        return None  # nothing resolved yet, so there is nothing to command
    pred = model.predict(features.reshape(1, -1))[0]
    # Still the model's own vocabulary: the bus is keyed by alias, and the routing to
    # VHI's addresses travels with the resolved set. The bus sanitises, smooths and
    # renders. No clip here: each alias's resolved range is the authority, and clipping
    # before the smoother would let the filter overshoot straight back out of it.
    return {"dof": bus.push(dict(zip(controls.channel_labels(), pred, strict=True)))}


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


# --8<-- [start:negotiate]
def _ensure_vhi() -> None:
    """Resolve the control map once VHI is up and can say what it exports.

    Semantics come from the target, so nothing can be built at import time: the app
    launches VHI from its own ProcessLauncher. Called from the UI handlers and the
    training thread — never from the predict callback, because `capabilities` blocks
    on an RPC. Cheap and idempotent once settled.
    """
    global bus, controls, vhi_target
    if bus is not None:
        return
    capabilities = vhi_control.capabilities()
    if capabilities is None:
        app.ctx.log("VHI not reachable yet — controls stay unresolved")
        return
    # Refuses an address this build does not export, naming the near misses.
    controls = resolve(CONTROL_MAP, capabilities)
    vhi_target = VhiTarget(vhi_outlet, client=vhi_control)
    bus = ControlBus(controls, targets=[vhi_target], smoothing=output_filter, hz=32)
    # Recordings then carry the space they were made under: a bare -1 does not say
    # whether it was a full excursion or out of range.
    app.ctx.control_space = CONTROL_MAP
    # `bind` ran inside the bus, and VHI already answered above, so the handshake is
    # settled — `bind` would have raised otherwise.
    app.ctx.log(f"resolved {len(controls.dofs)} controls against VHI")
# --8<-- [end:negotiate]


# --8<-- [start:gesture]
def _on_gesture(i: int) -> None:
    # A held state, commanded by name through the same bus the continuous DOFs go
    # through. The control hand snaps to that pose and holds it, so VHI_Control
    # settles to a static kinematic value per gesture, which the regressor learns to
    # map back from the corresponding EMG amplitude.
    #
    # `bus.select` bypasses the debounce because this is a deliberate click, not a
    # noisy prediction, and rebases the trigger so the next push does not re-fire it.
    _ensure_vhi()
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore
    if bus is not None:
        # The state names are VHI's own movements, straight out of its manifest — the
        # class names here match them, and `select` returns False if one ever does not.
        bus.select("gesture", CLASSES[i])
# --8<-- [end:gesture]


# --8<-- [start:record]
def _on_record() -> None:
    # The recording aid, not a control command: it gates VHI's local keyboard so the
    # gesture buttons are the session's only movement source. Returns False if this
    # VHI has no v2 aid, which is worth surfacing — an ungated recording can pick up
    # stray keyboard movements and nothing downstream could tell.
    _ensure_vhi()
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
        # Rest the hand first, and make that frame land: the outlet sends on a
        # paced thread, so a pose pushed at exit would otherwise never go out
        # and the hand would hold its last commanded position.
        if bus is not None:
            bus.stop()
        recording_aid.stop_trajectory()      # no-op unless a trajectory was started
        recording_aid.set_recording_session(False)
        recording_aid.stop()
        vhi_control.stop()


if __name__ == "__main__":
    main()
