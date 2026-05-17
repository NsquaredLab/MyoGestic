"""MyoGestic playground app - synthetic EMG, sklearn LDA, live in the browser.

Kept in a separate file (not the <script type="text/python"> tag) so it
can be edited in any Python tool and shipped via fetch() at boot. The
loader does ``pyodide.runPython(await fetch('app.py').text())`` after
all deps and shims are in place.
"""

import time
from collections import deque

import numpy as np

from myogestic import App, Fr, Grid, Px, Stream, StreamInfo, TrainingData
from myogestic.ml import Pipeline
from myogestic.ml.widgets import pipeline_panel
from myogestic.widgets import (
    FilterControl,
    app_logo,
    panel_header,
    prediction_label,
    recording_controls,
    signal_viewer,
)
from imgui_bundle import imgui


# ----------------------------------------------------------------------
# Synthetic, class-modulated EMG source
#
# Browser substitute for an LSL inlet: emits 8 channels at 256 Hz where
# the amplitude/shape depends on whichever class the user last picked in
# the recording_controls strip. Each click on a gesture button mutates
# `current_class`; the source's read() reads that global.
# ----------------------------------------------------------------------

FS = 256.0
N_CHANNELS = 8
N_CHUNK = 16  # samples per read() - 16 / 256 = 62.5 ms per chunk

CLASSES = ["Rest", "Fist", "Pinch"]
current_class = 0  # mutated by _on_gesture


def _class_signature(class_idx: int, t: np.ndarray) -> np.ndarray:
    """Per-channel amplitude pattern for each class. Returns (n_ch, n_samp)."""
    base = 0.05 * np.random.randn(N_CHANNELS, t.shape[0])
    if class_idx == 0:    # Rest - low noise floor
        return base
    if class_idx == 1:    # Fist - all channels active, ~5 Hz envelope
        env = 0.8 * (0.6 + 0.4 * np.sin(2 * np.pi * 5 * t))
        return base + env * np.sin(2 * np.pi * 50 * t)
    if class_idx == 2:    # Pinch - channels 0,1,2 active, others quiet
        env = 0.7 * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))
        out = base.copy()
        out[:3] += env * np.sin(2 * np.pi * 60 * t)
        return out
    return base


class BrowserSource:
    """Non-blocking synthetic source. Same contract as LSLSource.

    In the browser, time.sleep blocks the single event loop, so this
    source pacing is *return-based*: read() returns (None, None) until
    a full chunk's worth of wall-clock time has elapsed. The framework's
    async acquire loop will sleep briefly and try again.
    """

    def __init__(self):
        self._t = 0
        self._next_tick = None

    def connect(self) -> StreamInfo:
        self._next_tick = time.monotonic()
        return StreamInfo(
            n_channels=N_CHANNELS,
            fs=FS,
            dtype=np.dtype(np.float32),
            channel_names=[f"ch{i}" for i in range(N_CHANNELS)],
        )

    def read(self):
        # Non-blocking: if the next chunk's worth of wall-clock hasn't
        # arrived yet, tell the framework "nothing right now."
        now = time.monotonic()
        if now < self._next_tick:
            return None, None
        chunk_target_end = self._next_tick + N_CHUNK / FS
        self._next_tick = chunk_target_end

        t = (self._t + np.arange(N_CHUNK)) / FS
        self._t += N_CHUNK

        data = _class_signature(current_class, t).T.astype(np.float32)  # (n_samples, n_ch)
        ts = (chunk_target_end + (np.arange(N_CHUNK) - (N_CHUNK - 1)) / FS).astype(np.float64)
        return data, ts

    def disconnect(self):
        pass


# ----------------------------------------------------------------------
# App + Stream + Pipeline
# ----------------------------------------------------------------------

app = App("MyoGestic Playground", ui_scale=0.9)
app.streams(Stream("emg", source=BrowserSource(), window_seconds=1.0, buffer_seconds=10))

pipeline = Pipeline(app)
# The Pipeline.start_training gate rejects empty TrainingData. The
# playground doesn't have on-disk sessions, so we hand it a single
# placeholder path to pass the gate. The actual training data is read
# from the `sessions` list inside @pipeline.train.
pipeline.training_data = TrainingData(
    paths=["__browser_in_memory__"],
    class_names=CLASSES,
    classes=set(range(len(CLASSES))),
)


def _rms(window: np.ndarray) -> np.ndarray:
    """Per-channel RMS - the simplest possible feature."""
    return np.sqrt(np.mean(window ** 2, axis=1)).astype(np.float32)


@pipeline.extract
def extract(windows):
    return _rms(windows["emg"])


# In-memory recording substitute for zarr (which needs threads).
# While ctx.state == "recording", the sampler step grabs one feature
# vector per tick and tags it with the currently selected gesture.
# When the user clicks Stop, the buffer is frozen into a Session entry
# and a fresh buffer takes over for the next cycle.
recorded_X: list[np.ndarray] = []
recorded_y: list[int] = []
sessions: list[dict] = []  # each: {"name": str, "X": list, "y": list, "use": bool}


def _recording_sampler() -> float:
    """Per-frame sampler called by the browser scheduler.

    Captures one (features, label) pair every ~200 ms while recording.
    A real desktop session writes ~`fs` samples/sec to zarr; we don't
    need that throughput because the trainer only needs ~30-60 windows
    per class to fit a clean LDA on this synthetic dataset.
    """
    if app.ctx.state != "recording":
        return 0.05  # poll the state cheaply when idle
    try:
        stream = app.ctx.streams["emg"]
    except KeyError:
        return 0.5
    data, _ts = stream.get_window()
    if data.size == 0:
        return 0.05
    recorded_X.append(_rms(data))
    recorded_y.append(current_class)
    return 0.2


@pipeline.train
def train(_data):
    """Train an LDA on every ticked session.

    Falls back to a synthesised per-class dataset when nothing has been
    recorded yet, so a first-time visitor can still click Train -> Predict
    without having to run the record loop first.
    """
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis

    log = pipeline.train_log
    log.clear()

    picked = [s for s in sessions if s["use"]]
    X_chunks: list[np.ndarray] = []
    y_chunks: list[int] = []
    for s in picked:
        X_chunks.extend(s["X"])
        y_chunks.extend(s["y"])

    if X_chunks:
        X = np.stack(X_chunks)
        y = np.array(y_chunks)
        log.append(
            f"Training on {len(picked)} session(s), "
            f"{len(X_chunks)} windows total."
        )
    else:
        log.append("No sessions ticked; synthesising a fallback dataset.")
        X_list, y_list = [], []
        n_per_class = 60
        for class_idx in range(len(CLASSES)):
            for _ in range(n_per_class):
                t = np.arange(int(FS)) / FS
                window = _class_signature(class_idx, t)
                X_list.append(_rms(window))
                y_list.append(class_idx)
        X = np.stack(X_list)
        y = np.array(y_list)

    log.append(f"X: {X.shape}, y: {y.shape}")
    classes_present = sorted(set(y.tolist()))
    if len(classes_present) < 2:
        log.append(
            f"Only one class in the picked data ({CLASSES[classes_present[0]]}). "
            "Record at least two classes before training."
        )
        return None
    model = LinearDiscriminantAnalysis()
    model.fit(X, y)
    log.append(f"Training complete (LDA, classes={classes_present}).")
    return model


def _sessions_panel() -> None:
    """Lightweight in-memory equivalent of session_manager.

    Each row: tickbox + name + per-class window count. Tickbox controls
    whether the session contributes to the next Train call. Clear All
    nukes the list (useful when iterating).
    """
    panel_header("Sessions")
    if not sessions:
        imgui.text_disabled("No sessions yet. Click Record -> a few gestures -> Stop.")
        return
    for s in sessions:
        # Per-class counts, e.g. "Rest:8 Fist:7 Pinch:5"
        counts = [0] * len(CLASSES)
        for lbl in s["y"]:
            if 0 <= lbl < len(CLASSES):
                counts[lbl] += 1
        breakdown = "  ".join(
            f"{CLASSES[i]}:{counts[i]}" for i in range(len(CLASSES)) if counts[i]
        )
        changed, s["use"] = imgui.checkbox(f"##use_{s['name']}", s["use"])
        imgui.same_line()
        imgui.text(f"{s['name']}  ({len(s['X'])} windows)")
        if breakdown:
            imgui.same_line()
            imgui.text_disabled(f"  {breakdown}")
    imgui.spacing()
    if imgui.button("Clear all"):
        sessions.clear()


# Live-tunable post-processing smoother. Same widget the desktop demos
# use to smooth a 9-DoF pose before pushing to VHI; here we feed it the
# per-class probability vector so the prediction_label's confidence bar
# smooths instead of jittering frame-to-frame.
proba_filter = FilterControl(hz=20.0, default="one_euro")


@pipeline.predict
def predict(model, features):
    proba = model.predict_proba(features.reshape(1, -1))[0].astype(np.float32)
    smoothed = proba_filter(proba)
    idx = int(np.argmax(smoothed))
    return {"class": idx, "proba": smoothed}


# ----------------------------------------------------------------------
# Callbacks + UI
# ----------------------------------------------------------------------


def _on_record():
    # The real app.start_recording() initialises a zarr Session, and
    # zarr v3's sync API starts an iothread - which Pyodide forbids.
    # The playground records to in-memory lists instead via the
    # _recording_sampler step registered with the browser scheduler.
    # Setting ctx.state directly flips the recording_controls widget
    # (Record button -> Stop button) without needing a Session object.
    recorded_X.clear()
    recorded_y.clear()
    app.ctx.state = "recording"


def _on_stop():
    app.ctx.state = "idle"
    # Freeze the current buffer into a session entry so subsequent
    # records don't overwrite it. Sessions are time-stamped by their
    # ordinal so the list reads chronologically.
    if recorded_X:
        sessions.append({
            "name": f"session_{len(sessions) + 1:02d}",
            "X": list(recorded_X),
            "y": list(recorded_y),
            "use": True,
        })


def _on_gesture(i: int):
    global current_class
    current_class = i


# Register the in-memory sampler so it ticks once per ImGui frame and
# captures (features, label) pairs while the user is "recording".
from myogestic._browser import register as _browser_register
_browser_register(_recording_sampler)


grid = Grid(
    5, 2,
    row_height=[Px(120), Fr(2), Fr(1), Fr(1), Px(110)],
    col_width=[Px(360), Fr(1)],
)


@app.ui
def ui(ctx):
    with grid[0, 0:2]:
        app_logo()

    with grid[1, 0]:
        recording_controls(
            ctx, CLASSES,
            on_record=_on_record,
            on_stop=_on_stop,
            on_gesture=_on_gesture,
        )

    with grid[1, 1]:
        signal_viewer(ctx, "emg")

    with grid[2, 0]:
        pipeline_panel(pipeline)

    with grid[2, 1]:
        prediction_label(pipeline, CLASSES, show_probability=True)

    with grid[3, 0]:
        _sessions_panel()

    with grid[3, 1]:
        proba_filter.ui()

    with grid[4, 0:2]:
        panel_header("Browser playground")
        imgui.text_wrapped(
            "Click Record, cycle through gestures, then Stop. The "
            "session is saved in memory. Train uses every ticked "
            "session; Predict drives the prediction panel from live "
            "features. The filter on the right smooths the per-class "
            "probability so the confidence bar doesn't jitter."
        )


app.run(window_size=(1280, 800))
