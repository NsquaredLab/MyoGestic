"""Myocontrol: pick a device, record labelled trials, train, drive the Virtual Hand.

Classification or regression — the switch in the Train step chooses what the *next*
Train builds, and the mode is bound into the model it returns.

Run with:
    uv run --extra examples --extra grpc python examples/start_here/myocontrol.py
"""

import math
import pathlib
import random
import threading
import time
import tomllib
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui
from mne_lsl.lsl import local_clock

from myogestic import App, Context, Fr, Grid, Layout, Px, Stream, TrainingData
from myogestic._theme import display_font, mono_font
from myogestic.controls import ControlBus, ControlLink, ControlLinkConnector, load_control_map
from myogestic.ml import Pipeline, load_pickle, save_pickle
from myogestic.recipes.estimators import catboost_classifier, catboost_regressor
from myogestic.recipes.features import mav, rms, var, wl, zc
from myogestic.remote import RemoteTarget
from myogestic.session import RecordedTime, iter_labeled_windows, open_session_store, recorded_time
from myogestic.sources import LSLSource
from myogestic.tracking import blend_pose
from myogestic.vhi import virtual_hand
from myogestic.vhi.pose import POSE_WIDTH
from myogestic.widgets import (
    DEFAULT_DEVICES,
    AppHeader,
    DevicePicker,
    FeatureSelector,
    FollowRun,
    LogPanel,
    ParticipantPanel,
    PostProcessor,
    PredictionLabel,
    ProcessLauncher,
    RecordingControls,
    SessionManager,
    SignalViewer,
    StatusBar,
    StepBar,
)
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    PALETTE,
    SUCCESS,
    WARNING,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    primary,
    primary_button,
    push_selected,
    segmented,
    tinted_row,
    ui_px,
)
from myogestic.widgets.panels.recording import TakeStatus

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

output_filter = PostProcessor(hz=PREDICT_HZ, compact=True)
vhi_control = vhi.control_client()

app = App("MyoGestic — myocontrol", require_participant=True)
app.streams(Stream("emg", source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS))
pipeline = Pipeline(app, predict_hz=PREDICT_HZ, input_streams=("emg",))
pipeline.save_model = save_pickle
pipeline.load_model = load_pickle
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
    show_header=False,
)
training_inputs: dict[str, tuple | None] = {"requested": None, "fitted": None}
# Object identity distinguishes a loaded model from the next successful fit.
saved_model: dict[str, Any] = {"model": None, "when": ""}
participant_workflow: dict[str, Any] = {"participant": None, "pending_step": None}


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

    target = follow_run.tick(app.ctx)
    control = held_control
    if target is not None:
        index, level = target
        control = float(blend_pose([POSES["Rest"]], [POSES[FOLLOW_GESTURES[index]]], level)[0])
    bus = link.bus
    if bus is not None:
        # `link.bus`, never `ensure()`: that blocks on an RPC and this is the predict
        # thread. `control` must be included or `push` completes it to rest every tick.
        out["controls"] = bus.push({"prediction": value, "control": control})
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


def _device_connected(ctx: Context) -> bool:
    """A fitted model still needs a live EMG device before prediction can start."""
    stream = ctx.streams.get("emg")
    return stream is not None and stream.status == "connected" and stream.info is not None


def _load_saved_model(pid: str, path: pathlib.Path) -> bool:
    """Use the pipeline loader and report only the pseudonym and model filename."""
    try:
        stamp = datetime.fromtimestamp(path.stat().st_mtime)
        model = pipeline.load_model(str(path))
    except Exception:
        # A loader error may contain names from the key file or arbitrary model data.
        app.ctx.status_message = f"Could not load the saved model for {pid}. Retrain on the takes."
        app.ctx.log(f"Model load failed for {pid}")
        return False
    pipeline.model = model
    pipeline.last_saved_model = str(path)
    today = datetime.now().date()
    when = (
        stamp.strftime("Today %H:%M")
        if stamp.date() == today
        else stamp.strftime("Yesterday %H:%M")
        if stamp.date() == today - timedelta(days=1)
        else stamp.strftime("%Y-%m-%d %H:%M")
    )
    saved_model.update(model=model, when=when)
    # The saved tuple owns its prediction mode; expose that same mode for retraining.
    if isinstance(model, tuple) and len(model) == 2 and model[0] in MODES:
        training_mode["index"] = MODES.index(model[0])
    training_inputs["requested"] = None
    training_inputs["fitted"] = _input_fingerprint()
    app.ctx.status_message = f"Saved model loaded for {pid}"
    app.ctx.log(f"Participant {pid} · loaded {path.name}")
    return True


def _select_participant(ctx: Context, *, navigate: bool = True, load_model: bool = True) -> None:
    """Tick this participant's takes once and discard the previous model and filters."""
    if ctx.participant == participant_workflow["participant"]:
        return
    if participant_workflow["participant"] is not None:
        pipeline.model = None
        pipeline.last_saved_model = None
        pipeline.predictions.clear()
        saved_model.update(model=None, when="")
        training_inputs.update(requested=None, fitted=None)
    participant_workflow["participant"] = ctx.participant
    if ctx.participant:
        sessions.select_all(ctx.participant)
        folder = pathlib.Path("sessions", ctx.participant)
        if load_model:
            try:
                models = [path for path in folder.glob("*_model.joblib") if path.is_file()]
                newest = max(models, key=lambda path: path.stat().st_mtime, default=None)
            except OSError:
                newest = None
            if newest is not None:
                _load_saved_model(ctx.participant, newest)
    if navigate:
        has_takes = bool(ctx.participant) and sessions.selection().n_total > 0
        step = 2 if has_takes else 1 if _device_connected(ctx) else 0
        steps.active = participant_workflow["pending_step"] = step


def _drive_participant(pid: str, path: pathlib.Path) -> None:
    """Open Drive after the panel has selected the ID and the model has loaded."""
    if app.ctx.state != "idle" or app.ctx.participant != pid:
        return
    _select_participant(app.ctx, navigate=False, load_model=False)
    if _load_saved_model(pid, path):
        steps.active = participant_workflow["pending_step"] = 3


participant = ParticipantPanel(on_drive=_drive_participant)
header = AppHeader("Myocontrol", steps=steps, participant=participant)
status = StatusBar("emg", pipeline=pipeline)
# These are view caches, not another source of recording state.
recorded: dict[str, Any] = {
    "participant": None,
    "recording": False,
    "pending": False,
    "time": RecordedTime(0, 0.0, {}),
}

# Every stream here is a device stream; the app owns its acquisition geometry.
device = DevicePicker(
    "emg",
    selectable=True,
    show_header=False,
    exclude=("vhi_control",),
    on_add=lambda name: app.add_stream(
        Stream(name, source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS)
    ),
    on_remove=app.remove_stream,
)
log = LogPanel(title="Activity log")
# The Source panel owns connecting, so the viewer offers no button of its own.
viewer = SignalViewer(
    "emg",
    show_connect=False,
    selectable=True,
    show_title=True,
    show_markers=True,
    exclude=("vhi_control",),
)
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
hand_connection: dict[str, Any] = {"announced": None, "feedback_pending": False}
drive_run: dict[str, float | None] = {"started": None}
drive_mode = {"index": 0}
guided_run: dict[str, Any] = {
    "phase": "setup",
    "reps": 5,
    "cue_s": 4.0,
    "order": [],
    "index": -1,
    "deadline": 0.0,
    "session": None,
    "score": None,
}


def score_guided_run(path: str | pathlib.Path) -> dict:
    """Score a guided run's predictions against its cues.

    Parameters
    ----------
    path
        Saved session folder or ``.session.zip`` with ``extras.guided``.

    Returns
    -------
    dict
        Row-weighted ``match`` and ``per_class`` fractions, ``median_reach_s``,
        and ``reached`` / ``cues`` counts. Windows include their onset and exclude
        their closing label. Repeated gestures count toward match but not reach;
        the first cue counts toward reach. Fractions with no rows and a median
        with no reached cues are ``None``. Only closed cue windows are scored.
    """
    with open_session_store(path) as take:
        names = take.extras["guided"]["classes"]
        if "prediction.class" in take.stores:
            predictions, timestamps = take.get_continuous("prediction.class")
            predictions = predictions.reshape(-1)
        else:
            predictions, timestamps = np.array([]), np.array([])
        counts = {name: [0, 0] for name in names}
        reach = []
        cues = 0
        previous = None
        for cue, closing in pairwise(take.label_track):
            ci = cue.class_index
            if not 0 <= ci < len(names):
                previous = None
                continue
            inside = (timestamps >= cue.timestamp) & (timestamps < closing.timestamp)
            matches = inside & (predictions == ci)
            counts[names[ci]][0] += int(np.count_nonzero(matches))
            counts[names[ci]][1] += int(np.count_nonzero(inside))
            if ci != previous:
                cues += 1
                if matches.any():
                    reach.append(float(np.min(timestamps[matches]) - cue.timestamp))
            previous = ci
        matched = sum(value[0] for value in counts.values())
        rows = sum(value[1] for value in counts.values())
        return {
            "match": matched / rows if rows else None,
            "per_class": {name: good / n if n else None for name, (good, n) in counts.items()},
            "median_reach_s": float(np.median(reach)) if reach else None,
            "reached": len(reach),
            "cues": cues,
        }


def _prediction_reason() -> str:
    """The shared gate for free prediction and a guided run."""
    if app.ctx.state != "idle":
        return "Busy — wait until the current action finishes."
    if pipeline.model is None:
        return "No model yet — train or load a model first."
    if not _device_connected(app.ctx):
        return "Connect a device in Connect before predicting."
    if pipeline.on_extract is None or pipeline.on_predict is None:
        return "Prediction needs @pipeline.extract and @pipeline.predict wired."
    return ""


def _start_guided_run() -> None:
    """Start prediction and a take, then wait three seconds before the first cue."""
    if _prediction_reason() or guided_run["phase"] in ("warmup", "cue", "saving"):
        return
    pipeline.start_predicting()
    if app.ctx.state != "predicting":
        return
    app.start_recording()
    if not app.ctx.recording:
        reason = app.ctx.status_message
        pipeline.stop_predicting()
        app.ctx.status_message = reason
        return
    seed = random.SystemRandom().randrange(2**32)
    order = list(range(len(CLASSES))) * guided_run["reps"]
    random.Random(seed).shuffle(order)
    session = app.ctx.session
    session.extras["guided"] = {
        "classes": list(CLASSES),
        "reps": guided_run["reps"],
        "cue_s": guided_run["cue_s"],
        "seed": seed,
        "order": order,
    }
    guided_run.update(
        phase="warmup",
        order=order,
        index=-1,
        deadline=local_clock() + 3.0,
        session=session,
        score=None,
    )


def _stop_guided_run() -> None:
    """Close even a partial cue, save the take and return prediction to idle."""
    if guided_run["phase"] not in ("warmup", "cue"):
        return
    guided_run["session"].add_label(-1, local_clock())
    guided_run["phase"] = "saving"
    _stop_drive()


def _sync_guided_run() -> None:
    """Advance on the data clock, even when another workflow step is visible."""
    phase = guided_run["phase"]
    if phase in ("warmup", "cue"):
        now = local_clock()
        if now >= guided_run["deadline"]:
            index = guided_run["index"] + 1
            if index == len(guided_run["order"]):
                _stop_guided_run()
            else:
                ci = guided_run["order"][index]
                guided_run["session"].add_label(ci, now)
                # A delayed UI frame must not invent unseen cues or shorten the next.
                guided_run.update(phase="cue", index=index, deadline=now + guided_run["cue_s"])
    if guided_run["phase"] == "saving" and not app.ctx.pending_saves:
        try:
            guided_run["score"] = score_guided_run(guided_run["session"].path)
            guided_run["phase"] = "results"
        except Exception:
            # A failed or incomplete save may still leave the take recoverable.
            guided_run["phase"] = "error"
            app.ctx.log("The guided run could not be scored from its saved take.")


def _cleanup_guided_run(_app: App) -> None:
    """Close the cue before the app finalises an open take at shutdown."""
    if guided_run["phase"] in ("warmup", "cue"):
        guided_run["session"].add_label(-1, local_clock())


app.cleanup_hooks.append(_cleanup_guided_run)


#: What drives each alias here. The map says where a value goes, not what sends one.
ALIAS_ROLES = {
    "prediction": "the model, every predict tick",
    "control": "the gesture buttons or Follow run",
}
#: A map that declares an alias nothing here pushes would show a control in this panel
#: that never moves, so the fallback should never be reached — it is a warning, not a row.
UNDRIVEN = "declared but never sent — wrong map?"


def _announce_binding(bus: ControlBus | None) -> None:
    """Announce each new connection once, including a background bind."""
    if bus is not None:
        hand_connection["feedback_pending"] = "vhi_control" not in app.ctx.streams
        _ensure_hand_feedback()
    if bus is not None and hand_connection["announced"] is not bus:
        app.ctx.notify("Virtual Hand connected", "Start predicting drives it.", "info")
    hand_connection["announced"] = bus


def _ensure_hand_feedback() -> None:
    """Attach the ordinary feedback stream once, after an open take has ended."""
    if not hand_connection["feedback_pending"] or app.ctx.recording:
        return
    if "vhi_control" not in app.ctx.streams:
        stream = Stream(
            "vhi_control",
            source=LSLSource(vhi.control_stream_name or "VHI_Control"),
            window_ms=1000,
            buffer_ms=60000,
        )
        if app.add_stream(stream):
            # Binding authorises this inlet; acquisition itself never auto-connects.
            threading.Thread(target=stream.reconnect, daemon=True).start()
    hand_connection["feedback_pending"] = False


def _feedback_summary() -> str | None:
    """Summarise the observed pose and its measured LSL rate when data is fresh."""
    stream = app.ctx.streams.get("vhi_control")
    if stream is None or stream.status != "connected":
        return None
    data, timestamps = stream.get_window()
    if not len(timestamps) or data.shape[0] != POSE_WIDTH:
        return None
    from mne_lsl.lsl import local_clock

    if local_clock() - timestamps[-1] > 2.0:
        return None
    pose = data[:, -1]
    flexion = float(np.mean(pose[[0, 2, 3, 4, 5]]))
    rate = (
        (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])
        if len(timestamps) > 1 and timestamps[-1] > timestamps[0]
        else 0.0
    )
    return (
        f"flex {flexion:+.2f} · wrist {pose[6]:+.2f}/{pose[7]:+.2f}/{pose[8]:+.2f} · {rate:.0f} Hz"
    )


def _toggle_drive_recording() -> None:
    """Save a free drive take without interrupting prediction or asking for a name."""
    if app.ctx.state != "predicting":
        return
    if app.ctx.recording:
        app.stop_recording()
        drive_run["started"] = None
    else:
        app.start_recording()
        if app.ctx.recording:
            drive_run["started"] = time.monotonic()


def _stop_drive() -> None:
    """Close the take before stopping prediction so the workflow finishes idle."""
    if app.ctx.recording:
        app.stop_recording()
    drive_run["started"] = None
    pipeline.stop_predicting()


FOLLOW_GESTURES = [name for name in CLASSES if name != "Rest"]


def _start_follow_recording() -> None:
    """Use Drive's prediction gate and undo a failed recording start."""
    if _prediction_reason():
        return
    pipeline.start_predicting()
    if app.ctx.state != "predicting":
        return
    app.start_recording()
    if not app.ctx.recording:
        pipeline.stop_predicting()


def _stop_follow_recording() -> None:
    """Save before stopping prediction and restore the relaxed manual target."""
    global held_control
    held_control = POSES["Rest"]
    _stop_drive()


follow_run = FollowRun(
    FOLLOW_GESTURES,
    on_record=_start_follow_recording,
    on_stop=_stop_follow_recording,
)
app.cleanup_hooks.append(lambda _app: follow_run.stop(app.ctx))


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
    take_lengths=(3.0, 5.0, 10.0),
    warmups=(0.0, 1.0, 2.0, 3.0),
    timed=True,
    take_length=5.0,
    warmup=2.0,
)


def _pushed() -> list[tuple[str, str]]:
    """The last sent frame as alias → targets and formatted value rows."""
    controls = pipeline.predictions.get("controls")
    if not controls:
        return []
    rows = []
    for name, value in controls.items():
        binding = CONTROL_MAP.bindings.get(name)
        targets = ", ".join(ref.address for ref in binding.targets) if binding else "unmapped"
        rows.append((f"{name} → {targets}", value if isinstance(value, str) else f"{value:+.2f}"))
    return rows


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
    """Read disk on participant changes, take stops, and finalization completion."""
    if (
        ctx.participant != recorded["participant"]
        or (recorded["recording"] and not ctx.recording)
        or (recorded["pending"] and not ctx.pending_saves)
    ):
        recorded["time"] = (
            recorded_time(pathlib.Path("sessions", ctx.participant))
            if ctx.participant
            else RecordedTime(0, 0.0, {})
        )
        recorded["participant"] = ctx.participant
    recorded["recording"] = ctx.recording
    recorded["pending"] = bool(ctx.pending_saves)
    return recorded["time"]


def _recorded_block(ctx: Context, totals: RecordedTime) -> None:
    """Show a participant's takes and comparable gesture durations."""
    rows = list(dict.fromkeys([*CLASSES, *totals.per_class]))
    style = imgui.get_style()
    empty = "Nothing yet. Each gesture's recorded time shows here as you go."
    wrap_width = max(ui_px(1), imgui.get_content_region_avail().x - 2 * style.window_padding.x)
    height = (
        2 * style.window_padding.y
        + imgui.get_text_line_height_with_spacing()
        + style.item_spacing.y
        + (
            len(rows) * imgui.get_frame_height_with_spacing()
            if totals.takes
            else imgui.calc_text_size(empty, wrap_width=wrap_width).y
        )
    )
    imgui.push_style_color(imgui.Col_.child_bg, style.color_(imgui.Col_.popup_bg))
    imgui.begin_child(
        "recorded-time", imgui.ImVec2(0, height), imgui.ChildFlags_.always_use_window_padding
    )
    summary = f"{totals.takes} takes · {_duration(totals.total_s)}"
    summary_w = imgui.calc_text_size(summary).x
    panel_header(f"Recorded for {ctx.participant}", reserve=summary_w + style.item_spacing.x)
    imgui.same_line()
    imgui.set_cursor_pos_x(
        imgui.get_cursor_pos_x() + max(0.0, imgui.get_content_region_avail().x - summary_w)
    )
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
            width = max(
                ui_px(1), imgui.get_content_region_avail().x - value_w - style.item_spacing.x
            )
            color = PALETTE[index % len(PALETTE)]
            imgui.push_style_color(imgui.Col_.plot_histogram, imgui.ImVec4(*color, 1.0))
            imgui.progress_bar(
                seconds / maximum if maximum else 0.0,
                imgui.ImVec2(width, imgui.get_frame_height()),
                "",
            )
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
    _muted_line("Timed captures one gesture. Start / stop lets you switch gestures.")


def _take_overlay(take: TakeStatus) -> None:
    """Draw the take's live countdown or recording chip over the signal cell."""
    if take.phase not in ("warmup", "recording"):
        return
    origin, size = imgui.get_window_pos(), imgui.get_window_size()
    pad = ui_px(12)
    left, right = origin.x + pad, origin.x + size.x - pad
    # The viewer's title row stays visible above the plot veil and REC chip.
    top = origin.y + pad + imgui.get_frame_height_with_spacing()
    bottom = origin.y + size.y - pad
    draw = imgui.get_window_draw_list()
    style = imgui.get_style()
    draw.push_clip_rect(imgui.ImVec2(left, top), imgui.ImVec2(right, bottom), True)
    try:
        if take.phase == "warmup":
            surface = style.color_(imgui.Col_.child_bg)
            veil = imgui.ImVec4(surface.x, surface.y, surface.z, 0.90)
            draw.add_rect_filled(
                imgui.ImVec2(left, top),
                imgui.ImVec2(right, bottom),
                imgui.get_color_u32(veil),
                style.child_rounding,
            )
            center_x, center_y = (left + right) / 2, (top + bottom) / 2
            title = "Get ready" + (f" · {take.gesture}" if take.gesture else "")
            for text, font, font_size, y, tone in (
                (title, None, ui_px(20), center_y - ui_px(72), WARNING),
                (
                    str(math.ceil(take.warmup_left_s)),
                    display_font(),
                    ui_px(64),
                    center_y - ui_px(40),
                    WARNING,
                ),
                (
                    f"recording starts in {take.warmup_left_s:.1f} s",
                    mono_font(),
                    ui_px(14),
                    center_y + ui_px(38),
                    muted(),
                ),
            ):
                imgui.push_font(font, font_size)
                try:
                    text = _ellipsize(text, right - left)
                    draw.add_text(
                        imgui.ImVec2(center_x - imgui.calc_text_size(text).x / 2, y),
                        imgui.get_color_u32(tone),
                        text,
                    )
                finally:
                    imgui.pop_font()
        else:
            tenths = round(max(0, take.elapsed_s) * 10)
            minutes, tenths = divmod(tenths, 600)
            clock = f"{minutes}:{tenths // 10:02d}.{tenths % 10}"
            gesture = take.gesture or ""
            if app.ctx.state == "predicting":
                gesture = (
                    CLASSES[guided_run["order"][guided_run["index"]]]
                    if guided_run["phase"] == "cue"
                    else "run"
                )
            text = f"REC {gesture} · {clock}"
            imgui.push_font(mono_font(), style.font_size_base)
            try:
                text = _ellipsize(text, right - left - 3 * pad)
                width = imgui.calc_text_size(text).x + 3 * pad
                height = imgui.get_text_line_height() + pad
                x, y = right - width, top + ui_px(6)
                draw.add_rect_filled(
                    imgui.ImVec2(x, y),
                    imgui.ImVec2(right, y + height),
                    imgui.get_color_u32(style.color_(imgui.Col_.popup_bg)),
                    style.frame_rounding,
                )
                draw.add_circle_filled(
                    imgui.ImVec2(x + pad, y + height / 2), ui_px(3), imgui.get_color_u32(DANGER)
                )
                draw.add_text(
                    imgui.ImVec2(x + 2 * pad, y + pad / 2),
                    imgui.get_color_u32(style.color_(imgui.Col_.text)),
                    text,
                )
            finally:
                imgui.pop_font()
    finally:
        draw.pop_clip_rect()
    if take.phase == "recording" and take.timed:
        fraction = min(1.0, take.elapsed_s / take.length_s)
        draw.add_rect_filled(
            origin,
            imgui.ImVec2(origin.x + size.x * fraction, origin.y + ui_px(3)),
            imgui.get_color_u32(DANGER),
        )


def model_ui() -> None:
    """Choose model inputs and review the selected training takes."""
    if pipeline.model is not None and pipeline.model is saved_model["model"]:
        _saved_model_ui()
        return
    busy = app.ctx.state != "idle"
    style = imgui.get_style()
    imgui.begin_disabled(busy)
    room = imgui.get_content_region_avail().x
    labels_width = sum(imgui.calc_text_size(label).x for label in MODES)
    padding = max(0.0, (room - labels_width - 2 * (len(MODES) - 1)) / (2 * len(MODES)))
    imgui.push_style_var(
        imgui.StyleVar_.frame_padding, imgui.ImVec2(padding, style.frame_padding.y)
    )
    training_mode["index"] = segmented("mode", MODES, training_mode["index"])
    imgui.pop_style_var()
    imgui.text_colored(muted(), "Features")
    features.ui()
    imgui.end_disabled()

    summary = sessions.selection()
    seconds = summary.class_seconds
    total = _duration(sum(seconds.values()))
    # One shared range keeps gesture durations comparable inside this card.
    maximum = max(seconds.values(), default=0.0)
    height = (
        2 * style.window_padding.y
        + imgui.get_text_line_height_with_spacing()
        + len(seconds) * imgui.get_frame_height_with_spacing()
    )
    imgui.push_style_color(imgui.Col_.child_bg, style.color_(imgui.Col_.frame_bg))
    imgui.begin_child(
        "training-selection", imgui.ImVec2(0, height), imgui.ChildFlags_.always_use_window_padding
    )
    total_width = imgui.calc_text_size(total).x
    panel_header(
        f"Training on {summary.n_selected} takes", reserve=total_width + style.item_spacing.x
    )
    imgui.same_line()
    imgui.set_cursor_pos_x(
        imgui.get_cursor_pos_x()
        + max(
            0.0,
            imgui.get_content_region_avail().x - total_width,
        )
    )
    mono_text(total, muted())
    name_width = max((imgui.calc_text_size(name).x for name in seconds), default=0.0)
    value_width = imgui.calc_text_size(_duration(maximum)).x
    for index, (name, elapsed) in enumerate(seconds.items()):
        left = imgui.get_cursor_pos_x()
        imgui.align_text_to_frame_padding()
        imgui.text_unformatted(name)
        imgui.same_line()
        imgui.set_cursor_pos_x(left + name_width + style.item_spacing.x)
        width = max(
            ui_px(1), imgui.get_content_region_avail().x - value_width - style.item_spacing.x
        )
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
    reason = _training_reason()
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


def _training_reason() -> str:
    """Apply the same training requirements to a fresh fit and a saved-model retrain."""
    summary = sessions.selection()
    data = pipeline.training_data
    missing = [name for name in CLASSES if name not in summary.class_seconds]
    if app.ctx.state != "idle":
        return "Busy — wait until the current action finishes."
    if app.ctx.pending_saves:
        return "Saving the last take…"
    if features.n_active == 0:
        return "Select at least one feature."
    if data is None or data.is_empty or summary.n_selected == 0:
        return "Record a take or select takes below first."
    if missing:
        return f"No selected takes for {', '.join(missing)} — include those gestures below."
    return ""


def _saved_model_ui() -> None:
    """Offer Drive and retraining for the loaded model."""
    # Two text lines keep both state and timestamp readable in a 320 px cell.
    height = 2 * imgui.get_text_line_height_with_spacing() + ui_px(8)
    with tinted_row(SUCCESS, height=height) as width:
        imgui.text_unformatted("Saved model loaded")
        mono_text(_ellipsize(saved_model["when"], width), muted())
    imgui.text_wrapped("Drive with it now, or retrain on the ticked takes below.")
    busy = app.ctx.state != "idle"
    imgui.begin_disabled(busy)
    go = primary_button("Go to Drive", size=(imgui.get_content_region_avail().x, 0))
    imgui.end_disabled()
    if go and not busy:
        steps.active = 3
    reason = _training_reason()
    count = sessions.selection().n_selected
    imgui.begin_disabled(bool(reason))
    retrain = imgui.button(f"Retrain on {count} takes", imgui.ImVec2(-1, 0))
    imgui.end_disabled()
    if retrain and not reason:
        training_inputs["requested"] = _input_fingerprint()
        pipeline.start_training()
    if reason:
        _disabled_reason(reason)


def connect_ui(ctx: Context) -> None:
    """Connect step: choose acquisition and launch or bind the Virtual Hand."""
    device.ui(ctx)
    imgui.spacing()
    imgui.align_text_to_frame_padding()
    imgui.text_colored(muted(), "Mains notch")
    imgui.set_item_tooltip("Filters the recording and the model input.")
    imgui.same_line()
    imgui.begin_disabled(ctx.state != "idle")
    # Segments size to their labels; equal padding gives them the rest of the row.
    style = imgui.get_style()
    room = imgui.get_content_region_avail().x
    labels_width = sum(imgui.calc_text_size(label).x for label in NOTCH_CHOICES)
    padding = max(
        0.0, (room - labels_width - 2 * (len(NOTCH_CHOICES) - 1)) / (2 * len(NOTCH_CHOICES))
    )
    imgui.push_style_var(
        imgui.StyleVar_.frame_padding, imgui.ImVec2(padding, style.frame_padding.y)
    )
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


def _guided_hero(text: str, ci: int | None = None) -> None:
    """Give the participant a display-sized cue with its gesture identity dot."""
    if ci is not None:
        size = ui_px(48)
        imgui.dummy(imgui.ImVec2(ui_px(12), size))
        lo = imgui.get_item_rect_min()
        color = imgui.ImVec4(*PALETTE[ci % len(PALETTE)], 1.0)
        imgui.get_window_draw_list().add_circle_filled(
            imgui.ImVec2(lo.x + ui_px(4), lo.y + size / 2),
            ui_px(4),
            imgui.get_color_u32(color),
        )
        imgui.same_line()
    imgui.push_font(display_font(), ui_px(48))
    imgui.text_unformatted(_ellipsize(text, imgui.get_content_region_avail().x))
    imgui.pop_font()


def _guided_start_ui(label: str) -> None:
    """Use the free-prediction gate and its visible explanation for guided starts."""
    reason = _prediction_reason()
    imgui.begin_disabled(bool(reason))
    clicked = primary_button(label, size=(-1, 0))
    imgui.end_disabled()
    if clicked and not reason:
        _start_guided_run()
    if reason:
        _disabled_reason(reason)
        if (
            app.ctx.state == "idle"
            and pipeline.model is not None
            and not _device_connected(app.ctx)
            and imgui.button("Go to Connect", imgui.ImVec2(-1, 0))
        ):
            steps.active = 0


def _guided_results_ui() -> None:
    """Show saved-take match and reach without exposing participant names."""
    score = guided_run["score"]
    match = score["match"]
    _guided_hero(f"{match:.0%}" if match is not None else "—")
    imgui.push_style_color(imgui.Col_.text, muted())
    imgui.text_wrapped("of the time the prediction matched the cue")
    imgui.pop_style_color()
    imgui.spacing()
    style = imgui.get_style()
    gap = style.item_spacing.x
    name_width = max((imgui.calc_text_size(name).x for name in score["per_class"]), default=0.0)
    imgui.push_font(mono_font(), style.font_size_base)
    value_width = imgui.calc_text_size("100%").x
    imgui.pop_font()
    for ci, (name, value) in enumerate(score["per_class"].items()):
        left, top = imgui.get_cursor_pos()
        imgui.text_unformatted(name)
        imgui.same_line()
        imgui.set_cursor_pos_x(left + name_width + gap)
        width = max(ui_px(1), imgui.get_content_region_avail().x - value_width - gap)
        imgui.set_cursor_pos_y(top + (imgui.get_text_line_height() - ui_px(4)) / 2)
        imgui.push_style_color(
            imgui.Col_.plot_histogram, imgui.ImVec4(*PALETTE[ci % len(PALETTE)], 1.0)
        )
        # Match PredictionLabel: a thin bar must not charge frame padding to the row.
        imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(style.frame_padding.x, 0))
        imgui.progress_bar(value or 0.0, imgui.ImVec2(width, ui_px(4)), "")
        imgui.pop_style_var()
        imgui.pop_style_color()
        imgui.same_line()
        imgui.set_cursor_pos_y(top)
        mono_text(f"{value:.0%}" if value is not None else "—", muted())
    imgui.spacing()
    reach = score["median_reach_s"]
    mono_text(f"{reach:.2f} s" if reach is not None else "—")
    _muted_line("Median time to reach a cue")
    _muted_line(f"{score['reached']} of {score['cues']} cues reached")
    if match is None:
        _muted_line("No predictions were recorded inside the cues.")
    imgui.spacing()
    filename = guided_run["session"].path.name
    mono_text(_ellipsize(filename, imgui.get_content_region_avail().x), muted())
    imgui.set_item_tooltip(filename)
    _guided_start_ui("Run again")
    if imgui.button("Done", imgui.ImVec2(-1, 0)):
        guided_run.update(phase="setup", session=None, score=None)


def _guided_ui() -> None:
    """Draw the setup, participant cue, save status or saved-run result."""
    phase = guided_run["phase"]
    if phase == "setup":
        columns = 2 if imgui.get_content_region_avail().x >= ui_px(360) else 1
        if imgui.begin_table("guided-settings", columns):
            imgui.table_next_column()
            imgui.text_colored(muted(), "Repetitions per gesture")
            imgui.set_next_item_width(-1)
            changed, reps = imgui.input_int("##guided-reps", guided_run["reps"])
            if changed:
                guided_run["reps"] = max(1, reps)
            imgui.table_next_column()
            imgui.text_colored(muted(), "Cue length (s)")
            imgui.set_next_item_width(-1)
            changed, seconds = imgui.input_float("##guided-cue", guided_run["cue_s"], format="%.1f")
            if changed and math.isfinite(seconds):
                guided_run["cue_s"] = max(0.1, seconds)
            imgui.end_table()
        imgui.spacing()
        _guided_start_ui("Start guided run")
    elif phase in ("warmup", "cue"):
        left = max(0.0, guided_run["deadline"] - local_clock())
        if phase == "warmup":
            _muted_line("Get ready")
            _guided_hero(str(math.ceil(left)))
            _muted_line("Follow each gesture when it appears.")
        else:
            ci = guided_run["order"][guided_run["index"]]
            _guided_hero(CLASSES[ci], ci)
            mono_text(
                f"{guided_run['index'] + 1} of {len(guided_run['order'])} · {left:.1f} s left",
                muted(),
            )
            predicted = pipeline.predictions.get("class")
            name = (
                CLASSES[predicted]
                if isinstance(predicted, int) and 0 <= predicted < len(CLASSES)
                else "Waiting for prediction"
            )
            matches = predicted == ci
            imgui.push_style_color(imgui.Col_.text, SUCCESS if matches else muted())
            imgui.text_wrapped(f"{name} · {'matches cue' if matches else 'not matching yet'}")
            imgui.pop_style_color()
        imgui.spacing()
        if imgui.button("Stop run", imgui.ImVec2(-1, 0)):
            _stop_guided_run()
    elif phase == "saving":
        _muted_line("Saving the run…")
    elif phase == "results":
        _guided_results_ui()
    else:
        imgui.text_wrapped("The saved run could not be scored. Check the take in Takes.")
        if imgui.button("Done", imgui.ImVec2(-1, 0)):
            guided_run.update(phase="setup", session=None, score=None)


def drive_ui() -> None:
    """Drive freely, or follow a recorded sequence of gesture cues."""
    _sync_guided_run()
    locked = app.ctx.state != "idle" or app.ctx.recording or guided_run["phase"] == "saving"
    imgui.begin_disabled(locked)
    width = (imgui.get_content_region_avail().x - 2 * imgui.get_style().item_spacing.x) / 3
    for index, label in enumerate(("Free", "Guided", "Follow")):
        if index:
            imgui.same_line()
        selected = drive_mode["index"] == index
        if selected:
            push_selected()
        clicked = imgui.button(label + "##drive-mode", imgui.ImVec2(width, 0))
        if selected:
            pop_selected()
        if clicked and not locked:
            drive_mode["index"] = index
    imgui.end_disabled()
    imgui.spacing()
    if drive_mode["index"] == 1:
        _guided_ui()
        return
    if drive_mode["index"] == 2:
        follow_run.ui(app.ctx, disabled_reason=_prediction_reason())
        return
    _free_drive_ui()


def _free_drive_ui() -> None:
    """Keep free prediction, smoothing and control inspection together."""
    prediction.ui()
    state = app.ctx.state
    predicting = state == "predicting"
    reason = _prediction_reason()
    can_start = not reason
    enabled = can_start or predicting
    imgui.begin_disabled(not enabled)
    # The pre-click value guards both sides, including the frame Stop is clicked.
    if predicting:
        push_selected()
    clicked = primary_button("Stop predicting" if predicting else "Start predicting", size=(-1, 0))
    if predicting:
        pop_selected()
    imgui.end_disabled()
    if clicked and enabled:
        if predicting:
            _stop_drive()
        else:
            pipeline.start_predicting()
    if not enabled:
        _disabled_reason(reason)
        if (
            state == "idle"
            and pipeline.model is not None
            and not _device_connected(app.ctx)
            and imgui.button("Go to Connect", imgui.ImVec2(-1, 0))
        ):
            steps.active = 0
    imgui.spacing()
    predicting = app.ctx.state == "predicting"
    selected = app.ctx.recording
    imgui.begin_disabled(not predicting)
    if selected:
        push_selected()
    label = "Record this run"
    if selected:
        elapsed = max(0.0, time.monotonic() - (drive_run["started"] or time.monotonic()))
        label = f"Recording this run · {int(elapsed) // 60}:{int(elapsed) % 60:02d}"
    clicked = imgui.button(label + "##drive_record", imgui.ImVec2(-1, 0))
    if selected:
        pop_selected()
    imgui.end_disabled()
    if clicked and predicting:
        _toggle_drive_recording()
    if app.ctx.recording:
        _muted_line("Press again to stop and save. Predicting keeps running.")
    output_filter.ui()
    imgui.spacing()
    rows = _pushed()
    style = imgui.get_style()
    imgui.push_style_color(imgui.Col_.child_bg, style.color_(imgui.Col_.frame_bg))
    imgui.begin_child(
        "sent-controls",
        imgui.ImVec2(0, 0),
        imgui.ChildFlags_.auto_resize_y | imgui.ChildFlags_.always_use_window_padding,
    )
    panel_header("Sent to the hand")
    if not rows:
        mono_text("nothing sent yet", muted())
    for label, value in rows:
        imgui.push_font(mono_font(), style.font_size_base)
        value_w = imgui.calc_text_size(value).x
        imgui.pop_font()
        room = imgui.get_content_region_avail().x
        # Fan-out targets stay on one row; hovering exposes the complete route.
        imgui.text_unformatted(_ellipsize(label, max(0.0, room - value_w - style.item_spacing.x)))
        imgui.set_item_tooltip(label)
        imgui.same_line()
        imgui.set_cursor_pos_x(
            imgui.get_cursor_pos_x() + max(0.0, imgui.get_content_region_avail().x - value_w)
        )
        mono_text(value)
    feedback = _feedback_summary()
    _muted_line(f"Hand feedback · {feedback or 'not connected'}")
    imgui.end_child()
    imgui.pop_style_color()


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
        # The connection may have completed since this frame began.
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
        tone, detail = SUCCESS, "Connected · prediction and control → hand"
    elif phase == "stopping":
        tone, detail = WARNING, "Stopping…"
    elif phase in ("checking", "launched"):
        tone, detail = WARNING, binder.status or "Launched · waiting for the hand…"
    elif phase == "failed":
        tone = DANGER
        detail = binder.status if binder.last_error is not None else "no Virtual Hand answered"
        if not hand_processes and binder.last_error is None:
            detail += " · not installed here"
    else:
        tone, detail = IDLE, "Not running" if hand_processes else "not installed here"
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
        imgui.text_colored(primary(), "Virtual Hand")
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
            if imgui.small_button(action) and phase != "stopping":
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
                    "Wait for the connection attempt to stop."
                    if phase == "stopping"
                    else "Stop connecting and close the hand launched here."
                    if action == "Stop"
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


@app.ui
def myocontrol_ui(ctx: Context) -> None:
    _sync_guided_run()
    follow_run.sync(ctx)
    _ensure_hand_feedback()
    # External context changes refresh data without overriding a manually chosen step.
    _select_participant(ctx, navigate=False)
    previous_participant = ctx.participant
    with layout["header"]:
        active = header.ui(ctx, _step_done(ctx))
    _select_participant(ctx, navigate=ctx.participant != previous_participant)
    if participant_workflow["pending_step"] is not None:
        active = participant_workflow["pending_step"]
        participant_workflow["pending_step"] = None
    padding = imgui.get_style().window_padding
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding.x, ui_px(4)))
    if active != 1 or not ctx.participant:
        recording.ui(ctx, visible=False)
    # Observe recording transitions even while a different workflow step is open.
    _refresh_recorded(ctx)
    # Refresh the participant's selection before Train can read it this frame.
    with layout["sessions"]:
        pipeline.training_data = sessions.ui(participant=ctx.participant)
    with layout["step"]:
        stream = ctx.streams.get("emg")
        tone = (
            SUCCESS
            if stream is not None and stream.status == "connected" and stream.info is not None
            else DANGER
            if stream is not None and stream.last_error
            else IDLE
        )
        if active != 3 or drive_mode["index"] != 2:
            panel_header(steps.steps[active], status=tone if active == 0 else None)
        if active == 0:
            connect_ui(ctx)
        elif active == 1:
            record_ui(ctx)
        elif active == 2:
            model_ui()
        else:
            drive_ui()
    with layout["signal"]:
        viewer.ui(ctx)
        _take_overlay(recording.take)
    with layout["log"]:
        log.ui(ctx)
    imgui.pop_style_var()
    with layout["status"]:
        status.ui(ctx)

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
