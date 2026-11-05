"""Magic Piano: record a finger lesson, train, then play songs one finger at a time.

Seven classes from one forearm: Rest, Thumb to Pinky, and Fist. Seven classes are a lot
to ask of a subject, and a confusion matrix gives them no reason to keep at it. A piano
does: each finger is a key, a song asks for them in order, and a missed note names the
finger the model has not learned. Rest and Fist play nothing; they are there so the
model learns what *not* playing looks like.

The amplifier defaults to the Quattrocento in its 384-channel mode at 2048 Hz, the
smallest mode that carries a montage of around 320 channels. Connect picks another, or
the synthetic hand, which plays without one at the same size: hold keys 1 to 5 to bend
a finger.

**Record** runs the lesson as one take, cueing each movement and labelling it as it
goes. **Train** fits a classifier and then checks every finger on held-out windows;
a model that cannot tell one finger apart is refused by name, because that finger's
key would never play. **Play** runs the model through `PianoGate`, so a held finger
strikes once and an ambiguous prediction stays silent.

**Record take** in Play saves what was played, not just the EMG. Beside the signal,
the take holds the features and class scores of every prediction, the key the gate let
through (``prediction.note``), the key the song asked for (``prediction.cue``), the
model that played (``model.joblib``) and each finished song's score (``meta.json``,
under ``piano``). Every trained model is also saved under ``sessions/``.

Run with:
    uv run --extra examples python examples/start_here/magic_piano.py
"""

import dataclasses
import functools
import pathlib
import time
from types import SimpleNamespace

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic import App, Context, Fr, Grid, Layout, Px, Stream, TrainingData
from myogestic._theme import display_font
from myogestic.ml import Pipeline, save_pickle
from myogestic.ml.widgets import TrainButton, TrainingLog
from myogestic.recipes.estimators import catboost_classifier
from myogestic.recipes.features import mav, rms, var, wl, zc
from myogestic.session import iter_labeled_windows
from myogestic.sources import SyntheticSource
from myogestic.stream import StreamInfo
from myogestic.widgets import (
    DEFAULT_DEVICES,
    AppHeader,
    DevicePicker,
    DeviceSpec,
    FeatureSelector,
    LogPanel,
    ParticipantPanel,
    PianoGate,
    PianoTask,
    PredictionLabel,
    SessionManager,
    SignalViewer,
    StatusBar,
    StepBar,
)
from myogestic.widgets.common import (
    CONSOLE_BG,
    CONSOLE_TEXT,
    DANGER,
    IDLE,
    PALETTE,
    SUCCESS,
    WARNING,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    primary_button,
    push_selected,
    tinted_row,
    ui_px,
)
from myogestic.widgets.piano import FINGERS, PIANO_CLASSES, check_calibration

# The live Stream window is also the training window: a model fitted on 200 ms of
# signal is fed 200 ms at predict time.
WINDOW_MS = 200
HOP_MS = 100
#: The gate's timings (`myogestic.widgets.piano`) were tuned at this rate.
PREDICT_HZ = 32
CLASSES = list(PIANO_CLASSES)
# Shallow and short on purpose: at 320 channels x 3 features, CatBoost's defaults with
# 150 iterations took 52-89 s for the check plus the fit; this takes about 8 s, and
# grows with every lesson ticked. Softmax scores, which is what the gate is tuned on.
ITERATIONS = 100
DEPTH = 4
#: Folds of the held-out finger check that runs before every fit.
CHECK_FOLDS = 3

#: The lesson: every movement but Rest held for `HOLD_S`, each followed by `REST_S` of
#: Rest, `LESSON_ROUNDS` times over, after `READY_S` to settle.
LESSON_ROUNDS = 3
HOLD_S = 3.0
REST_S = 2.0
READY_S = 3.0
#: Each cue's first half second is left unlabelled, so the subject's reaction to a cue
#: is not trained as the movement it asks for.
REACT_S = 0.5
LESSON = [
    ("Get ready", -1, READY_S),
    *(
        step
        for _ in range(LESSON_ROUNDS)
        for index, name in enumerate(CLASSES)
        if index
        for step in ((name, index, HOLD_S), ("Rest", 0, REST_S))
    ),
]
LESSON_S = sum(seconds for *_, seconds in LESSON)
#: The synthetic hand's channels per finger: 5 x 64 = 320.
CHANNELS_PER_FINGER = 64


class DummyHandSource:
    """A synthetic hand for trying the piano without an amplifier.

    A block of `CHANNELS_PER_FINGER` channels per finger, 320 in all, so a dry run trains
    on as many features as a Quattrocento montage gives. Bending a finger raises its
    block out of a quiet floor; a fist raises every channel. That separates all seven
    classes, which is all a dry run of this app needs.
    """

    def __init__(self) -> None:
        self._source = SyntheticSource(n_channels=CHANNELS_PER_FINGER * len(FINGERS))
        #: The class being made now, an index into `CLASSES`.
        self.gesture = 0

    def connect(self) -> StreamInfo:
        return self._source.connect()

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        data, ts = self._source.read()
        if data is not None:
            gains = np.full(data.shape[1], 0.05, dtype=np.float32)
            if 1 <= self.gesture <= len(FINGERS):
                block = CHANNELS_PER_FINGER * (self.gesture - 1)
                gains[block : block + CHANNELS_PER_FINGER] = 1.0
            elif self.gesture == len(FINGERS) + 1:
                gains[:] = 0.6
            data *= gains
        return data, ts

    def disconnect(self) -> None:
        self._source.disconnect()


_STOCK_QUATTROCENTO = next(d for d in DEFAULT_DEVICES if d.label == "Quattrocento")
# The 384-channel mode as the default, in the dropdown and in the seeded stream alike;
# the stock entry opens on 192, which cannot carry a ~320-channel montage.
QUATTROCENTO = dataclasses.replace(
    _STOCK_QUATTROCENTO, factory=functools.partial(_STOCK_QUATTROCENTO.factory, nch_mode=3)
)
DEVICES = (
    QUATTROCENTO,
    *(d for d in DEFAULT_DEVICES if d is not _STOCK_QUATTROCENTO),
    DeviceSpec(
        "Synthetic hand (keys 1-5 bend a finger)",
        DummyHandSource,
        hint="A test hand for trying the piano without hardware, not EMG.",
    ),
)

app = App("MyoGestic — magic piano", require_participant=True)
app.ctx.class_names = CLASSES
app.streams(Stream("emg", source=QUATTROCENTO.factory(), window_ms=WINDOW_MS))
pipeline = Pipeline(app, predict_hz=PREDICT_HZ, input_streams=("emg",))
# Saves every trained model under sessions/, and the playing model into each take.
pipeline.save_model = save_pickle
pipeline.autosave_dir = "sessions"
features = FeatureSelector(
    {"RMS": rms, "MAV": mav, "WL": wl, "VAR": var, "ZC": zc},
    default=["RMS", "MAV", "WL"],
    show_header=False,
)
gate = PianoGate()
piano = PianoTask()
#: The key the song asks for now. Written by the UI every frame and read by `predict`,
#: so each recorded prediction carries the cue it answered.
song_cue = {"key": -1}
#: When the running lesson began (``None`` when none is), and the label last written.
lesson: dict = {"start": None, "label": None}
#: How many songs had finished when the open take began.
take = {"songs": 0}
#: Whether the synthetic hand plays the song by itself.
simulated = {"auto": False}


def _classifier():
    return catboost_classifier(iterations=ITERATIONS, depth=DEPTH)


@pipeline.extract
def extract(windows: dict[str, np.ndarray]) -> np.ndarray | None:
    """Active features of the EMG window, stacked along axis 0."""
    window = windows.get("emg")
    return None if window is None else features(window)


@pipeline.train
def train(data: TrainingData) -> SimpleNamespace:
    """Fit the seven-class model, after checking every class on held-out windows.

    The check runs first and refuses a model with a finger it cannot recognise: that
    finger's key would never play, and good overall accuracy hides it. Each class is
    cut into three contiguous thirds, one per fold, so the overlapping windows of one
    hold rarely sit on both sides of a split.
    """
    if data.is_empty:
        raise ValueError("No sessions selected. Record a lesson, then tick it in Sessions.")
    if features.n_active == 0:
        raise ValueError("No features ticked (RMS, MAV and WL are the default).")
    xs: list[np.ndarray] = []
    ys: list[int] = []
    for window, _ts, class_idx in iter_labeled_windows(
        data.paths, "emg", WINDOW_MS, HOP_MS, classes=data.classes or None
    ):
        xs.append(extract({"emg": window}))
        ys.append(class_idx)
    missing = [name for i, name in enumerate(CLASSES) if i not in set(ys)]
    if missing:
        raise ValueError(f"No windows of {', '.join(missing)}. Tick a complete lesson.")
    x, y = np.stack(xs), np.array(ys)

    fold = np.empty(len(y), dtype=int)
    for c in range(len(CLASSES)):
        members = np.flatnonzero(y == c)
        fold[members] = np.arange(len(members)) * CHECK_FOLDS // len(members)
    held_out = np.empty_like(y)
    for k in range(CHECK_FOLDS):
        model = _classifier().fit(x[fold != k], y[fold != k])
        held_out[fold == k] = np.asarray(model.predict(x[fold == k])).ravel()
    recall = [float(np.mean(held_out[y == c] == c)) for c in range(len(CLASSES))]
    accuracy = float(np.mean(held_out == y))
    report = {
        "accuracy": round(accuracy, 3),
        "recall": {name: round(float(r), 3) for name, r in zip(CLASSES, recall, strict=True)},
    }
    app.ctx.log(
        "[check] "
        + " · ".join(f"{name} {r:.0%}" for name, r in report["recall"].items())
        + f" · accuracy {accuracy:.0%}"
    )
    check_calibration(recall, accuracy)

    estimator = _classifier()
    estimator.fit(x, y)
    app.ctx.log(f"[train] {len(x)} windows from {len(data.paths)} sessions")
    # `report` is what `Pipeline` writes into every take's meta.json beside the model.
    return SimpleNamespace(estimator=estimator, report=report)


@pipeline.predict
def predict(model: SimpleNamespace, feats: np.ndarray | None) -> dict | None:
    """Score the window, gate it into a key, and say which key the song wanted.

    Every number here is recorded while a take is open: ``proba`` is the scores,
    ``note`` the key the gate let through, ``cue`` the key the song asked for.
    """
    if feats is None:
        return None
    proba = model.estimator.predict_proba(feats.reshape(1, -1))[0]
    return {
        "class": int(np.argmax(proba)),
        "proba": proba,
        "note": gate.update(proba, time.monotonic() * 1000.0),
        "cue": song_cue["key"],
    }


def _save_songs(session) -> None:
    """Write the songs finished during a take into its meta.json."""
    songs = piano.songs[take["songs"] :]
    if songs:
        session.extras["piano"] = {"songs": songs}


app.finalize_hooks.append(_save_songs)

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
steps = StepBar(["Connect", "Record", "Train", "Play"], widget_id="piano_steps")
participant = ParticipantPanel()
header = AppHeader("Magic Piano", steps=steps, participant=participant)
status = StatusBar("emg", pipeline=pipeline)
device = DevicePicker("emg", devices=DEVICES, show_header=False)
viewer = SignalViewer("emg", show_connect=False, show_title=True)
log = LogPanel(title="Activity log")
sessions = SessionManager("sessions", class_names=CLASSES)
train_button = TrainButton(pipeline, size=(-1, 0))
training_log = TrainingLog(pipeline)
scores = PredictionLabel(pipeline, CLASSES, title="Class scores", font_scale=1.4)


def _connected(ctx: Context) -> bool:
    stream = ctx.streams.get("emg")
    return stream is not None and stream.status == "connected" and stream.info is not None


def _dummy(ctx: Context) -> DummyHandSource | None:
    stream = ctx.streams.get("emg")
    source = getattr(stream, "_source", None)
    return source if _connected(ctx) and isinstance(source, DummyHandSource) else None


def _record() -> None:
    """Open a take, remembering which songs came before it."""
    take["songs"] = len(piano.songs)
    app.start_recording()


def _lesson_at(elapsed: float) -> tuple[int, float] | None:
    """The lesson step at ``elapsed`` seconds and the time into it, or ``None`` after."""
    for index, (*_, seconds) in enumerate(LESSON):
        if elapsed < seconds:
            return index, elapsed
        elapsed -= seconds
    return None


def _stop_lesson(message: str) -> None:
    lesson["start"] = None
    if app.ctx.recording:
        app.stop_recording()
    app.ctx.log(message)


def _run_lesson(ctx: Context) -> tuple[int, float] | None:
    """Label the lesson take with the cue on screen. Runs every frame, on any step."""
    if lesson["start"] is None:
        return None
    if not ctx.recording or ctx.session is None:
        lesson["start"] = None  # stopped from elsewhere
        return None
    at = _lesson_at(time.monotonic() - lesson["start"])
    if at is None:
        _stop_lesson("[lesson] saved. Tick it in Sessions, then train.")
        return None
    index, into = at
    label = LESSON[index][1] if into >= REACT_S else -1
    if label != lesson["label"]:
        lesson["label"] = ctx.current_label = label
        ctx.session.add_label(label)
    return at


def _drive_dummy(ctx: Context, at: tuple[int, float] | None) -> None:
    """The synthetic hand follows the lesson cue, the song, or keys 1-5."""
    dummy = _dummy(ctx)
    if dummy is None:
        return
    if at is not None:
        dummy.gesture = max(LESSON[at[0]][1], 0)
        return
    if simulated["auto"] and ctx.state == "predicting":
        dummy.gesture = piano.expected + 1
        return
    # Any of this app's windows: this runs before the first grid cell begins.
    allowed = not imgui.get_io().want_text_input and imgui.is_window_focused(
        imgui.FocusedFlags_.any_window
    )
    keys = (imgui.Key._1, imgui.Key._2, imgui.Key._3, imgui.Key._4, imgui.Key._5)
    held = [i for i, key in enumerate(keys) if allowed and imgui.is_key_down(key)]
    dummy.gesture = held[0] + 1 if held else 0


def _reason_row(reason: str) -> None:
    if reason:
        imgui.text_wrapped(reason)


def _wide_button(label: str, *, primary: bool, active: bool = False) -> bool:
    width = (imgui.get_content_region_avail().x, 0)
    if primary:
        return primary_button(label, size=width)
    if active:
        push_selected()
    clicked = imgui.button(label, imgui.ImVec2(*width))
    if active:
        pop_selected()
    return clicked


def connect_ui(ctx: Context) -> None:
    """Pick and connect the amplifier."""
    device.ui(ctx)


def record_ui(ctx: Context, at: tuple[int, float] | None) -> None:
    """Start or stop the lesson."""
    running = lesson["start"] is not None
    left = max(0, int(LESSON_S - (time.monotonic() - lesson["start"]))) if running else 0
    with tinted_row(DANGER if running else IDLE):
        imgui.align_text_to_frame_padding()
        imgui.text("Recording the lesson" if running else "Ready to record")
        if running:
            imgui.same_line()
            mono_text(f"{left // 60}:{left % 60:02} left", muted())
    reason = (
        ""
        if running
        else "Connect a device first."
        if not _connected(ctx)
        else "Set a participant first."
        if not ctx.participant
        else "Stop playing to record a lesson."
        if ctx.state != "idle"
        else ""
    )
    imgui.begin_disabled(bool(reason))
    if running:
        if _wide_button(f"{fa.ICON_FA_STOP}  Stop lesson", primary=False, active=True):
            _stop_lesson("[lesson] stopped early; the take is kept.")
    elif _wide_button(f"{fa.ICON_FA_CIRCLE}  Start lesson", primary=True):
        _record()
        if app.ctx.recording:
            lesson.update(start=time.monotonic(), label=None)
    imgui.end_disabled()
    _reason_row(reason)
    imgui.spacing()
    imgui.text_wrapped(
        f"Bend each finger, then make a fist: {HOLD_S:.0f} s each with {REST_S:.0f} s of "
        f"rest between, {LESSON_ROUNDS} rounds. {LESSON_S / 60:.1f} minutes in one take."
    )


def model_ui() -> None:
    """Choose features, train, and read the finger check."""
    model = pipeline.model
    with tinted_row(IDLE if model is None else SUCCESS):
        imgui.align_text_to_frame_padding()
        imgui.text(
            "No model yet: tick a lesson, then train."
            if model is None
            else f"Finger check passed · accuracy {model.report['accuracy']:.0%}"
        )
    imgui.text_colored(muted(), "Features")
    features.ui()
    imgui.spacing()
    train_button.ui()
    training_log.ui()


def play_ui(ctx: Context) -> None:
    """Start the model, record what is played, and show the class scores."""
    playing = ctx.state == "predicting"
    with tinted_row(SUCCESS if playing else IDLE):
        imgui.align_text_to_frame_padding()
        imgui.text(f"Playing · {PREDICT_HZ} Hz" if playing else "Ready to play")
    reason = (
        ""
        if playing
        else "Train a model that passes the finger check first."
        if pipeline.model is None
        else "Connect a device first."
        if not _connected(ctx)
        else "Finish the current action first."
        if ctx.state != "idle"
        else ""
    )
    imgui.begin_disabled(bool(reason))
    if playing:
        if _wide_button(f"{fa.ICON_FA_STOP}  Stop playing", primary=False, active=True):
            if ctx.recording:
                app.stop_recording()
            pipeline.stop_predicting()
    elif _wide_button(f"{fa.ICON_FA_PLAY}  Play", primary=True):
        pipeline.start_predicting()
    imgui.end_disabled()
    _reason_row(reason)

    imgui.begin_disabled(not playing)
    recording = ctx.recording
    if _wide_button(
        f"{fa.ICON_FA_STOP}  Stop take" if recording else f"{fa.ICON_FA_CIRCLE}  Record take",
        primary=False,
        active=recording,
    ):
        app.stop_recording() if recording else _record()
    imgui.end_disabled()
    imgui.text_colored(muted(), "Saves the EMG, every prediction, the keys and the scores.")

    if _dummy(ctx) is not None:
        if _wide_button("Simulated hand plays the song", primary=False, active=simulated["auto"]):
            simulated["auto"] = not simulated["auto"]
        imgui.text_colored(muted(), "Or hold keys 1-5 to bend a finger yourself.")
    imgui.spacing()
    scores.ui()


def cue_ui(at: tuple[int, float] | None) -> None:
    """The lesson cue, large enough to read from the chair."""
    panel_header("Lesson", fa.ICON_FA_HAND, status=DANGER if at else IDLE)
    dl = imgui.get_window_draw_list()
    origin = imgui.get_cursor_screen_pos()
    width = imgui.get_content_region_avail().x
    height = ui_px(180)
    imgui.dummy(imgui.ImVec2(width, height))
    far = imgui.ImVec2(origin.x + width, origin.y + height)
    dl.add_rect_filled(origin, far, imgui.get_color_u32(CONSOLE_BG), ui_px(4))

    def centred(text: str, y: float, tone: imgui.ImVec4, size: float | None = None) -> None:
        if size:
            imgui.push_font(
                display_font() or imgui.get_font(), size / imgui.get_style().font_scale_main
            )
        x = origin.x + (width - imgui.calc_text_size(text).x) / 2
        dl.add_text(imgui.ImVec2(x, y), imgui.get_color_u32(tone), text)
        if size:
            imgui.pop_font()

    line = imgui.get_text_line_height()
    if at is None:
        centred(
            "Start the lesson to see the cues here.", origin.y + height / 2 - line / 2, CONSOLE_TEXT
        )
        return
    index, into = at
    name, label, seconds = LESSON[index]
    c = PALETTE[label % len(PALETTE)] if label >= 0 else None
    tone = (
        imgui.ImVec4(float(c[0]), float(c[1]), float(c[2]), 1.0) if c is not None else CONSOLE_TEXT
    )
    big = min(ui_px(72), height * 0.45)
    centred(name, origin.y + height * 0.18, tone, big)
    after = LESSON[index + 1][0] if index + 1 < len(LESSON) else "done"
    centred(
        f"{max(0.0, seconds - into):.0f} s · next: {after}",
        origin.y + height * 0.18 + big + ui_px(6),
        CONSOLE_TEXT,
    )
    bar_y = far.y - ui_px(6)
    dl.add_rect_filled(
        imgui.ImVec2(origin.x, bar_y),
        imgui.ImVec2(origin.x + width * min(into / seconds, 1.0), far.y),
        imgui.get_color_u32(tone),
    )


def _step_done(ctx: Context) -> list[bool]:
    """Connected, a lesson recorded, a model trained, playing."""
    return [
        _connected(ctx),
        bool(ctx.participant)
        and any(pathlib.Path("sessions", ctx.participant).glob(f"{ctx.participant}_*")),
        pipeline.model is not None,
        ctx.state == "predicting",
    ]


@app.ui
def piano_ui(ctx: Context) -> None:
    at = _run_lesson(ctx)
    _drive_dummy(ctx, at)
    view = layout
    with view["header"]:
        active = header.ui(ctx, _step_done(ctx))
    padding = imgui.get_style().window_padding
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding.x, ui_px(4)))
    with view["sessions"]:
        pipeline.training_data = sessions.ui(participant=ctx.participant)
    with view["step"]:
        tone = SUCCESS if _connected(ctx) else WARNING
        panel_header(steps.steps[active], status=tone if active == 0 else None)
        if active == 0:
            connect_ui(ctx)
        elif active == 1:
            record_ui(ctx, at)
        elif active == 2:
            model_ui()
        else:
            play_ui(ctx)
    with view["signal"]:
        if active == 1:
            cue_ui(at)
            viewer.ui(ctx)
        elif active == 0:
            viewer.ui(ctx)
        else:
            note = pipeline.predictions.get("note", -1) if ctx.state == "predicting" else -1
            piano.ui(note)
    song_cue["key"] = piano.expected
    with view["log"]:
        log.ui(ctx)
    imgui.pop_style_var()
    with view["status"]:
        status.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
