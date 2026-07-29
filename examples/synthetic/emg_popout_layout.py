"""Pop-out windows demo: same 32-ch multi-model experiment as
``emg_32ch_multi_model.py``, but each block is registered with
``app.popout(...)`` so the user can tear panels off into their own floating
ImGui windows — and, with multi-viewport enabled, into real OS windows.

Run with:
    uv run python examples/synthetic/emg_popout_layout.py

Workflow:
    1. Launch generator + VHI as before.
    2. Drag any panel's tab outside the main window — it floats into its
       own native OS window.
    3. Quit and re-launch — the layout restores from
       ``.imgui_state/EMG_32ch_Popout.ini``.

Experimental - see the README "Status" note for macOS caveats.
"""

import re
import sys
import time as _time
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import torch
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui
from imgui_bundle import portable_file_dialogs as pfd
from myoverse.transforms import MAV, RMS, WaveformLength

from myogestic import App, Stream, TrainingData
from myogestic.controls import ControlBus, load_control_map, resolve
from myogestic.ml import Pipeline, load_pickle, save_pickle
from myogestic.ml.widgets import PredictButton, TrainButton, TrainingLog
from myogestic.recipes.estimators import (
    catboost_classifier,
    constant_classifier,
    sklearn_classifier,
    sklearn_extra_trees_classifier,
    sklearn_logistic_classifier,
)
from myogestic.session import iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.vhi import VhiTarget, virtual_hand
from myogestic.widgets import (
    LogPanel,
    PostProcessor,
    PredictionLabel,
    ProcessLauncher,
    RecordingControls,
    SessionManager,
    SignalViewer,
    StreamPanel,
)
from myogestic.widgets.common import panel_header
from myogestic.widgets.panels.log_box import render_log_buttons, render_log_popout

N_CHANNELS = 32
CLASSES = ["Rest", "Fist", "Pinch", "Open"]
CTRL_VALUES = [0.0, 1.0, 2.0, 3.0]
WINDOW_MS = 250
HOP_MS = 100

ctrl_outlet = control_outlet()

vhi = virtual_hand()
vhi_outlet = vhi.outlet()
output_filter = PostProcessor(hz=32)

# Which of *this example's* output names go to which of VHI's controls. Parsing the file
# needs no VHI; learning what its addresses mean does — see `_ensure_vhi`.
CONTROL_FILE = Path(__file__).resolve().parent.parent / "controls" / "popout_layout.toml"
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

# Our aliases, taken from the file, so renaming one there needs no edit here.
POSE_ALIASES = tuple(CONTROL_MAP.bindings)

# Per-class poses in canonical values: +1 is the direction the alias' target names, 0 is
# rest. The fist abducts the thumb — this used to write that channel as 0, but recorded
# VHI sessions have it at full excursion.
HAND_POSES: dict[int, dict[str, float]] = {
    0: {},  # Rest
    1: dict.fromkeys(POSE_ALIASES, 1.0),  # Fist
    2: {  # Pinch
        "thumb_curl": 0.7,
        "thumb_spread": 0.6,
        "index_curl": 0.8,
        "middle_curl": 0.6,
    },
    3: dict.fromkeys(POSE_ALIASES, -0.5),  # Open: extended past rest
}

# The bus + target own the wire. VHI's continuous inlet takes *canonical* values as of
# 2.0 while older builds want the negated legacy pose, so a hand-built frame is correct
# on exactly one of them. `VhiTarget` asks which and encodes accordingly. Both wait for
# `_ensure_vhi`: the map says nothing about kinds or ranges until VHI has declared them.
vhi_canonical = vhi.canonical_client()
vhi_target: VhiTarget | None = None
bus: ControlBus | None = None

rms_transform = RMS(window_size=32)
mav_transform = MAV(window_size=32)
wl_transform = WaveformLength(window_size=32)


def extract_features(emg: np.ndarray) -> np.ndarray:
    tensor = torch.from_numpy(emg).float()
    return np.concatenate(
        [
            rms_transform(tensor).numpy().flatten(),
            mav_transform(tensor).numpy().flatten(),
            wl_transform(tensor).numpy().flatten(),
        ]
    )


PROCESSES = [
    (
        "EMG Generator 32ch",
        [
            sys.executable,
            "-m",
            "myogestic.tools.emg_generator",
            "--name",
            "TestEMG32",
            "--channels",
            str(N_CHANNELS),
            "--classes",
            str(len(CLASSES)),
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

# docking=True enables ImGui multi-viewport so each app.popout(...) panel
# becomes a tearable / dockable window.
app = App("EMG 32ch Popout", ui_scale=0.85, docking=True)
app.streams(Stream("emg", source=LSLSource("TestEMG32"), window_ms=WINDOW_MS, buffer_ms=60000))
pipeline = Pipeline(app)
pipeline.save_model = save_pickle
pipeline.load_model = load_pickle

MODELS_DIR = Path("models")


@pipeline.extract
def extract(windows) -> np.ndarray:
    return extract_features(windows["emg"])


# --- Model recipes ----------------------------------------------------------

MODEL_RECIPES: dict[str, Callable[[], Any]] = {
    "CatBoost": lambda: catboost_classifier(iterations=150),
    "Random Forest": lambda: sklearn_classifier(n_estimators=200, random_state=0, n_jobs=-1),
    "Extra Trees": lambda: sklearn_extra_trees_classifier(
        n_estimators=300, random_state=0, n_jobs=-1
    ),
    "Logistic Regression": lambda: sklearn_logistic_classifier(max_iter=1000),
    "Dummy Constant": lambda: constant_classifier(0),
}
MODEL_NAMES = list(MODEL_RECIPES)
selected_model_idx = 0
_load_dialog: object | None = None


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "model"


def _list_saved() -> list[Path]:
    if not MODELS_DIR.is_dir():
        return []
    return sorted(MODELS_DIR.glob("*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)


@pipeline.train
def train(data: TrainingData):
    log = pipeline.train_log
    log.clear()
    if data.is_empty:
        raise ValueError("No sessions selected.")
    if len(data.classes) < 2:
        raise ValueError("Need ≥2 active classes.")
    X, y = [], []
    for window, _ts, ci in iter_labeled_windows(
        data.paths, "emg", WINDOW_MS, HOP_MS, classes=data.classes
    ):
        X.append(extract_features(window))
        y.append(ci)
    if len(X) < 2:
        raise ValueError(f"Need at least 2 windows, got {len(X)}")
    X = np.stack(X)
    y = np.array(y)

    model_name = MODEL_NAMES[selected_model_idx]
    log.append(f"Model: {model_name} · X={X.shape} · classes={sorted(set(y))}")
    rng = np.random.default_rng(0)
    perm = rng.permutation(len(X))
    cut = max(1, int(0.8 * len(X)))
    tr, te = perm[:cut], perm[cut:]
    model = MODEL_RECIPES[model_name]()
    model.fit(X[tr], y[tr])
    if len(te) and hasattr(model, "score"):
        log.append(f"Held-out accuracy ({len(te)}): {model.score(X[te], y[te]):.2%}")
    return model


@pipeline.predict
def predict(model, features):
    x = features.reshape(1, -1)
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x)[0]
        class_idx = int(np.argmax(proba))
    else:
        proba = None
        class_idx = int(model.predict(x)[0])
    if bus is None:
        # Nothing resolved yet, so there is nothing to command — and asking VHI what it
        # exports blocks on an RPC, which this thread must not do.
        return {"class": class_idx, "proba": proba, "hand": {}}
    pose = HAND_POSES.get(class_idx, HAND_POSES[0])
    hand = bus.push({**dict.fromkeys(POSE_ALIASES, 0.0), **pose})
    return {"class": class_idx, "proba": proba, "hand": hand}


def _ensure_vhi() -> None:
    """Resolve the control map once VHI is up and can say what it exports."""
    global bus, vhi_target
    if bus is not None:
        return
    capabilities = vhi_canonical.capabilities()
    if capabilities is None:
        app.ctx.log("VHI not reachable yet — controls stay unresolved")
        return
    controls = resolve(CONTROL_MAP, capabilities)
    vhi_target = VhiTarget(vhi_outlet, client=vhi_canonical)
    bus = ControlBus(controls, targets=[vhi_target], smoothing=output_filter, hz=32)
    app.ctx.control_space = CONTROL_MAP  # recordings record what they were made under
    app.ctx.log(f"resolved {len(controls.dofs)} controls against VHI")


def _on_gesture(i: int) -> None:
    _ensure_vhi()
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore


def _on_record() -> None:
    _ensure_vhi()
    app.start_recording()


# --- Per-block render functions (each becomes its own dockable window) -----


_signal_viewer = SignalViewer("emg", selectable=True)


def _signal_block() -> None:
    _signal_viewer.ui(app.ctx)


_streams = StreamPanel()


def _streams_block() -> None:
    _streams.ui(app.ctx)


_log = LogPanel()


def _log_block() -> None:
    _log.ui(app.ctx)


_processes = ProcessLauncher(PROCESSES)


def _processes_block() -> None:
    _processes.ui()


_recording = RecordingControls(
    CLASSES,
    on_record=_on_record,
    on_stop=app.stop_recording,
    on_gesture=_on_gesture,
)


def _recording_block() -> None:
    _recording.ui(app.ctx)


_MODEL_WIDGET_ID = "ml_popout"
_autoscroll_on = True
_log_popout_open = False

_train_btn = TrainButton(pipeline)
_predict_btn = PredictButton(pipeline)
_training_log = TrainingLog(pipeline, height=80.0, widget_id=_MODEL_WIDGET_ID)


def _model_block() -> None:
    global selected_model_idx, _load_dialog, _autoscroll_on, _log_popout_open

    # Render the popout window first so it survives even if the parent
    # block scrolls / docks out of view (same pattern as pipeline_panel).
    if _log_popout_open:
        still_open = render_log_popout(
            _MODEL_WIDGET_ID,
            pipeline.train_log,
            title="Model training log",
            autoscroll=_autoscroll_on,
        )
        if not still_open:
            _log_popout_open = False

    panel_header("MODEL", fa.ICON_FA_BRAIN)
    imgui.push_item_width(-1)
    _, selected_model_idx = imgui.combo("##model_sel", selected_model_idx, MODEL_NAMES)
    imgui.pop_item_width()
    _train_btn.ui()
    imgui.same_line()
    _predict_btn.ui()
    imgui.same_line()
    _autoscroll_on, _log_popout_open = render_log_buttons(
        _MODEL_WIDGET_ID, autoscroll=_autoscroll_on, popped_out=_log_popout_open
    )
    if _log_popout_open:
        imgui.text_disabled("(log popped out — see 'Model training log' window)")
    else:
        _training_log.ui()

    can_save = pipeline.model is not None
    if not can_save:
        imgui.begin_disabled()
    if imgui.button(f"{fa.ICON_FA_FLOPPY_DISK}  Save") and pipeline.model is not None:
        MODELS_DIR.mkdir(exist_ok=True)
        slug = _slug(MODEL_NAMES[selected_model_idx])
        ts = _time.strftime("%Y%m%d_%H%M%S")
        path = MODELS_DIR / f"{slug}_{ts}.joblib"
        save_pickle(pipeline.model, str(path))
        app.ctx.log(f"Model saved → {path}")
    if not can_save:
        imgui.end_disabled()
    imgui.same_line()
    if imgui.button(f"{fa.ICON_FA_FOLDER_OPEN}  Load..."):
        MODELS_DIR.mkdir(exist_ok=True)
        _load_dialog = pfd.open_file("Load model", str(MODELS_DIR), ["Model", "*.joblib"])
    imgui.same_line()
    imgui.text_disabled(f"({len(_list_saved())} saved)")

    if _load_dialog is not None and _load_dialog.ready():  # type: ignore
        result = _load_dialog.result()  # type: ignore
        _load_dialog = None
        if result:
            try:
                pipeline.model = load_pickle(result[0])
                app.ctx.log(f"Model loaded ← {result[0]}")
            except Exception as e:
                app.ctx.log(f"Load failed: {e}")


def _filter_block() -> None:
    output_filter.ui()


_sessions = SessionManager("sessions", class_names=CLASSES)


def _sessions_block() -> None:
    pipeline.training_data = _sessions.ui()


_prediction = PredictionLabel(pipeline, CLASSES)


def _prediction_block() -> None:
    _prediction.ui()


def _panel(title: str, fn: Callable[[], None]) -> None:
    # Panels are dockable/tearable but not closeable. `remember_is_visible=False`
    # avoids a stale ini entry keeping a previously closed panel hidden.
    app.popout(title, fn, can_be_closed=False, remember_is_visible=False)


_panel("Signal", _signal_block)
_panel("Streams", _streams_block)
_panel("Log", _log_block)
_panel("Processes", _processes_block)
_panel("Recording", _recording_block)
_panel("Model", _model_block)
_panel("Post-processing", _filter_block)
_panel("Sessions", _sessions_block)
_panel("Prediction", _prediction_block)


def main() -> None:
    try:
        app.run()
    finally:
        # Rest the hand and make that frame land before the outlet's thread dies.
        if bus is not None:
            bus.stop()
        vhi_canonical.stop()


if __name__ == "__main__":
    main()
