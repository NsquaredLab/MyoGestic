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
from myogestic.ml.widgets import PipelinePanel
from myogestic.widgets import (
    AppLogo,
    PostProcessor,
    PredictionLabel,
    RecordingControls,
    SignalViewer,
    panel_header,
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

# Viewport-width detection, done once at module load. Picks which Grid
# shape to build below. Re-evaluating per frame is unnecessary; users
# who rotate can reload. < 720 catches every phone in portrait and
# leaves tablets (iPad mini portrait = 768 px) on the desktop layout.
import js
_VW = int(js.window.innerWidth)
_VH = int(js.window.innerHeight)
_IS_PHONE = _VW < 720

app = App(
    "MyoGestic Playground",
    ui_scale=1.0 if _IS_PHONE else 0.9,
)
app.streams(Stream("emg", source=BrowserSource(), window_ms=1000, buffer_ms=10000))

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
proba_filter = PostProcessor(hz=20.0)


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


if _IS_PHONE:
    # Single-column stack so the desktop 360 px left column never has to
    # coexist with the signal viewer on a 375 px viewport. Row heights
    # are tuned for portrait phones: the signal_viewer row is large
    # because its controls (Pause / dropdown / Auto / Rescale / two
    # sliders / 8 channel toggles) wrap aggressively on narrow widths
    # and consume ~180 px on their own. Anything less than ~480 px
    # leaves the plot itself a clipped sliver. The page scrolls
    # vertically, so making the stack tall is the right call.
    grid = Grid(
        8, 1,
        row_height=[Px(90), Px(200), Px(500), Px(160),
                    Px(140), Px(220), Px(180), Px(140)],
        col_width=[Fr(1)],
    )
else:
    grid = Grid(
        5, 2,
        row_height=[Px(120), Fr(2), Fr(1), Fr(1), Px(110)],
        col_width=[Px(360), Fr(1)],
    )


# Apply a touch-friendly style bump once on the first frame. ImGui's
# default scrollbar is ~14 px wide, which is impossible to grab with a
# finger; 36 px makes it a clear thumb target. Larger frame padding +
# item spacing keep buttons clear of each other under fat fingers.
_styled = False
def _apply_touch_style():
    global _styled
    if _styled or not _IS_PHONE:
        return
    s = imgui.get_style()
    s.scrollbar_size = 36
    s.frame_padding = imgui.ImVec2(10, 12)
    s.item_spacing = imgui.ImVec2(10, 10)
    _styled = True


def _mobile_panel(label: str, height: float, render):
    """Render `render()` inside a fixed-height bordered child window.

    Using natural ImGui cursor advancement (one child after another)
    instead of the absolute-positioned Grid means ImGui correctly
    accumulates content size, so the outer scrollable child window
    actually has overflow to scroll through. The Grid uses
    set_cursor_pos which doesn't extend the parent's content rect
    cleanly inside a scroll container.
    """
    imgui.begin_child(
        f"##mob_{label}",
        imgui.ImVec2(0, height),
        child_flags=imgui.ChildFlags_.borders,
    )
    try:
        render()
    finally:
        imgui.end_child()


# Widgets are constructed once here and rendered with `.ui(...)` every frame
# inside `@app.ui` (never rebuilt per-frame or inside a lambda).
logo = AppLogo()
rec_controls = RecordingControls(
    CLASSES, on_record=_on_record, on_stop=_on_stop, on_gesture=_on_gesture
)
emg_viewer = SignalViewer("emg")
ml_panel = PipelinePanel(pipeline)
pred_label = PredictionLabel(pipeline, CLASSES, show_probability=True)


@app.ui
def ui(ctx):
    _apply_touch_style()
    if _IS_PHONE:
        # Outer scrollable child fills the viewport. Inner panels are
        # natural-flow children with fixed heights; ImGui's cursor
        # accumulates their sizes into the parent's content rect, so
        # when the total exceeds the viewport the fat scrollbar
        # (36 px from _apply_touch_style) actually scrolls.
        imgui.begin_child(
            "##mobile_scroll",
            imgui.ImVec2(0, 0),
            window_flags=imgui.WindowFlags_.always_vertical_scrollbar,
        )
        try:
            _mobile_panel("logo", 90, lambda: logo.ui())
            _mobile_panel("rec", 200, lambda: rec_controls.ui(ctx))
            _mobile_panel("signal", 500, lambda: emg_viewer.ui(ctx))
            _mobile_panel("pipe", 160, lambda: ml_panel.ui())
            _mobile_panel("pred", 140, lambda: pred_label.ui())
            _mobile_panel("sessions", 220, _sessions_panel)
            _mobile_panel("filter", 180, lambda: proba_filter.ui())

            def _blurb():
                panel_header("Browser playground")
                imgui.text_wrapped(
                    "Tap Record, cycle through gestures, then Stop. "
                    "Train uses every ticked session; Predict drives "
                    "the prediction panel from live features."
                )
            _mobile_panel("blurb", 140, _blurb)
        finally:
            imgui.end_child()
        return

    with grid[0, 0:2]:
        logo.ui()

    with grid[1, 0]:
        rec_controls.ui(ctx)

    with grid[1, 1]:
        emg_viewer.ui(ctx)

    with grid[2, 0]:
        ml_panel.ui()

    with grid[2, 1]:
        pred_label.ui()

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


# On phones the canvas is viewport-sized (no fighting HelloImGui).
# ImGui's own scrollbar - bumped to 36 px in _apply_touch_style above
# so it is finger-grabbable - handles scrolling through the 1700 px
# of stacked panel content.
#
# On desktop we keep the original (1280, 800) preset rather than the
# raw viewport: at 4K (2560 x 1440) the Fr-based Grid stretches every
# panel to fill the screen and the layout looks too spread out.
if _IS_PHONE:
    app.run(window_size=(_VW, _VH))
else:
    app.run(window_size=(1280, 800))
