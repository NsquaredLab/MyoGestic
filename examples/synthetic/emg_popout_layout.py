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
from myogestic.interfaces import virtual_hand
from myogestic.ml import Pipeline
from myogestic.ml.widgets import predict_button, train_button, training_log
from myogestic.models import (
    catboost_classifier,
    constant_classifier,
    load_model,
    save_model,
    sklearn_classifier,
    sklearn_extra_trees_classifier,
    sklearn_logistic_classifier,
)
from myogestic.session import iter_labeled_windows
from myogestic.sources import LSLSource
from myogestic.tools.emg_generator import control_outlet
from myogestic.widgets import (
    log_panel,
    prediction_label,
    process_launcher,
    recording_controls,
    session_manager,
    signal_viewer,
    stream_panel,
)
from myogestic.widgets._common import panel_header
from myogestic.widgets._log_box import render_log_buttons, render_log_popout
from myogestic.widgets.filter_controls import FilterControl

N_CHANNELS = 32
CLASSES = ["Rest", "Fist", "Pinch", "Open"]
CTRL_VALUES = [0.0, 1.0, 2.0, 3.0]
WIN_SECONDS = 0.25
HOP_SECONDS = 0.1

ctrl_outlet = control_outlet()

vhi = virtual_hand()
vhi_outlet = vhi.outlet()
output_filter = FilterControl(hz=32, default="one_euro")

HAND_POSES: dict[int, np.ndarray] = {
    0: np.zeros(9, dtype=np.float32),
    1: np.array([-1, 0, -1, -1, -1, -1, 0, 0, 0], dtype=np.float32),
    2: np.array([-0.7, 0, -0.8, -0.6, 0, 0, 0, 0, 0], dtype=np.float32),
    3: np.array([0.5, 0, 0.5, 0.5, 0.5, 0.5, 0, 0, 0], dtype=np.float32),
}

rms_transform = RMS(window_size=32)
mav_transform = MAV(window_size=32)
wl_transform = WaveformLength(window_size=32)


def extract_features(emg: np.ndarray) -> np.ndarray:
    tensor = torch.from_numpy(emg).float()
    return np.concatenate([
        rms_transform(tensor).numpy().flatten(),
        mav_transform(tensor).numpy().flatten(),
        wl_transform(tensor).numpy().flatten(),
    ])


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
    # vhi.launcher() returns a [(name, argv)] entry; splat it so EMG
    # Generator and VHI Hand share a single launcher panel.
    *vhi.launcher(),
]

# docking=True enables ImGui multi-viewport so each app.popout(...) panel
# becomes a tearable / dockable window.
app = App("EMG 32ch Popout", ui_scale=0.85, docking=True)
app.streams(
    Stream("emg", source=LSLSource("TestEMG32"), window_seconds=WIN_SECONDS, buffer_seconds=60)
)
pipeline = Pipeline(app)
pipeline.save_model = save_model
pipeline.load_model = load_model

MODELS_DIR = Path("models")


@pipeline.extract
def extract(windows) -> np.ndarray:
    return extract_features(windows["emg"])


# --- Model recipes ----------------------------------------------------------

MODEL_RECIPES: dict[str, Callable[[], Any]] = {
    "CatBoost": lambda: catboost_classifier(iterations=150),
    "Random Forest": lambda: sklearn_classifier(n_estimators=200, random_state=0, n_jobs=-1),
    "Extra Trees": lambda: sklearn_extra_trees_classifier(n_estimators=300, random_state=0, n_jobs=-1),
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
        data.paths, "emg", WIN_SECONDS, HOP_SECONDS, classes=data.classes
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
    hand = HAND_POSES.get(class_idx, HAND_POSES[0]).copy()
    hand = output_filter(hand).astype(np.float32)
    vhi_outlet.push(hand)
    return {"class": class_idx, "proba": proba, "hand": hand}


def _on_gesture(i: int) -> None:
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]


# --- Per-block render functions (each becomes its own dockable window) -----


def _signal_block() -> None:
    signal_viewer(app.ctx, "emg", selectable=True)


def _streams_block() -> None:
    stream_panel(app.ctx)


def _log_block() -> None:
    log_panel(app.ctx)


def _processes_block() -> None:
    process_launcher(PROCESSES)


def _recording_block() -> None:
    recording_controls(
        app.ctx,
        CLASSES,
        on_record=app.start_recording,
        on_stop=app.stop_recording,
        on_gesture=_on_gesture,
    )


_MODEL_WIDGET_ID = "ml_popout"
_autoscroll_on = True
_log_popout_open = False


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
    train_button(pipeline)
    imgui.same_line()
    predict_button(pipeline)
    imgui.same_line()
    _autoscroll_on, _log_popout_open = render_log_buttons(
        _MODEL_WIDGET_ID, autoscroll=_autoscroll_on, popped_out=_log_popout_open
    )
    if _log_popout_open:
        imgui.text_disabled("(log popped out — see 'Model training log' window)")
    else:
        training_log(pipeline, height=80.0, widget_id=_MODEL_WIDGET_ID)

    can_save = pipeline.model is not None
    if not can_save:
        imgui.begin_disabled()
    if imgui.button(f"{fa.ICON_FA_FLOPPY_DISK}  Save") and pipeline.model is not None:
        MODELS_DIR.mkdir(exist_ok=True)
        slug = _slug(MODEL_NAMES[selected_model_idx])
        ts = _time.strftime("%Y%m%d_%H%M%S")
        path = MODELS_DIR / f"{slug}_{ts}.joblib"
        save_model(pipeline.model, str(path))
        app.ctx.log(f"Model saved → {path}")
    if not can_save:
        imgui.end_disabled()
    imgui.same_line()
    if imgui.button(f"{fa.ICON_FA_FOLDER_OPEN}  Load..."):
        MODELS_DIR.mkdir(exist_ok=True)
        _load_dialog = pfd.open_file("Load model", str(MODELS_DIR), ["Model", "*.joblib"])
    imgui.same_line()
    imgui.text_disabled(f"({len(_list_saved())} saved)")

    if _load_dialog is not None and _load_dialog.ready():  # type: ignore[union-attr]
        result = _load_dialog.result()  # type: ignore[union-attr]
        _load_dialog = None
        if result:
            try:
                pipeline.model = load_model(result[0])
                app.ctx.log(f"Model loaded ← {result[0]}")
            except Exception as e:
                app.ctx.log(f"Load failed: {e}")


def _filter_block() -> None:
    output_filter.ui()


def _sessions_block() -> None:
    pipeline.training_data = session_manager("sessions", class_names=CLASSES)


def _prediction_block() -> None:
    prediction_label(pipeline, CLASSES)


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
    app.run()


if __name__ == "__main__":
    main()
