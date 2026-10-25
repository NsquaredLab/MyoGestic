"""Myocontrol: pick a device, record labelled trials, train, drive the Virtual Hand.

Classification or regression — the switch in the Train step chooses what the *next*
Train builds, and the mode is bound into the model it returns.

Run with:
    uv run --extra examples --extra grpc python examples/start_here/myocontrol.py
"""

import pathlib
import tomllib
from typing import Any

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic import App, Context, Fr, Grid, Layout, Px, Stream, TrainingData
from myogestic._theme import mono_font
from myogestic.controls import ControlBus, ControlLink, ControlLinkConnector, load_control_map
from myogestic.ml import Pipeline, save_pickle
from myogestic.recipes.estimators import catboost_classifier, catboost_regressor
from myogestic.recipes.features import mav, rms, var, wl, zc
from myogestic.remote import RemoteTarget
from myogestic.session import RecordedTime, iter_labeled_windows, open_session_store, recorded_time
from myogestic.vhi import virtual_hand
from myogestic.widgets import (
    DEFAULT_DEVICES,
    AppLogo,
    DevicePicker,
    FeatureSelector,
    LogPanel,
    ParticipantPanel,
    PostProcessor,
    PredictionLabel,
    ProcessLauncher,
    RecordingControls,
    SessionManager,
    SignalViewer,
    StepBar,
    status_pill,
)
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    INFO,
    PALETTE,
    SUCCESS,
    WARNING,
    hairline,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    primary_button,
    push_selected,
    segmented,
    tinted_row,
    ui_px,
)

# The live Stream window is also the training window — a model fitted on 200 ms of
# signal is fed 200 ms at predict time or it sees a distribution it never met.
WINDOW_MS = 200
HOP_MS = 100
# One rate for the predict loop, the smoother and the control bus. Let them drift and
# the post-processor's time constants are tuned for a timebase nothing runs on.
PREDICT_HZ = 32
# The names are yours: nothing downstream matches them against VHI's vocabulary. They
# have to agree with `POSES` and nothing else.
CLASSES = ["Rest", "Fist"]
MODES = ["Classification", "Regression"]

#: What each class *is*, as a control value. Add a class by adding a row; `predict`
#: does not change.
POSES: dict[str, float] = {"Rest": 0.0, "Fist": 1.0}
# A class with no pose would push all-rest and look like a model that never fires.
assert set(POSES) == set(CLASSES), f"POSES and CLASSES disagree: {set(POSES) ^ set(CLASSES)}"

#: Notch on *acquisition* — reaches the model and the recording, unlike the viewer's
#: Notch, which only changes what is drawn.
NOTCH_CHOICES = ["Off", "50 Hz", "60 Hz"]
NOTCH_HZ = [0, 50, 60]
#: A dict so the UI callback writes it without `global`.
notch = {"index": 0}

vhi = virtual_hand()

# Where the prediction goes. The left side is ours, the right side is VHI's; nothing is
# resolved until VHI answers, which is why binding is a button and not an import.
CONTROL_FILE = pathlib.Path(__file__).resolve().parent.parent / "controls" / "myocontrol.toml"
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

output_filter = PostProcessor(hz=PREDICT_HZ)
vhi_control = vhi.control_client()

app = App("MyoGestic — myocontrol", require_participant=True)
app.streams(Stream("emg", source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS))
pipeline = Pipeline(app, predict_hz=PREDICT_HZ)
pipeline.save_model = save_pickle
pipeline.autosave_dir = "sessions"
link = ControlLink(
    CONTROL_MAP,
    [RemoteTarget(client=vhi_control, interface=vhi)],
    ctx=app.ctx,
    smoothing=output_filter,
    hz=PREDICT_HZ,
)
# A dict, so the UI callback writes it without `global`. Read only by `train`.
training_mode = {"index": 0}
#: What the control hand is showing. Set by the class buttons and re-sent every frame,
#: because VHI drops a control pose whose streams go quiet for 5 s.
held_control = 0.0
features = FeatureSelector(
    {"RMS": rms, "MAV": mav, "WL": wl, "VAR": var, "ZC": zc},
    default=["RMS", "MAV"],
)
training_inputs: dict[str, tuple | None] = {"requested": None, "fitted": None}


def _input_fingerprint() -> tuple[str, tuple[str, ...], int]:
    """The mode and signal inputs chosen for the next fit."""
    return MODES[training_mode["index"]], tuple(features.active_names), NOTCH_HZ[notch["index"]]


@pipeline.extract
def extract(windows: dict[str, np.ndarray]) -> np.ndarray | None:
    """Active features of the EMG window, stacked along axis 0."""
    # `.get`, not `[...]`: a stream added at runtime has no data on its first ticks and
    # the predict loop only passes the ones that do, so a subscript raises 32×/second.
    window = windows.get("emg")
    return None if window is None else features(window)


@pipeline.train
def train(data: TrainingData) -> tuple[str, Any]:
    """Fit the mode the switch currently shows, and return it with the estimator."""
    fingerprint = training_inputs["requested"] or _input_fingerprint()
    training_inputs["requested"] = None
    if data.is_empty:
        raise ValueError("No sessions selected. Scan folder, then tick some.")
    if features.n_active == 0:
        raise ValueError("No features ticked in the FEATURES panel (RMS+MAV is the default).")

    # Filtered samples are indistinguishable from raw in the arrays, so a take recorded
    # under a different notch than the switch now shows is refused by name.
    want = NOTCH_HZ[notch["index"]]
    for path in data.paths:
        with open_session_store(path) as sess:
            was = int((sess.extras.get("conditioning", {}).get("emg") or {}).get("notch_hz", 0))
        if was != want:
            raise ValueError(
                f"{pathlib.Path(path).name} was recorded with notch={was or 'off'} but "
                f"Connect is set to {want or 'off'}. Match the setting to the take, or "
                f"untick it — the model cannot be fitted on one and run on the other."
            )

    all_x: list[np.ndarray] = []
    all_y: list[int] = []
    for window, _ts, class_idx in iter_labeled_windows(
        # `or None` because an empty set filters every window out, and that is what
        # `SessionManager` returns when the selection has no class pool yet.
        data.paths,
        "emg",
        WINDOW_MS,
        HOP_MS,
        classes=data.classes or None,
    ):
        # Through `extract`, not `features`, so training and prediction cannot diverge.
        all_x.append(extract({"emg": window}))
        all_y.append(class_idx)

    if len(all_x) < 2:
        raise ValueError(f"Need at least 2 windows, got {len(all_x)}. Record longer trials.")
    x = np.stack(all_x)
    y = np.array(all_y)
    if len(np.unique(y)) < 2:
        raise ValueError(f"Need trials from ≥2 classes, got {len(np.unique(y))}.")

    mode = MODES[training_mode["index"]]
    if mode == "Classification":
        est = catboost_classifier(iterations=100)
        est.fit(x, y)
    else:
        # One column: how closed the hand is. The map fans that scalar out to the
        # five digits, so a regressor emitting 0..1 drives the same aliases a classifier
        # drives with a hard 0/1 — no per-mode control map.
        est = catboost_regressor(iterations=200)
        # The target is the pose table read as numbers: what `fist` would be commanded
        # for that class. One definition of what a class means, not two.
        closed = np.array([POSES[CLASSES[i]] for i in y], dtype=np.float32)
        est.fit(x, closed)
    print(f"[train] {mode.lower()} on {len(all_x)} windows from {len(data.paths)} sessions")
    training_inputs["fitted"] = fingerprint
    return mode, est


@pipeline.predict
def predict(model: tuple[str, Any], feats: np.ndarray | None) -> dict | None:
    """Run the model in the mode it was trained in and drive the prediction hand.

    The mode comes out of ``model``, never off the live switch: flipping the switch
    with a classifier loaded would send a class *index* down the regression branch and
    snap the hand to full flexion with nothing raising.
    """
    if feats is None:
        return None
    mode, est = model
    if mode == "Classification":
        proba = est.predict_proba(feats.reshape(1, -1))[0]
        class_idx = int(np.argmax(proba))
        # The class names a posture; the posture is what gets sent. Same wire, same
        # aliases, same units as the regressor below — a constant instead of a curve.
        value = POSES[CLASSES[class_idx]]
        out: dict[str, Any] = {"class": class_idx, "proba": proba}
    else:
        # Clamped because the alias is signed [-1, 1]: an extrapolated -0.35 would
        # extend the fingers while the read-out said "Rest, 100 %".
        value = min(max(float(est.predict(feats.reshape(1, -1))[0]), 0.0), 1.0)
        out = {"class": int(value >= 0.5), "proba": [1.0 - value, value]}

    bus = link.bus
    if bus is not None:
        # `link.bus`, never `ensure()`: that blocks on an RPC and this is the predict
        # thread. `control` must be included or `push` completes it to rest every tick.
        out["controls"] = bus.push({"prediction": value, "control": held_control})
    return out


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
steps = StepBar(["Connect", "Record", "Train", "Drive"], widget_id="myocontrol_steps")
participant = ParticipantPanel()
# These are view caches, not another source of recording state.
recorded: dict[str, Any] = {"participant": None, "state": "idle", "time": RecordedTime(0, 0.0, {})}
header_widths: dict[str, float] = {}

# Every stream here is a device stream; the app owns its acquisition geometry.
device = DevicePicker(
    "emg", selectable=True, show_header=False,
    on_add=lambda name: app.add_stream(
        Stream(name, source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS)
    ),
    on_remove=app.remove_stream,
)
log = LogPanel(title="Activity log")
# The Source panel owns connecting, so the viewer offers no button of its own.
viewer = SignalViewer("emg", show_connect=False, selectable=True, show_title=True)
# `launchable`, never `launcher`: a VHI that cannot be launched must not stop this app
# from opening, and one already running needs no button.
hand_processes = vhi.launchable()
processes = ProcessLauncher(hand_processes)
# VHI takes seconds to boot and `ensure()` blocks, so this retries in the background —
# rate-limited and single-flight, safe to poll every frame.
binder = ControlLinkConnector(link)
hand_attempt = {"phase": "idle"}
sessions = SessionManager("sessions", class_names=CLASSES)
prediction = PredictionLabel(pipeline, CLASSES, show_probability=True)
hand_connection: dict[str, ControlBus | None] = {"announced": None}


#: What drives each alias here. The map says where a value goes, not what sends one.
ALIAS_ROLES = {
    "prediction": "the model, every predict tick",
    "control": "the Rest / Fist buttons",
}
#: A map that declares an alias nothing here pushes would show a control in this panel
#: that never moves, so the fallback should never be reached — it is a warning, not a row.
UNDRIVEN = "declared but never sent — wrong map?"


def _announce_binding(bus: ControlBus | None) -> None:
    """Announce each new connection once, including a background bind."""
    if bus is not None and hand_connection["announced"] is not bus:
        app.ctx.notify("Virtual Hand connected", "Start predicting drives it.", "info")
    hand_connection["announced"] = bus


def _bind() -> ControlBus | None:
    """Bind the control map to VHI, saying so when it does not work.

    Both failures are silent by default and they look identical from the outside — a
    button that does nothing. `ControlLink.ensure` returns ``None`` when VHI is simply
    unreachable, and raises when it answered but the map does not fit its manifest.
    """
    try:
        bus = link.ensure()
    except ValueError as exc:
        app.ctx.log(f"Control map does not fit this VHI: {exc}")
        return None
    if bus is None:
        app.ctx.log("VHI is not answering — launch it in Connect, or press Bind now.")
    _announce_binding(bus)
    return bus


def _on_control(index: int) -> None:
    """Put the selected class on the control hand.

    Remembering is the whole job: the frame that carries it is sent by `myocontrol_ui`
    while recording, and by the predict loop while predicting. Pushing here too would
    only add a frame in which `prediction` is completed to rest, twitching the other hand
    on every class press.

    It does bind, though. A UI handler is where that is affordable — `predict` must never
    call it — and binding on first press is what lets the buttons work without visiting
    the Connect step.
    """
    global held_control
    held_control = POSES[CLASSES[index]]
    # `_bind` logs why when it cannot, so a press that moves nothing always says so.
    _bind()


recording = RecordingControls(
    CLASSES,
    on_record=app.start_recording,
    on_stop=app.stop_recording,
    on_gesture=_on_control,
    show_header=False,
)


def _pushed() -> str:
    """The last frame delivered to VHI, one control per line."""
    controls = pipeline.predictions.get("controls")
    if not controls:
        return "nothing pushed yet"
    return "\n".join(
        f"{name:<13}{value}" if isinstance(value, str) else f"{name:<13}{value:+.2f}"
        for name, value in controls.items()
    )


def _ellipsize(text: str, width: float) -> str:
    """Fit one line to its available space with an ellipsis when needed."""
    if imgui.calc_text_size(text).x <= width:
        return text
    while text and imgui.calc_text_size(text + "…").x > width:
        text = text[:-1]
    return text + "…" if width >= imgui.calc_text_size("…").x else ""


def _muted_line(text: str) -> None:
    """Keep supporting copy on one line without losing the full explanation."""
    imgui.text_colored(muted(), _ellipsize(text, imgui.get_content_region_avail().x))
    if imgui.is_item_hovered():
        imgui.set_tooltip(text)


def _disabled_reason(reason: str) -> None:
    """Explain a disabled action both on hover and in the panel itself."""
    if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
        imgui.set_tooltip(reason)
    imgui.text_colored(WARNING, fa.ICON_FA_CIRCLE_INFO)
    imgui.same_line()
    _muted_line(reason)


def _duration(seconds: float) -> str:
    """Format the recorded sample-clock duration in minutes and seconds."""
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def _refresh_recorded(ctx: Context) -> RecordedTime:
    """Read disk on participant changes and when a recording returns to idle."""
    if ctx.participant != recorded["participant"] or (
        recorded["state"] == "recording" and ctx.state == "idle"
    ):
        recorded["time"] = (
            recorded_time(pathlib.Path("sessions", ctx.participant))
            if ctx.participant else RecordedTime(0, 0.0, {})
        )
        recorded["participant"] = ctx.participant
    recorded["state"] = ctx.state
    return recorded["time"]


def _recorded_block(ctx: Context, totals: RecordedTime) -> None:
    """Show a participant's takes and comparable gesture durations."""
    rows = list(dict.fromkeys([*CLASSES, *totals.per_class]))
    style = imgui.get_style()
    empty = "Nothing yet. Each gesture's recorded time shows here as you go."
    wrap_width = max(ui_px(1), imgui.get_content_region_avail().x - 2 * style.window_padding.x)
    height = (
        2 * style.window_padding.y + imgui.get_text_line_height_with_spacing()
        + style.item_spacing.y
        + (len(rows) * imgui.get_frame_height_with_spacing() if totals.takes else
           imgui.calc_text_size(empty, wrap_width=wrap_width).y)
    )
    imgui.push_style_color(imgui.Col_.child_bg, style.color_(imgui.Col_.popup_bg))
    imgui.begin_child("recorded-time", imgui.ImVec2(0, height),
                      imgui.ChildFlags_.always_use_window_padding)
    summary = f"{totals.takes} takes · {_duration(totals.total_s)}"
    summary_w = imgui.calc_text_size(summary).x
    panel_header(f"Recorded for {ctx.participant}", reserve=summary_w + style.item_spacing.x)
    imgui.same_line()
    imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(
        0.0, imgui.get_content_region_avail().x - summary_w
    ))
    imgui.text_colored(muted(), summary)
    if not totals.takes:
        imgui.push_text_wrap_pos(0.0)
        imgui.text_colored(muted(), empty)
        imgui.pop_text_wrap_pos()
    else:
        name_w = max(imgui.calc_text_size(name).x for name in rows)
        value_w = imgui.calc_text_size(_duration(max(totals.per_class.values(), default=0))).x
        maximum = max(totals.per_class.values(), default=0.0)
        for index, name in enumerate(rows):
            seconds = totals.per_class.get(name, 0.0)
            left = imgui.get_cursor_pos_x()
            imgui.align_text_to_frame_padding()
            imgui.text_unformatted(name)
            imgui.same_line()
            imgui.set_cursor_pos_x(left + name_w + style.item_spacing.x)
            width = max(ui_px(1), imgui.get_content_region_avail().x - value_w - style.item_spacing.x)
            color = PALETTE[index % len(PALETTE)]
            imgui.push_style_color(imgui.Col_.plot_histogram, imgui.ImVec4(*color, 1.0))
            imgui.progress_bar(seconds / maximum if maximum else 0.0,
                               imgui.ImVec2(width, imgui.get_frame_height()), "")
            imgui.pop_style_color()
            imgui.same_line()
            imgui.text_colored(muted(), _duration(seconds))
    imgui.end_child()
    imgui.pop_style_color()


def record_ui(ctx: Context) -> None:
    """Record labelled gestures, or open participant setup before recording."""
    _refresh_recorded(ctx)
    if not ctx.participant:
        left, top = imgui.get_cursor_pos()
        width, height = imgui.get_content_region_avail()
        line = imgui.get_text_line_height_with_spacing()
        imgui.set_cursor_pos_y(top + max(0.0, (height - 3 * line - imgui.get_frame_height()) / 2))
        for text, color in (
            (fa.ICON_FA_LOCK, WARNING),
            ("Set a participant to record", None),
            ("Recordings are saved under the participant ID.", muted()),
        ):
            text = _ellipsize(text, width)
            imgui.set_cursor_pos_x(left + max(0.0, (width - imgui.calc_text_size(text).x) / 2))
            if color is None:
                imgui.text_unformatted(text)
            else:
                imgui.text_colored(color, text)
        button_w = imgui.calc_text_size("Set participant").x + 2 * imgui.get_style().frame_padding.x
        imgui.set_cursor_pos_x(left + max(0.0, (width - button_w) / 2))
        if primary_button("Set participant"):
            participant.open()
        return
    recording.ui(ctx)
    # Stop can change the state during this very frame.
    _recorded_block(ctx, _refresh_recorded(ctx))
    _muted_line(
        "Pick the gesture the hand shows, press Record, switch gestures as the participant moves, then Stop."
    )


def model_ui() -> None:
    """Train step: choose inputs and see exactly which takes and gestures will fit."""
    busy = app.ctx.state != "idle"
    style = imgui.get_style()
    imgui.begin_disabled(busy)
    room = imgui.get_content_region_avail().x
    labels_width = sum(imgui.calc_text_size(label).x for label in MODES)
    padding = max(0.0, (room - labels_width - 2 * (len(MODES) - 1)) / (2 * len(MODES)))
    imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(padding, style.frame_padding.y))
    training_mode["index"] = segmented("mode", MODES, training_mode["index"])
    imgui.pop_style_var()
    features.ui()
    imgui.end_disabled()

    summary = sessions.selection()
    seconds = summary.class_seconds
    total = _duration(sum(seconds.values()))
    # One shared range keeps gesture durations comparable inside this card.
    maximum = max(seconds.values(), default=0.0)
    height = (2 * style.window_padding.y + imgui.get_text_line_height_with_spacing()
              + len(seconds) * imgui.get_frame_height_with_spacing())
    imgui.push_style_color(imgui.Col_.child_bg, style.color_(imgui.Col_.frame_bg))
    imgui.begin_child("training-selection", imgui.ImVec2(0, height),
                      imgui.ChildFlags_.always_use_window_padding)
    total_width = imgui.calc_text_size(total).x
    panel_header(f"Training on {summary.n_selected} takes", reserve=total_width + style.item_spacing.x)
    imgui.same_line()
    imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(
        0.0, imgui.get_content_region_avail().x - total_width,
    ))
    mono_text(total, muted())
    name_width = max((imgui.calc_text_size(name).x for name in seconds), default=0.0)
    value_width = imgui.calc_text_size(_duration(maximum)).x
    for index, (name, elapsed) in enumerate(seconds.items()):
        left = imgui.get_cursor_pos_x()
        imgui.align_text_to_frame_padding()
        imgui.text_unformatted(name)
        imgui.same_line()
        imgui.set_cursor_pos_x(left + name_width + style.item_spacing.x)
        width = max(ui_px(1), imgui.get_content_region_avail().x - value_width - style.item_spacing.x)
        ci = CLASSES.index(name) if name in CLASSES else index
        color = PALETTE[ci % len(PALETTE)]
        # Reserve a full line but draw only a thin bar, centred on its text.
        top = imgui.get_cursor_pos_y()
        imgui.set_cursor_pos_y(top + (imgui.get_frame_height() - ui_px(4)) / 2)
        imgui.push_style_color(imgui.Col_.plot_histogram, imgui.ImVec4(*color, 1.0))
        imgui.progress_bar(elapsed / maximum if maximum else 0.0, imgui.ImVec2(width, ui_px(4)), "")
        imgui.pop_style_color()
        imgui.same_line()
        imgui.set_cursor_pos_y(top)
        imgui.align_text_to_frame_padding()
        mono_text(_duration(elapsed), muted())
    imgui.end_child()
    imgui.pop_style_color()

    stream = app.ctx.streams.get("emg")
    channels = str(stream.info.n_channels) if stream is not None and stream.info else "—"
    mode = MODES[training_mode["index"]]
    estimator = "classifier" if mode == "Classification" else "regressor"
    detail = f"{WINDOW_MS} ms windows · notch {NOTCH_CHOICES[notch['index']].lower()} · {channels} ch · CatBoost"
    font = mono_font()
    if font is not None:
        imgui.push_font(font, style.font_size_base)
    mono_text(_ellipsize(detail, imgui.get_content_region_avail().x), muted())
    if font is not None:
        imgui.pop_font()
    imgui.set_item_tooltip(detail)
    if pipeline.model is not None and training_inputs["fitted"] != _input_fingerprint():
        imgui.push_style_color(imgui.Col_.text, WARNING)
        imgui.text_wrapped("Features changed — retrain to apply them.")
        imgui.pop_style_color()
    data = pipeline.training_data
    missing = [name for name in CLASSES if name not in seconds]
    if busy:
        reason = "Busy — wait until the current action finishes."
    elif features.n_active == 0:
        reason = "Select at least one feature."
    elif data is None or data.is_empty or summary.n_selected == 0:
        reason = "Record a take or select takes below first."
    elif missing:
        reason = f"No selected takes for {', '.join(missing)} — include those gestures below."
    else:
        reason = ""
    can_train = not reason
    imgui.begin_disabled(not can_train)
    clicked = primary_button(f"Train {estimator}", size=(-1, 0))
    imgui.end_disabled()
    if clicked and can_train:
        training_inputs["requested"] = _input_fingerprint()
        pipeline.start_training()
    if not can_train:
        _disabled_reason(reason)
    if pipeline.model is not None and pipeline.last_saved_model:
        with tinted_row(SUCCESS) as width:
            saved = f"{fa.ICON_FA_CHECK}  {pathlib.Path(pipeline.last_saved_model).name}"
            imgui.align_text_to_frame_padding()
            imgui.text_unformatted(_ellipsize(saved, width))
            imgui.set_item_tooltip(pipeline.last_saved_model)


def connect_ui(ctx: Context) -> None:
    """Connect step: choose acquisition and launch or bind the Virtual Hand."""
    device.ui(ctx)
    imgui.spacing()
    imgui.align_text_to_frame_padding()
    imgui.text("Mains notch")
    imgui.set_item_tooltip("Filters the recording and the model input.")
    imgui.same_line()
    imgui.begin_disabled(ctx.state != "idle")
    # Segments size to their labels; equal padding gives them the rest of the row.
    style = imgui.get_style()
    room = imgui.get_content_region_avail().x
    labels_width = sum(imgui.calc_text_size(label).x for label in NOTCH_CHOICES)
    padding = max(0.0, (room - labels_width - 2 * (len(NOTCH_CHOICES) - 1)) / (2 * len(NOTCH_CHOICES)))
    imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(padding, style.frame_padding.y))
    notch["index"] = segmented("notch", NOTCH_CHOICES, notch["index"])
    imgui.pop_style_var()
    imgui.end_disabled()
    if ctx.state != "idle" and imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
        imgui.set_tooltip("Return to idle before changing the mains notch.")
    stream = ctx.streams.get("emg")
    if stream is not None:
        stream.notch_hz = NOTCH_HZ[notch["index"]]
    imgui.spacing()
    hand_ui()


def drive_ui() -> None:
    """Drive step: start prediction, tune smoothing and inspect sent controls."""
    prediction.ui()
    state = app.ctx.state
    predicting = state == "predicting"
    can_start = (
        state == "idle"
        and pipeline.model is not None
        and pipeline.on_extract is not None
        and pipeline.on_predict is not None
    )
    enabled = can_start or predicting
    imgui.begin_disabled(not enabled)
    # The pre-click value guards both sides, including the frame Stop is clicked.
    if predicting:
        push_selected()
    clicked = primary_button("Stop predicting" if predicting else "Start predicting")
    if predicting:
        pop_selected()
    imgui.end_disabled()
    if clicked and enabled:
        if predicting:
            pipeline.stop_predicting()
        else:
            pipeline.start_predicting()
    if not enabled:
        if state != "idle":
            reason = "Busy — wait until the current action finishes."
        elif pipeline.model is None:
            reason = "No model yet — train or load a model first."
        else:
            reason = "Prediction needs @pipeline.extract and @pipeline.predict wired."
        _disabled_reason(reason)
    imgui.spacing()
    output_filter.ui()
    imgui.spacing()
    # A read-out, not a progress bar: `fist` resolves to [-1, 1] and a bar would clamp
    # the negative half away without saying so.
    panel_header("PUSHED")
    mono_text(_pushed())


def hand_ui() -> None:
    """Connect to an existing hand first, then launch one only if none answered.

    The operator's Connect arms the background binder. Stop cancels the attempt;
    a replacement connector waits for late cleanup before it can bind again.
    """
    global binder
    bound = link.bus is not None
    running = processes.running(vhi.name)
    phase = hand_attempt["phase"]
    if phase == "stopping" and binder.finished:
        binder = ControlLinkConnector(link)
        phase = "stopped" if running else "idle"
        bound = link.bus is not None
    if phase == "idle" and running and not bound:
        phase = "launched"
    if phase == "checking" and binder.finished:
        # Re-read after completion: the worker may have bound since this frame began.
        bound = link.bus is not None
        if not bound:
            if binder.last_error is not None:
                # A responding but incompatible target must not spawn another.
                phase = "failed"
            elif running:
                phase = "launched"
            elif hand_processes:
                processes.launch(vhi.name)
                running = True
                phase = "launched"
            else:
                phase = "failed"
    if phase == "launched" and not bound and not binder.busy:
        binder.poll()
    if bound and phase != "stopping":
        phase = "bound"
    hand_attempt["phase"] = phase
    if bound and phase != "stopping":
        _announce_binding(link.bus)
        tone, detail = SUCCESS, "bound · prediction and control → hand"
    elif phase == "stopping":
        tone, detail = WARNING, "stopping…"
    elif phase in ("checking", "launched"):
        tone, detail = WARNING, binder.status or "launched · binding as soon as it answers…"
    elif phase == "failed":
        tone = DANGER
        detail = binder.status if binder.last_error is not None else "no Virtual Hand answered"
        if not hand_processes and binder.last_error is None:
            detail += " · not installed here"
    else:
        tone, detail = IDLE, "not running" if hand_processes else "not installed here"
    if running or phase in ("checking", "launched", "stopping"):
        action = "Stop"
    elif bound:
        action = ""
    else:
        action = "Retry" if phase == "failed" else "Connect"
    mapping = "\n".join(
        f"{alias} → {', '.join(target.address for target in binding.targets)} · {ALIAS_ROLES.get(alias, UNDRIVEN)}"
        for alias, binding in CONTROL_MAP.bindings.items()
    )
    hint = f"{vhi.install_hint.strip()}\n\n" if not hand_processes else ""
    style = imgui.get_style()
    with tinted_row() as width:
        right = imgui.get_cursor_pos_x() + width
        action_w = imgui.calc_text_size(action).x + 2 * style.frame_padding.x if action else 0.0
        imgui.align_text_to_frame_padding()
        imgui.text_colored(tone, fa.ICON_FA_CIRCLE)
        imgui.same_line()
        imgui.text("Virtual Hand")
        imgui.same_line()
        font = mono_font()
        if font is not None:
            imgui.push_font(font, style.font_size_base)
        available = max(0.0, right - action_w - style.item_spacing.x - imgui.get_cursor_pos_x())
        mono_text(_ellipsize(detail, available), muted())
        if font is not None:
            imgui.pop_font()
        imgui.set_item_tooltip(f"{detail}\n\n{hint}{mapping}")
        if action:
            imgui.same_line()
            imgui.set_cursor_pos_x(right - action_w)
            imgui.begin_disabled(phase == "stopping")
            if imgui.button(action) and phase != "stopping":
                if action == "Stop":
                    binder.stop(timeout_s=0.0)
                    if running:
                        processes.stop(vhi.name)
                    hand_attempt["phase"] = "stopping"
                else:
                    binder.poll(force=True)
                    hand_attempt["phase"] = "checking"
            imgui.end_disabled()
            if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
                imgui.set_tooltip(
                    "Wait for the connection attempt to stop." if phase == "stopping"
                    else "Stop connecting and close the hand launched here." if action == "Stop"
                    else "Bind to a running Virtual Hand, or launch one if none answers."
                )


def _step_done(ctx: Context) -> list[bool]:
    """Completion reflects the participant's files, even when none are selected."""
    stream = ctx.streams.get("emg")
    return [
        stream is not None and stream.status == "connected" and stream.info is not None,
        bool(ctx.participant)
        and any(pathlib.Path("sessions", ctx.participant).glob(f"{ctx.participant}_*")),
        pipeline.model is not None,
        ctx.state == "predicting",
    ]


def _edge_rule(*, bottom: bool) -> None:
    """Separate the bare header and footer from the body with a theme hairline."""
    origin, size = imgui.get_window_pos(), imgui.get_window_size()
    y = origin.y + size.y - ui_px(1) if bottom else origin.y
    imgui.get_window_draw_list().add_line(
        imgui.ImVec2(origin.x, y), imgui.ImVec2(origin.x + size.x, y),
        imgui.get_color_u32(hairline()), thickness=ui_px(1),
    )


def header_ui(ctx: Context) -> int:
    """Lead with the brand and steps; keep the participant and state at the right."""
    _edge_rule(bottom=True)
    style = imgui.get_style()
    top = imgui.get_cursor_pos_y()
    height = imgui.get_content_region_avail().y
    center = top + height / 2
    imgui.set_cursor_pos_y(center - ui_px(26) / 2)
    AppLogo(variant="line", height=ui_px(26)).ui()
    imgui.same_line(0.0, ui_px(14))
    left = imgui.get_cursor_pos_x()
    available = imgui.get_content_region_avail().x
    right = left + available
    done = _step_done(ctx)

    # The pill owns its padding; retain its measured width instead of copying it.
    # A live scale change invalidates measurements from the preceding frame.
    if header_widths.get("font_size") != imgui.get_font_size():
        header_widths.clear()
        header_widths["font_size"] = imgui.get_font_size()
    state = ctx.state.upper()
    pill_w = header_widths.get(state, imgui.calc_text_size(state).x + ui_px(40))
    font = mono_font() if ctx.participant else None
    if font is not None:
        imgui.push_font(font, style.font_size_base)
    chip_w = imgui.calc_text_size(ctx.participant or "Set participant").x + 2 * style.frame_padding.x
    if font is not None:
        imgui.pop_font()
    padding = imgui.ImVec2(style.frame_padding.x, style.frame_padding.y)
    labels_w = sum(
        imgui.calc_text_size(f"{fa.ICON_FA_CHECK if complete else i + 1}  {label}").x
        for i, (label, complete) in enumerate(zip(steps.steps, done, strict=True))
    ) + (len(steps.steps) - 1) * ui_px(32)
    nav_w = labels_w + len(steps.steps) * 2 * padding.x
    gap = style.item_spacing.x
    title_w = 2 * gap + ui_px(1) + imgui.calc_text_size("Myocontrol").x
    # Drop the secondary title before compressing the navigation buttons.
    show_title = (
        imgui.get_window_size().x >= ui_px(1100)
        and available >= title_w + nav_w + chip_w + pill_w + 2 * gap
    )
    if show_title:
        imgui.set_cursor_pos_x(left - ui_px(14) + gap)
        imgui.set_cursor_pos_y(center - ui_px(20) / 2)
        imgui.dummy(imgui.ImVec2(ui_px(1), ui_px(20)))
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        imgui.get_window_draw_list().add_line(
            lo, imgui.ImVec2(lo.x, hi.y), imgui.get_color_u32(hairline()), thickness=ui_px(1),
        )
        imgui.same_line(0.0, gap)
        imgui.set_cursor_pos_y(center - imgui.get_text_line_height() / 2)
        imgui.text_colored(muted(), "Myocontrol")
        imgui.same_line(0.0, ui_px(14))
        left = imgui.get_cursor_pos_x()
        available = imgui.get_content_region_avail().x
    if available < nav_w + chip_w + pill_w + 2 * gap:
        padding.x = ui_px(4)
        nav_w = labels_w + len(steps.steps) * 2 * padding.x
    participant_w = max(chip_w, min(
        header_widths.get("participant", chip_w), available - nav_w - pill_w - 2 * gap
    ))
    right_w = participant_w + gap + pill_w
    imgui.set_cursor_pos(imgui.ImVec2(
        left, center - imgui.get_frame_height() / 2,
    ))
    imgui.push_style_var(imgui.StyleVar_.frame_padding, padding)
    active = steps.ui(done)
    imgui.pop_style_var()
    imgui.same_line()
    available = imgui.get_content_region_avail().x
    imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(0.0, available - right_w))
    imgui.set_cursor_pos_y(center - imgui.get_frame_height() / 2)
    # Long local names yield to the state badge, while the chip stays clickable.
    clip = imgui.get_cursor_screen_pos()
    imgui.push_clip_rect(clip, imgui.ImVec2(clip.x + participant_w, clip.y + height), True)
    imgui.begin_group()
    participant.ui(ctx)
    imgui.end_group()
    header_widths["participant"] = imgui.get_item_rect_size().x
    imgui.pop_clip_rect()
    imgui.same_line()
    pill_h = imgui.get_text_line_height() + ui_px(8)
    imgui.set_cursor_pos(imgui.ImVec2(right - pill_w, center - pill_h / 2))
    tone = {"recording": DANGER, "training": WARNING, "predicting": INFO}.get(ctx.state, IDLE)
    status_pill(state, tone)
    header_widths[state] = imgui.get_item_rect_size().x
    return active


def status_ui(ctx: Context) -> None:
    """Show acquisition, participant storage and the most recent saved model."""
    stream = ctx.streams.get("emg")
    connected = stream is not None and stream.status == "connected" and stream.info is not None
    if connected:
        info = stream.info
        source = f"{stream.name} · {info.n_channels} ch / {info.fs:g} Hz"
    else:
        source = "emg · disconnected"
    folder = pathlib.Path("sessions") / ctx.participant
    if pipeline.model is None:
        model = "Model: none"
    elif pipeline.last_saved_model:
        model = f"Model: {pathlib.Path(pipeline.last_saved_model).name}"
    else:
        model = "Model: fitted (not saved)"
    _edge_rule(bottom=False)
    imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + max(
        0.0, (imgui.get_content_region_avail().y - imgui.get_text_line_height()) / 2
    ))
    imgui.text_colored(SUCCESS if connected else IDLE, fa.ICON_FA_CIRCLE)
    imgui.same_line()
    available = imgui.get_content_region_avail().x
    right = imgui.get_cursor_pos_x() + available
    model_w = min(imgui.calc_text_size(model).x, available * 0.4)
    text = f"{source} · {ctx.participant or 'No participant'} · {folder}"
    imgui.text_colored(muted(), _ellipsize(text, available - model_w - imgui.get_style().item_spacing.x))
    if imgui.is_item_hovered():
        imgui.set_tooltip(text)
    imgui.same_line()
    imgui.set_cursor_pos_x(right - model_w)
    _muted_line(model)


@app.ui
def myocontrol_ui(ctx: Context) -> None:
    """A visible workflow with persistent signal, activity and session files."""
    # Compact child padding leaves a full button-height line inside the 52 px
    # header; Grid keeps the parent's content bounds captured by Begin.
    padding = imgui.get_style().window_padding
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding.x, ui_px(4)))
    with layout["header"]:
        active = header_ui(ctx)
    # Observe recording transitions even while a different workflow step is open.
    _refresh_recorded(ctx)
    # Refresh the participant's selection before Train can read it this frame.
    with layout["sessions"]:
        pipeline.training_data = sessions.ui(participant=ctx.participant)
    with layout["signal"]:
        viewer.ui(ctx)
    with layout["log"]:
        log.ui(ctx)
    with layout["step"]:
        stream = ctx.streams.get("emg")
        tone = (SUCCESS if stream is not None and stream.status == "connected" and stream.info is not None
                else DANGER if stream is not None and stream.last_error else IDLE)
        panel_header(steps.steps[active], status=tone if active == 0 else None)
        if active == 0:
            connect_ui(ctx)
        elif active == 1:
            record_ui(ctx)
        elif active == 2:
            model_ui()
        else:
            drive_ui()
    with layout["status"]:
        status_ui(ctx)
    imgui.pop_style_var()

    # Stream it, do not fire it once: VHI holds a pose only while samples keep arriving
    # (5 s, then `StopToRest()`). While predicting the predict loop is already doing that.
    bus = link.bus
    _announce_binding(bus)
    if bus is not None and ctx.state != "predicting":
        bus.push({"control": held_control, "prediction": 0.0})


def main() -> None:
    try:
        app.run()
    finally:
        link.stop()
        vhi_control.stop()


if __name__ == "__main__":
    main()
