"""Multi-model classification demo: 32-ch fake EMG → MyoVerse features →
selectable classifier → VHI hand pose.

Run with:
    uv run python examples/synthetic/emg_32ch_multi_model.py

Workflow:
    1. Launch "EMG Generator 32ch" → signal appears.
    2. Click Rest / Fist / Pinch / Open to switch the generator's class
       (signal pattern + label sample).
    3. Record one trial per class.
    4. In "Model" dropdown pick CatBoost / Random Forest / Extra Trees /
       Logistic Regression / Dummy Constant.
    5. Click Train → Predict — VHI hand follows the predicted class.

Mirrors `emg_classification.py` but expands to 32 channels and 4 classes, and lets
you compare classifiers side-by-side without editing the file.
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

from myogestic import App, Fr, Grid, Px, Stream, TrainingData
from myogestic.vhi.interfaces import virtual_hand
from myogestic.ml import Pipeline
from myogestic.ml.widgets import predict_button, train_button, training_log
from myogestic.ml import load_pickle, save_pickle
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
from myogestic.widgets import (
    app_logo,
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

# Per-class 9-DOF hand poses. Library only ships the rest pose conceptually;
# anything richer is experiment-specific and lives here.
HAND_POSES: dict[int, np.ndarray] = {
    0: np.zeros(9, dtype=np.float32),                                       # Rest
    1: np.array([-1, 0, -1, -1, -1, -1, 0, 0, 0], dtype=np.float32),        # Fist
    2: np.array([-0.7, 0, -0.8, -0.6, 0, 0, 0, 0, 0], dtype=np.float32),    # Pinch
    3: np.array([0.5, 0, 0.5, 0.5, 0.5, 0.5, 0, 0, 0], dtype=np.float32),   # Open
}

rms_transform = RMS(window_size=32)
mav_transform = MAV(window_size=32)
wl_transform = WaveformLength(window_size=32)


def extract_features(emg: np.ndarray) -> np.ndarray:
    """RMS + MAV + WL on a (n_channels, n_samples) window."""
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

app = App("EMG 32ch Multi-Model", ui_scale=0.85)
app.streams(
    Stream("emg", source=LSLSource("TestEMG32"), window_seconds=WIN_SECONDS, buffer_seconds=60)
)
pipeline = Pipeline(app)
# Wire generic save/load so save_model_button / load_model_button work, and
# so the example's custom picker can call them through the pipeline too.
pipeline.save_model = save_pickle
pipeline.load_model = load_pickle

MODELS_DIR = Path("models")


@pipeline.extract
def extract(windows) -> np.ndarray:
    return extract_features(windows["emg"])


# --- Model recipes (kept in the example, NOT in the library) ---------------

MODEL_RECIPES: dict[str, Callable[[], Any]] = {
    "CatBoost": lambda: catboost_classifier(iterations=150),
    "Random Forest": lambda: sklearn_classifier(
        n_estimators=200, random_state=0, n_jobs=-1
    ),
    "Extra Trees": lambda: sklearn_extra_trees_classifier(
        n_estimators=300, random_state=0, n_jobs=-1
    ),
    "Logistic Regression": lambda: sklearn_logistic_classifier(max_iter=1000),
    "Dummy Constant": lambda: constant_classifier(0),
}
MODEL_NAMES = list(MODEL_RECIPES)
selected_model_idx = 0


_load_dialog: object | None = None  # in-flight pfd.open_file future, None if idle

# Local autoscroll + popout state for the custom model_panel — equivalent
# to what pipeline_panel manages internally, but we own it here because
# we don't call pipeline_panel directly (custom layout with the recipe
# selector + save/load row).
_MODEL_WIDGET_ID = "ml_multi"
_autoscroll_on = True
_popout_open = False


def _slug(name: str) -> str:
    """Filesystem-safe recipe slug — strip everything outside [A-Za-z0-9_-]."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "model"


def _list_saved_models() -> list[Path]:
    """Saved models, newest first. Empty if the directory does not exist yet."""
    if not MODELS_DIR.is_dir():
        return []
    return sorted(MODELS_DIR.glob("*.joblib"), key=lambda p: p.stat().st_mtime, reverse=True)


def _save_current() -> Path | None:
    """Save `pipeline.model` under `models/<recipe>_<timestamp>.joblib`."""
    if pipeline.model is None:
        return None
    MODELS_DIR.mkdir(exist_ok=True)
    slug = _slug(MODEL_NAMES[selected_model_idx])
    ts = _time.strftime("%Y%m%d_%H%M%S")
    path = MODELS_DIR / f"{slug}_{ts}.joblib"
    save_pickle(pipeline.model, str(path))
    return path


def model_panel() -> None:
    """Combined MODEL panel: recipe dropdown + Train + Predict + log + save/load.

    Replaces the framework's `pipeline_panel(pipeline)` so the recipe
    selector and per-model persistence live next to the actions that
    modify them. Save auto-names the file by recipe + timestamp (one
    click); Load opens a native file dialog rooted at ``models/``.

    Log inherits the same autoscroll + popout UX as ``pipeline_panel``
    and the process launcher's log — same icons, same tooltips.
    """
    global selected_model_idx, _load_dialog, _autoscroll_on, _popout_open

    # Render the popout window first so it survives even if this panel
    # scrolls out of view next frame (same pattern as pipeline_panel).
    if _popout_open:
        still_open = render_log_popout(
            _MODEL_WIDGET_ID,
            pipeline.train_log,
            title="Model training log",
            autoscroll=_autoscroll_on,
        )
        if not still_open:
            _popout_open = False

    panel_header("MODEL", fa.ICON_FA_BRAIN)

    imgui.push_item_width(-1)
    _, selected_model_idx = imgui.combo(
        "##model_selector", selected_model_idx, MODEL_NAMES
    )
    imgui.pop_item_width()

    train_button(pipeline)
    imgui.same_line()
    predict_button(pipeline)
    imgui.same_line()
    _autoscroll_on, _popout_open = render_log_buttons(
        _MODEL_WIDGET_ID, autoscroll=_autoscroll_on, popped_out=_popout_open
    )

    if _popout_open:
        imgui.text_disabled(
            "(log popped out — see 'Model training log' window)"
        )
    else:
        training_log(pipeline, height=80.0, widget_id=_MODEL_WIDGET_ID)

    # --- Save / Load ------------------------------------------------------
    can_save = pipeline.model is not None
    if not can_save:
        imgui.begin_disabled()
    if imgui.button(f"{fa.ICON_FA_FLOPPY_DISK}  Save"):
        path = _save_current()
        if path is not None:
            app.ctx.status_message = f"Saved → {path.name}"
            app.ctx.log(f"Model saved → {path}")
    if not can_save:
        imgui.end_disabled()

    imgui.same_line()
    if imgui.button(f"{fa.ICON_FA_FOLDER_OPEN}  Load..."):
        # Make the directory before launching the dialog so it exists as the
        # initial root; harmless when it already does.
        MODELS_DIR.mkdir(exist_ok=True)
        _load_dialog = pfd.open_file(
            "Load model",
            str(MODELS_DIR),
            ["Model", "*.joblib"],
        )
    imgui.same_line()
    imgui.text_disabled(f"({len(_list_saved_models())} saved in {MODELS_DIR})")

    # Poll the in-flight dialog (if any). pfd's open_file returns list[str];
    # cancel produces an empty list.
    if _load_dialog is not None and _load_dialog.ready():  # type: ignore[union-attr]
        result = _load_dialog.result()  # type: ignore[union-attr]
        _load_dialog = None
        if result:
            path = Path(result[0])
            try:
                pipeline.model = load_pickle(str(path))
                app.ctx.status_message = f"Loaded ← {path.name}"
                app.ctx.log(f"Model loaded ← {path}")
            except Exception as e:
                app.ctx.status_message = f"Load failed: {e}"
                app.ctx.log(f"Model load failed: {e}")


# --- Train / predict --------------------------------------------------------



@pipeline.train
def train(data: TrainingData):
    """Train the currently-selected model on labeled windows from the
    selected sessions. Active class chips filter which trials get used."""
    log = pipeline.train_log
    log.clear()

    if data.is_empty:
        raise ValueError("No sessions selected. Tick at least one in the list.")
    if len(data.classes) < 2:
        active = sorted(data.classes)
        names = [CLASSES[i] if 0 <= i < len(CLASSES) else f"c{i}" for i in active]
        raise ValueError(
            f"Need ≥2 active classes — got {len(active)} ({names}). "
            f"Toggle more class chips on."
        )

    all_X: list[np.ndarray] = []
    all_y: list[int] = []
    for window, _ts, ci in iter_labeled_windows(
        data.paths,
        "emg",
        WIN_SECONDS,
        HOP_SECONDS,
        classes=data.classes,
    ):
        all_X.append(extract_features(window))
        all_y.append(ci)

    if len(all_X) < 2:
        raise ValueError(f"Need at least 2 windows, got {len(all_X)}")
    X = np.stack(all_X)
    y = np.array(all_y)
    if len(np.unique(y)) < 2:
        raise ValueError(f"Need at least 2 classes, got {len(np.unique(y))}")

    model_name = MODEL_NAMES[selected_model_idx]
    log.append(f"Model: {model_name}")
    log.append(f"X: {X.shape}, y: {y.shape}, classes: {sorted(set(y))}")

    # Held-out 80/20 split — comparing classifiers on training accuracy
    # is misleading (any tree-ensemble overfits to ~100%); a hold-out
    # score is the cheapest meaningful signal for "is this recipe better".
    rng = np.random.default_rng(0)
    perm = rng.permutation(len(X))
    cut = max(1, int(0.8 * len(X)))
    tr, te = perm[:cut], perm[cut:]
    model = MODEL_RECIPES[model_name]()
    model.fit(X[tr], y[tr])

    if len(te) and hasattr(model, "score"):
        try:
            log.append(f"Held-out accuracy ({len(te)} samples): {model.score(X[te], y[te]):.2%}")
        except Exception as e:
            log.append(f"score() failed: {e}")
    return model


@pipeline.predict
def predict(model, features):
    """Classify → look up hand pose → smooth → push to VHI.

    Some recipes (e.g. constant_classifier in degenerate cases) lack
    predict_proba, so we branch on availability instead of requiring it.
    """
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


LOGO_CELL_W = 300
WORDMARK_ASPECT = 800 / 540
grid = Grid(
    7,
    3,
    row_height=[Px(LOGO_CELL_W / WORDMARK_ASPECT), *[Fr(1)] * 6],
    col_width=[Px(LOGO_CELL_W), Fr(1), Fr(1)],
)


def _on_gesture(i: int) -> None:
    ctrl_outlet.push_sample(np.array([CTRL_VALUES[i]], dtype=np.float32))  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]


@app.ui
def demo_ui(ctx):
    with grid[0:5, 1:3]:
        signal_viewer(ctx, "emg", selectable=True)

    with grid[5:7, 1:2]:
        stream_panel(ctx)

    with grid[5:7, 2:3]:
        log_panel(ctx)

    with grid[0, 0]:
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
        pipeline.training_data = session_manager("sessions", class_names=CLASSES)

    with grid[4, 0]:
        model_panel()

    with grid[5, 0]:
        output_filter.ui()

    with grid[6, 0]:
        prediction_label(pipeline, CLASSES)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
