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
from imgui_bundle import imgui

from myogestic import App, Context, Fr, Grid, Layout, Px, Stream, TrainingData
from myogestic._theme import display_font
from myogestic.controls import ControlBus, ControlLink, ControlLinkConnector, load_control_map
from myogestic.ml import Pipeline, save_pickle
from myogestic.recipes.estimators import catboost_classifier, catboost_regressor
from myogestic.recipes.features import mav, rms, var, wl, zc
from myogestic.remote import RemoteTarget
from myogestic.session import iter_labeled_windows, open_session_store
from myogestic.vhi import virtual_hand
from myogestic.widgets import (
    DEFAULT_DEVICES,
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
)
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    INFO,
    SUCCESS,
    WARNING,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    primary_button,
    push_selected,
    segmented,
    ui_px,
)
from myogestic.widgets.panels.recording import _status_pill
from myogestic.widgets.training._session_state import get_state as session_state

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
        title    steps    participant state
        signal   signal   step        step
        signal   signal   sessions    sessions
        log      log      sessions    sessions
        status   status   status      status
        """,
        row_height=[Px(88), Fr(3), Fr(1), Fr(1), Px(56)],
        col_width=[Px(180), Fr(1), Px(240), Px(160)],
    ),
    narrow=Grid.areas(
        """
        title    participant state
        steps    steps       steps
        signal   signal      signal
        step     step        step
        sessions sessions    sessions
        log      log         log
        status   status      status
        """,
        row_height=[Px(88), Px(64), Fr(2), Fr(3), Fr(1.5), Fr(1), Px(76)],
        col_width=[Fr(1), Fr(1), Px(160)],
    ),
    breakpoint=Px(1100),
)
steps = StepBar(["Connect", "Record", "Train", "Drive"], widget_id="myocontrol_steps")
participant = ParticipantPanel()

# No `exclude`: every stream here is a device stream.
device = DevicePicker("emg", selectable=True)
log = LogPanel(title="Activity log")
# The Source panel owns connecting, so the viewer offers no button of its own.
viewer = SignalViewer("emg", show_connect=False, selectable=True, show_title=True)
# `launchable`, never `launcher`: a VHI that cannot be launched must not stop this app
# from opening, and one already running needs no button.
processes = ProcessLauncher(vhi.launchable())
# VHI takes seconds to boot and `ensure()` blocks, so this retries in the background —
# rate-limited and single-flight, safe to poll every frame.
binder = ControlLinkConnector(link)
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


def model_ui() -> None:
    """Train step: choose the model inputs and fit the selected takes."""
    busy = app.ctx.state != "idle"
    imgui.begin_disabled(busy)
    panel_header("MODE")
    training_mode["index"] = segmented("mode", MODES, training_mode["index"])
    imgui.spacing()
    features.ui()
    imgui.end_disabled()

    imgui.spacing()
    panel_header("INPUT")
    stream = app.ctx.streams.get("emg")
    channels = str(stream.info.n_channels) if stream is not None and stream.info else "—"
    mode = MODES[training_mode["index"]]
    estimator = "classifier" if mode == "Classification" else "regressor"
    imgui.text_wrapped(
        f"Window {WINDOW_MS} ms · Notch {NOTCH_CHOICES[notch['index']]} · "
        f"Channels {channels} · CatBoost {estimator}"
    )
    if pipeline.model is not None and training_inputs["fitted"] != _input_fingerprint():
        imgui.push_style_color(imgui.Col_.text, WARNING)
        imgui.text_wrapped("Features changed — retrain to apply them.")
        imgui.pop_style_color()
    imgui.spacing()
    data = pipeline.training_data
    can_train = not busy and data is not None and not data.is_empty and features.n_active > 0
    imgui.begin_disabled(not can_train)
    clicked = primary_button(f"Train {estimator}")
    imgui.end_disabled()
    if clicked and can_train:
        training_inputs["requested"] = _input_fingerprint()
        pipeline.start_training()
    if not can_train and imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
        if busy:
            reason = "Busy — wait until the current action finishes."
        elif features.n_active == 0:
            reason = "Select at least one feature."
        else:
            reason = "Record a take or select session files below first."
        imgui.set_tooltip(reason)


def connect_ui(ctx: Context) -> None:
    """Connect step: choose acquisition and launch or bind the Virtual Hand."""
    device.ui(ctx)
    imgui.spacing()
    panel_header("MAINS NOTCH")
    imgui.begin_disabled(ctx.state != "idle")
    notch["index"] = segmented("notch", NOTCH_CHOICES, notch["index"])
    imgui.end_disabled()
    stream = ctx.streams.get("emg")
    if stream is not None:
        stream.notch_hz = NOTCH_HZ[notch["index"]]
    imgui.text_wrapped("Conditions both recordings and the model input.")
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
    if not enabled and imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
        if state != "idle":
            reason = "Busy — wait until the current action finishes."
        elif pipeline.model is None:
            reason = "No model yet — train or load a model first."
        else:
            reason = "Prediction needs @pipeline.extract and @pipeline.predict wired."
        imgui.set_tooltip(reason)
    imgui.spacing()
    output_filter.ui()
    imgui.spacing()
    # A read-out, not a progress bar: `fist` resolves to [-1, 1] and a bar would clamp
    # the negative half away without saying so.
    panel_header("PUSHED")
    mono_text(_pushed())


def hand_ui() -> None:
    """Launch VHI in Connect, and bind to it once it answers.

    Launching is the only press. This still keeps "nothing attaches on its own" — the
    binding follows an act the operator performed, it just does not make them perform a
    second one to confirm the first. A VHI already running when the app opened was
    started outside this panel, so `ProcessLauncher.running` cannot see it; **Bind now**
    is there for that case.
    """
    processes.ui()
    imgui.spacing()
    bound = link.bus is not None
    panel_header("CONTROL MAP", status=SUCCESS if bound else None)
    for alias, binding in CONTROL_MAP.bindings.items():
        mono_text(alias)
        imgui.indent(ui_px(14))
        targets = binding.targets
        where = (
            f"{len(targets)} controls"
            if len(targets) > 1
            # The leading `vhi.` is the same on every row; the tail is what differs.
            else targets[0].address.split(".", 1)[-1]
        )
        imgui.text_colored(muted(), f"{where} · {ALIAS_ROLES.get(alias, UNDRIVEN)}")
        imgui.unindent(ui_px(14))
    imgui.spacing()
    if bound:
        _announce_binding(link.bus)
        imgui.text_disabled("Bound — Predict drives the hand.")
        return
    if processes.running(vhi.name):
        # Launched from this panel: retry until its manifest answers. `poll` never blocks
        # and never raises, so a VHI that never comes up costs one attempt every 2 s.
        binder.poll()
        imgui.text_disabled(binder.status or "Launched — binding as soon as VHI answers…")
        return
    if imgui.button("Bind now") and _bind() is None:
        app.ctx.log("VHI did not answer. Launch it above, or start it before the app.")
    imgui.text_wrapped("Launch VHI above, or bind to one already running.")


def _step_done(ctx: Context) -> list[bool]:
    """Completion reflects the participant's takes, even when none are selected."""
    stream = ctx.streams.get("emg")
    return [
        stream is not None and stream._connected,
        bool(session_state(sessions._widget_id).sessions),
        pipeline.model is not None,
        ctx.state == "predicting",
    ]


def status_ui(ctx: Context) -> None:
    """Show acquisition, participant storage and the most recent saved model."""
    stream = ctx.streams.get("emg")
    if stream is not None and stream._connected and stream.info is not None:
        info = stream.info
        device_name = type(stream._source).__name__.removesuffix("Source")
        source = f"{device_name} · {info.n_channels} ch / {info.fs:g} Hz"
    else:
        source = "Device: disconnected"
    folder = pathlib.Path("sessions") / ctx.participant
    if pipeline.model is None:
        model = "Model: none"
    elif pipeline.last_saved_model:
        model = f"Model: {pathlib.Path(pipeline.last_saved_model).name}"
    else:
        model = "Model: fitted (not saved)"
    imgui.push_style_color(imgui.Col_.text, muted())
    imgui.text_wrapped(f"{source}  ·  {ctx.participant or 'No participant'}  ·  {folder}  ·  {model}")
    imgui.pop_style_color()


@app.ui
def myocontrol_ui(ctx: Context) -> None:
    """A visible workflow with persistent signal, activity and session files."""
    with layout["title"]:
        imgui.push_font(display_font(), ui_px(28))
        imgui.text_unformatted("MyoGestic")
        imgui.pop_font()
        imgui.text_colored(muted(), "Myocontrol")
    with layout["participant"]:
        participant.ui(ctx)
    with layout["state"]:
        tone = {"recording": DANGER, "training": WARNING, "predicting": INFO}.get(ctx.state, IDLE)
        _status_pill(ctx.state.upper(), tone)
    # Refresh the participant's selection before Train can read it this frame.
    with layout["sessions"]:
        pipeline.training_data = sessions.ui(participant=ctx.participant)
    with layout["steps"]:
        active = steps.ui(done=_step_done(ctx))
    with layout["signal"]:
        viewer.ui(ctx)
    with layout["log"]:
        log.ui(ctx)
    with layout["step"]:
        panel_header(steps.steps[active])
        if active == 0:
            connect_ui(ctx)
        elif active == 1:
            recording.ui(ctx)
        elif active == 2:
            model_ui()
        else:
            drive_ui()
    with layout["status"]:
        status_ui(ctx)

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
