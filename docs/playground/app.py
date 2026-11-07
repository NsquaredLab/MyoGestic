"""Browser myocontrol: connect, record labelled takes, train LDA, predict.

The public widgets and Session lifecycle are shared with examples/start_here/
myocontrol.py. Pyodide schedules acquisition/prediction per frame and keeps the
ordinary Zarr takes in its temporary filesystem (a reload clears them).
"""

import json
import math
from functools import partial

import js
import numpy as np
from imgui_bundle import imgui

from myogestic import App, Fr, Grid, Layout, Px, Stream, TrainingData
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PredictButton, TrainButton, TrainingLog
from myogestic.recipes.features import rms
from myogestic.session import iter_labeled_windows
from myogestic.sources import SyntheticSource
from myogestic.widgets import (
    AppHeader,
    DevicePicker,
    DeviceSpec,
    LogPanel,
    PostProcessor,
    PredictionLabel,
    RecordingControls,
    SessionManager,
    SignalViewer,
    StatusBar,
    StepBar,
)
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    SUCCESS,
    WARNING,
    muted,
    panel_header,
    segmented,
    ui_px,
)
from myogestic.widgets.panels.recording import TakeStatus

CLASSES = ["Rest", "Fist", "Pinch"]
WINDOW_MS = 250
HOP_MS = 100
PREDICT_HZ = 20
current_class = 0

# SyntheticSource's public live knobs give each gesture a distinct spatial RMS.
# The browser path of read() returns no data until due instead of sleeping.
GESTURES = [(0.0, 0.0), (0.8, 0.0), (0.8, -1.0)]
synthetic = DeviceSpec(
    "Synthetic amplifier",
    partial(
        SyntheticSource, n_channels=8, fs=1024.0, noise=0.05, hum=0.0, activation=0.0,
        waveform="emg",
    ),
    hint="An in-process test signal. No amplifier is needed.",
)
app = App("MyoGestic Playground", ui_scale=1.0, require_participant=True)
app.ctx.participant = "P-DEMO"
stream = Stream("emg", source=synthetic.factory(), window_ms=WINDOW_MS, buffer_ms=10000)
app.streams(stream)
pipeline = Pipeline(app, predict_hz=PREDICT_HZ, input_streams=("emg",))
metrics = {}
proba_filter = PostProcessor(hz=PREDICT_HZ, compact=True)


@pipeline.extract
def extract(windows):
    window = windows.get("emg")
    return None if window is None else rms(window)


@pipeline.train
def train(data: TrainingData):
    """Fit only the saved takes and gesture filters selected in SessionManager."""
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis

    windows = list(
        iter_labeled_windows(
            data.paths,
            "emg",
            WINDOW_MS,
            HOP_MS,
            classes=data.classes or None,
        )
    )
    if len(windows) < 2:
        raise ValueError("Record and select longer takes before training.")
    x = np.stack([extract({"emg": window}) for window, _ts, _label in windows])
    y = np.array([label for _window, _ts, label in windows], dtype=int)
    if len(np.unique(y)) < 2:
        raise ValueError("Record at least two different gestures before training.")
    model = LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto")
    model.fit(x, y)
    metrics.update(
        takes=len(data.paths), windows=len(y), accuracy=float(model.score(x, y))
    )
    pipeline.train_log.append(f"LDA · {len(data.paths)} takes · {len(y)} windows")
    app.ctx.log(f"Trained LDA on {len(y)} saved windows")
    proba_filter.reset()
    return model


@pipeline.predict
def predict(model, features):
    if features is None:
        return None
    # LDA only emits the classes it was fitted on. Keep the full class axis even
    # when the take selection omitted a gesture.
    proba = np.zeros(len(CLASSES), dtype=np.float32)
    proba[model.classes_.astype(int)] = model.predict_proba(features.reshape(1, -1))[0]
    smoothed = proba_filter(proba)
    return {"class": int(np.argmax(smoothed)), "proba": smoothed}


layout = Layout(
    wide=Grid.areas(
        """
        header   header
        signal   step
        signal   sessions
        log      sessions
        status   status
        """,
        row_height=[Px(52), Fr(3), Fr(1), Px(110), Px(26)],
        col_width=[Fr(1), Px(400)],
        bare=("header", "status"),
    ),
    narrow=Grid.areas(
        """
        header
        signal
        step
        sessions
        log
        status
        """,
        row_height=[Px(52), Fr(2), Fr(3), Fr(1.5), Px(110), Px(26)],
        bare=("header", "status"),
    ),
    breakpoint=Px(1100),
)
steps = StepBar(["Connect", "Record", "Train", "Predict"], widget_id="playground_steps")
header = AppHeader("Playground", steps=steps)
device = DevicePicker("emg", devices=[synthetic], show_header=False)
sessions = SessionManager("data", class_names=CLASSES)
sessions.select_all(app.ctx.participant)
viewer = SignalViewer(
    "emg", show_connect=False, show_markers=True, show_controls=False, window_s=5.0
)
log = LogPanel(title="Activity log")
status = StatusBar("emg", pipeline=pipeline)
train_button = TrainButton(pipeline, size=(-1, 0))
training_log = TrainingLog(pipeline, height=80)
predict_button = PredictButton(pipeline, size=(-1, 0))
prediction = PredictionLabel(pipeline, CLASSES, show_probability=True)


def _on_gesture(index):
    global current_class
    current_class = index
    app.ctx.current_label = index
    source = stream._source
    source.activation, source.direction = GESTURES[index]


recording = RecordingControls(
    CLASSES,
    on_record=app.start_recording,
    on_stop=app.stop_recording,
    on_gesture=_on_gesture,
    show_header=False,
    take_lengths=(3.0, 5.0, 10.0),
    warmups=(0.0, 1.0, 2.0, 3.0),
    timed=True,
    take_length=3.0,
    warmup=1.0,
)


def _take_overlay(take: TakeStatus):
    """Show the same warm-up veil and REC chip as the desktop protocol."""
    if take.phase not in ("warmup", "recording"):
        return
    origin, size = imgui.get_window_pos(), imgui.get_window_size()
    pad = ui_px(12)
    left, right = origin.x + pad, origin.x + size.x - pad
    top = origin.y + pad + imgui.get_frame_height_with_spacing()
    bottom = origin.y + size.y - pad
    draw = imgui.get_window_draw_list()
    if take.phase == "warmup":
        surface = imgui.get_style().color_(imgui.Col_.child_bg)
        draw.add_rect_filled(
            imgui.ImVec2(left, top),
            imgui.ImVec2(right, bottom),
            imgui.get_color_u32(imgui.ImVec4(surface.x, surface.y, surface.z, 0.9)),
        )
        text = f"Get ready · {take.gesture} · {math.ceil(take.warmup_left_s)}"
        width = imgui.calc_text_size(text).x
        draw.add_text(
            imgui.ImVec2((left + right - width) / 2, (top + bottom) / 2),
            imgui.get_color_u32(WARNING),
            text,
        )
    else:
        remaining = f" / {take.length_s:g} s" if take.length_s else ""
        text = f"REC {take.gesture} · {take.elapsed_s:.1f} s{remaining}"
        width = imgui.calc_text_size(text).x
        draw.add_rect_filled(
            imgui.ImVec2(right - width - 2 * pad, top),
            imgui.ImVec2(right, top + imgui.get_text_line_height() + pad),
            imgui.get_color_u32(imgui.get_style().color_(imgui.Col_.popup_bg)),
        )
        draw.add_text(
            imgui.ImVec2(right - width - pad, top + pad / 2),
            imgui.get_color_u32(DANGER),
            text,
        )


def _train_ui():
    imgui.text_wrapped("LDA classifier · per-channel RMS · 250 ms windows")
    train_button.ui()
    if metrics:
        imgui.text(f"{metrics['takes']} takes · {metrics['windows']} windows")
        imgui.text(f"Training accuracy: {metrics['accuracy']:.1%}")
    training_log.ui()


def _predict_ui():
    imgui.begin_disabled(stream.status != "connected")
    predict_button.ui()
    imgui.end_disabled()
    prediction.ui()
    proba_filter.ui()
    imgui.spacing()
    imgui.text_colored(muted(), "Simulated gesture")
    selected = segmented("synthetic-gesture", CLASSES, current_class)
    if selected != current_class and not app.ctx.recording:
        _on_gesture(selected)


# Passive lifecycle/geometry evidence for the browser checks. Nothing here can
# invoke a workflow action; the tests operate the canvas's real controls.
_published_state = None
panel_bounds = {}


def _panel(name):
    pos, size = imgui.get_window_pos(), imgui.get_window_size()
    panel_bounds[name] = [
        round(pos.x, 1),
        round(pos.y, 1),
        round(size.x, 1),
        round(size.y, 1),
    ]


def _publish_state():
    global _published_state
    summary = sessions.selection()
    predicted = pipeline.predictions.get("class")
    data = pipeline.training_data
    state = {
        "state": str(app.ctx.state),
        "participant": app.ctx.participant,
        "connected": stream.status == "connected",
        "step": steps.steps[steps.active],
        "recording": app.ctx.recording,
        "take": recording.take.phase,
        "timed": recording.take.timed,
        "gesture": CLASSES[current_class],
        "prediction": CLASSES[predicted] if predicted is not None else None,
        "trained": pipeline.model is not None,
        "sessions": {
            "total": summary.n_total,
            "selected": summary.n_selected,
            "classes": summary.class_seconds,
            "paths": data.paths if data else [],
        },
        "metrics": metrics,
        "panels": panel_bounds,
    }
    serialized = json.dumps(state, sort_keys=True)
    if serialized != _published_state:
        js.document.body.setAttribute("data-mg-state", serialized)
        _published_state = serialized


@app.ui
def ui(ctx):
    done = [
        stream.status == "connected",
        sessions.selection().n_total > 0,
        pipeline.model is not None,
        ctx.state == "predicting",
    ]
    with layout["header"]:
        _panel("header")
        # The HTML Docs link occupies this row's rightmost 80 px. Give the real
        # AppHeader the rest so its navigation can compact normally on phones.
        width = imgui.get_content_region_avail().x - ui_px(80)
        header.show_state = imgui.get_window_size().x >= ui_px(1100)
        imgui.begin_child(
            "header-content",
            imgui.ImVec2(max(1, width), 0),
            window_flags=imgui.WindowFlags_.no_background
            | imgui.WindowFlags_.no_scrollbar
            | imgui.WindowFlags_.no_scroll_with_mouse,
        )
        active = header.ui(ctx, done)
        imgui.end_child()
    padding = imgui.get_style().window_padding
    imgui.push_style_var(
        imgui.StyleVar_.window_padding, imgui.ImVec2(padding.x, ui_px(4))
    )
    if active != 1:
        recording.ui(ctx, visible=False)
    with layout["sessions"]:
        _panel("sessions")
        pipeline.training_data = sessions.ui(participant=ctx.participant)
    with layout["step"]:
        _panel("step")
        tone = SUCCESS if done[0] else IDLE
        panel_header(steps.steps[active], status=tone if active == 0 else None)
        if active == 0:
            device.ui(ctx)
            _on_gesture(current_class)
            imgui.text_wrapped(
                "Connect the synthetic amplifier, then record each gesture."
            )
            imgui.text_colored(muted(), f"Participant · {ctx.participant}")
            imgui.text_wrapped("Takes stay in this browser tab. Reloading clears them.")
        elif active == 1:
            imgui.begin_disabled(not done[0])
            recording.ui(ctx)
            imgui.end_disabled()
        elif active == 2:
            _train_ui()
        else:
            _predict_ui()
    with layout["signal"]:
        _panel("signal")
        viewer.ui(ctx)
        _take_overlay(recording.take)
    with layout["log"]:
        _panel("log")
        log.ui(ctx)
    imgui.pop_style_var()
    with layout["status"]:
        _panel("status")
        status.ui(ctx)
    _publish_state()


app.run(window_size=(int(js.window.innerWidth), int(js.window.innerHeight)))
