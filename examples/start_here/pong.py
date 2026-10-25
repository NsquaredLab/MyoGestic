"""Pong: pick a device, follow the cursor, train, then play with your wrist.

One signed number in ``[-1, +1]`` moves the paddle: a rally rewards *graded* contraction
where a trapezoid only rewards tracking.

Two ways to record the training set, both started from the Record step. **Follow the
cursor** runs a `Pursuit` block — a ghost paddle wanders the court, the subject chases it,
and the cursor is recorded beside the EMG on the `target` stream. The Down / Rest / Up
buttons cue the older three-class protocol.

Prefer the cursor. Three cued classes are three distinct target values, so a tree ensemble
fitted on them is a three-class model whatever it is called; dense levels cut CatBoost's
error at intermediate efforts 14x. The measured active ingredient is the *number of
distinct levels*, not pursuit — a cued staircase of eleven holds does as well, and a
linear model gains nothing either way. What the cursor buys is human: told "go to 0.6" a
subject has no idea what 0.6 feels like.

The Virtual Hand is a **mirror**, not a target: the paddle follows a float that reaches it
whether or not VHI answers. The far paddle is played by the app, at a speed the Play step
sets; a wall would return everything, so a rally against one only ends in the subject's
own miss.

Run with:
    uv run --extra examples --extra grpc python examples/start_here/pong.py
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
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PredictButton, TrainButton, TrainingLog
from myogestic.recipes.estimators import (
    catboost_classifier,
    catboost_regressor,
    directional_decoder,
)
from myogestic.recipes.features import mav, rms, var, wl, zc
from myogestic.remote import RemoteTarget
from myogestic.session import iter_labeled_windows, iter_target_windows, split_sessions_by_stream
from myogestic.sources import TargetSource
from myogestic.tracking import Pursuit
from myogestic.vhi import virtual_hand
from myogestic.widgets import (
    DEFAULT_DEVICES,
    AppHeader,
    DevicePicker,
    FeatureSelector,
    LogPanel,
    ParticipantPanel,
    PongTask,
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
    SUCCESS,
    WARNING,
    fit_text,
    mono_text,
    muted,
    panel_header,
    primary,
    primary_button,
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
#: Three cued classes on one signed axis. Down is a real ``-1``, not a second one-way
#: channel: a wrist is the canonical bidirectional DOF and the paddle needs both halves.
CLASSES = ["Down", "Rest", "Up"]
# Proportional is the default because on real data the CatBoost regressor is
# non-monotonic in effort: scaling every channel 1.0 -> 1.6 moved its Up prediction
# 1.000 -> 0.723. The other two stay as baselines worth feeling.
MODES = ["Proportional", "Regression", "Classification"]

#: How the command reaches the paddle. Velocity first: integrating even a coarse output
#: reaches every height, where position gives as many places as the model has outputs.
CONTROLS = ["Velocity", "Position"]

#: The stream the followed cursor is recorded on, and the one `train` looks for to tell
#: a pursuit session from a cued one. Named here so the writer and the reader cannot
#: drift; the channel layout is `TargetSource`'s, not this app's.
TARGET_STREAM = "target"
#: The block the subject follows. Signed ``[-1, +1]`` — the same units as `POSES` below,
#: which is the whole reason a pursuit session and a cued session can be trained on
#: together. Defaults are a 58 s block: 5 s rest, 24 hops of 2 s, 5 s recover.
PURSUIT = Pursuit()

#: Opponent top tracking speed, in court-`y` per second. Fair is won by graded control
#: and lost by overshooting; Hard needs a clean early read.
OPPONENTS = {"Easy": 0.4, "Fair": 0.6, "Hard": 1.0}
LEVELS = list(OPPONENTS)

#: What each class *is*, as a paddle command. Classification is regression that emits a
#: constant: the model picks a row, and that row is pushed exactly as a regressor's own
#: numbers are. Adding a class means adding a row here — `predict` does not change.
POSES: dict[str, float] = {"Down": -1.0, "Rest": 0.0, "Up": 1.0}
# A class with no command would silently push a rest frame and look like a model that
# never fires. Caught here, at import, rather than on the subject.
assert set(POSES) == set(CLASSES), f"POSES and CLASSES disagree: {set(POSES) ^ set(CLASSES)}"
#: The same table as an array, indexed by class. It is the regression target at train
#: time and the read-out lookup at predict time, so the two cannot drift apart.
POSE_VALUES = np.array([POSES[name] for name in CLASSES], dtype=np.float32)

vhi = virtual_hand()

# Where the prediction goes. The left side is ours, the right side is VHI's; nothing is
# resolved until VHI answers, which is why binding is a button and not an import.
CONTROL_FILE = pathlib.Path(__file__).resolve().parent.parent / "controls" / "pong.toml"
with CONTROL_FILE.open("rb") as handle:  # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(handle))

output_filter = PostProcessor(hz=PREDICT_HZ)
vhi_control = vhi.control_client()

app = App("MyoGestic — pong", require_participant=True)
# The cursor is a *recorded signal*, not a start time plus a copy of the parameters:
# it lands in the session on the same clock as the EMG, aligned by construction. It is
# deliberately not connected here — see `_start_block`, which is the press that does it.
target = TargetSource(PURSUIT)
target_stream = Stream(TARGET_STREAM, source=target, window_ms=WINDOW_MS)
app.streams(
    Stream("emg", source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS), target_stream
)
pipeline = Pipeline(app, predict_hz=PREDICT_HZ)
link = ControlLink(
    CONTROL_MAP,
    [RemoteTarget(client=vhi_control, interface=vhi)],
    ctx=app.ctx,
    # No `smoothing=` here on purpose: `_smooth` already ran on the value both the
    # paddle and the hand receive. Filtering again on this branch alone would put the
    # hand a few frames behind the paddle it mirrors.
    hz=PREDICT_HZ,
)
# Dicts, so the UI callbacks write them without `global`. `training_mode` is read only by
# `train`, `opponent_level` only by `_new_game`.
training_mode = {"index": 0}
record_protocol = {"index": 0}
PROTOCOLS = ["Follow the cursor", "Gestures"]
opponent_level = {"index": LEVELS.index("Fair")}
control_mode = {"index": 0}
#: Whether the *block* started the recording it is being written into. It stops the one
#: it started and nothing else: an operator who pressed Record by hand before the block
#: keeps their take when the cursor reaches the end of its path.
block = {"recording": False}
#: The cued command, held between presses. It drives the paddle while recording, which
#: is what makes a trial legible: the subject sees where the class they are being asked
#: for actually puts the bat.
held_cue = 0.0
features = FeatureSelector(
    {"RMS": rms, "MAV": mav, "WL": wl, "VAR": var, "ZC": zc},
    default=["RMS", "MAV"], show_header=False,
)
#: How each feature answers a gain ``g``: RMS/MAV/WL by ``g``, VAR by ``g**2``, ZC not at
#: all. The gain only cancels if every ticked column moves alike, so `train` refuses a mix
#: in Proportional mode.
_GAIN_DEGREE = {"RMS": 1, "MAV": 1, "WL": 1, "VAR": 2, "ZC": 0}


@pipeline.extract
def extract(windows: dict[str, np.ndarray]) -> np.ndarray | None:
    """Active features of the EMG window, stacked along axis 0."""
    # `.get`, not `[...]`: a stream added at runtime has no data on its first ticks and
    # the predict loop only passes the ones that do, so a subscript raises 32×/second.
    window = windows.get("emg")
    return None if window is None else features(window)


@pipeline.train
def train(data: TrainingData) -> tuple[str, Any]:
    """Fit the mode the switch currently shows, and return it with the estimator.

    Each session is read the way it was recorded, decided per session rather than by a
    switch: a session carrying a `TARGET_STREAM` was a pursuit block and its windows are
    paired with the cursor value at the window's *end* (`iter_target_windows`, which is
    causal); anything else is a cued block and its windows carry a class, which `POSES`
    turns into the same number the cursor would have been showing. Old recordings made
    before the cursor existed therefore still train, and a mixed selection trains on the
    union.

    **Carrying the stream is not the same as having followed it**, and routing on
    presence alone loses data three ways, so the cued path is the fallback rather than
    the other branch of an either/or:

    - `_end_block` stops the *task* and leaves the *stream* attached, by design — so
      every cued take recorded after a pursuit block carries a `TARGET_STREAM` full of
      ``idle``, which `iter_target_windows` correctly drops every window of. Its label
      track is the real record and gets read.
    - A recording stopped inside the source's 100 ms chunk leaves the stream present and
      empty, which `iter_target_windows` raises on. One mis-pressed take must not throw
      away every other ticked session's windows.
    - Either way the session is *named* in the log with what it contributed, so
      "trained on less than I selected" is visible rather than inferred.

    **Units are checked, not assumed.** Both protocols land in one signed
    ``[-1, +1]`` column — a class is a constant target, so Down / Rest / Up are the
    levels -1 / 0 / +1 — which is the entire reason for having a signed standard. But
    `TargetSource` is also what `force_ramps.py` records a `Trapezoid` with, under the
    same stream name, the same channel names and into the same folder, in **percent of
    MVC**; a `StreamInfo` carries no unit, so nothing in the recording can tell the two
    apart. Concatenated, 0..100 beside ±1 collapses `directional_decoder`'s effort span
    by two orders of magnitude and the graded command becomes a three-step staircase —
    silently, because every one of that recipe's own guards passes. So the level is
    range-checked per session, and a force-ramp session is refused by name.
    """
    if data.is_empty:
        raise ValueError("No sessions selected. Scan folder, then tick some.")
    if features.n_active == 0:
        raise ValueError("No features ticked in the FEATURES panel (RMS+MAV is the default).")
    mode = MODES[training_mode["index"]]
    if mode == "Proportional" and len({_GAIN_DEGREE[n] for n in features.active_names}) > 1:
        raise ValueError(
            f"Proportional mode needs features that all answer an electrode gain the same "
            f"way, and {' + '.join(features.active_names)} do not (RMS/MAV/WL scale by g, "
            f"VAR by g², ZC not at all). Tick one of those groups, or switch to Regression."
        )

    split = split_sessions_by_stream(data.paths, TARGET_STREAM)
    all_x: list[np.ndarray] = []
    # Where the paddle should be, in signed control units, whichever protocol said so.
    # One column for all three modes — Down being a real `-1` is what teaches any of
    # these fits the half a one-way target never sees.
    all_y: list[float] = []
    read: list[str] = []

    # Sessions the target path could not use, sent on to the cued path below.
    fell_back: list[str] = []
    for path in split.with_stream:
        seen = len(all_x)
        name = pathlib.Path(path).name
        try:
            for window, _ts, value in iter_target_windows(
                [path], "emg", TARGET_STREAM, WINDOW_MS, HOP_MS
            ):
                # Through `extract`, not `features`, so training and prediction cannot
                # diverge — the same call the cued loop below and `predict` both make.
                all_x.append(extract({"emg": window}))
                all_y.append(float(value))
        except ValueError as exc:
            # An empty or mis-shaped target stream. Truncate whatever the generator got
            # through before it raised, then let the label track answer for the session.
            del all_x[seen:], all_y[seen:]
            app.ctx.log(f"{name}: {TARGET_STREAM!r} unusable ({exc}) — reading its labels")
            fell_back.append(path)
            continue
        if len(all_x) == seen:
            # Present but never followed: the `idle` stream every cued take inherits
            # after a block. Its labels are the real record.
            fell_back.append(path)
            continue
        peak = max(abs(v) for v in all_y[seen:])
        if peak > 1.0:
            raise ValueError(
                f"{name} recorded {TARGET_STREAM!r} in units this app cannot train on: "
                f"the level reaches {peak:.3g}, and a paddle command is signed [-1, +1]. "
                f"That is a force-ramp session (percent of MVC) — train it in "
                f"force_ramps.py, or untick it here."
            )
        read.append(f"{name}: pursuit, {len(all_x) - seen} windows")

    for path in [*fell_back, *split.without_stream, *(p for p, _ in split.unreadable)]:
        seen = len(all_x)
        for window, _ts, class_idx in iter_labeled_windows(
            # `or None` because an empty set filters every window out, and that is what
            # `SessionManager` returns when the selection has no class pool yet.
            [path],
            "emg",
            WINDOW_MS,
            HOP_MS,
            classes=data.classes or None,
        ):
            all_x.append(extract({"emg": window}))
            all_y.append(float(POSE_VALUES[class_idx]))
        read.append(f"{pathlib.Path(path).name}: cued, {len(all_x) - seen} windows")

    if len(all_x) < 2:
        raise ValueError(f"Need at least 2 windows, got {len(all_x)}. Record longer trials.")
    x = np.stack(all_x)
    y = np.array(all_y, dtype=np.float32)
    if len(np.unique(y)) < 2:
        raise ValueError(f"Need ≥2 distinct target levels, got {len(np.unique(y))}.")

    if mode == "Classification":
        # Nearest `POSES` row to the target given — the same lookup `predict` uses, so a
        # pursuit block quantised to three of them shows this mode's floor honestly.
        est = catboost_classifier(iterations=100)
        est.fit(x, np.argmin(np.abs(POSE_VALUES[None, :] - y[:, None]), axis=1))
    else:
        # Proportional and Regression share the signed column above. The decoder reads
        # only its sign plus which windows are rest (`0`), the regressor reads the
        # level, and neither can be handed a different idea of what "Up" is.
        est = (
            directional_decoder() if mode == "Proportional" else catboost_regressor(iterations=200)
        )
        est.fit(x, y)
    # `ctx.log`, not `print`: the operator is looking at `LogPanel`, and this line is
    # the only place a session that contributed nothing says so.
    app.ctx.log(f"[train] {mode.lower()} on {len(all_x)} windows · " + " · ".join(read))
    return mode, est


def _smooth(command: float) -> float:
    """One command through the output filter, as the one-element vector it takes.

    Applied here rather than handed to `ControlLink(smoothing=...)`, which is where it
    would naturally go, because that smooths only what reaches the Virtual Hand. The
    paddle does not go through the bus — it must not, or the game would stop whenever
    VHI is down — so a filter on that branch leaves the two consumers reading different
    numbers, and the hand no longer mirrors the paddle it is supposed to mirror.
    Smoothing the shared value keeps them the same number.

    Raw per-window regression on EMG is jittery enough that the paddle buzzes at rest
    and overshoots the return, which reads to a subject as *their* control being bad.
    `PostProcessor` defaults to 1€, which is the right shape here: a fixed cutoff must
    either pass the jitter at rest or lag the fast contraction that saves the ball,
    while 1€ moves its cutoff with the signal's own velocity and does neither.
    """
    return float(output_filter(np.array([command], dtype=np.float32))[0])


@pipeline.predict
def predict(model: tuple[str, Any], feats: np.ndarray | None) -> dict | None:
    """Run the model in the mode it was trained in and move the paddle.

    The mode comes out of ``model``, never off the live switch: flipping the switch
    with a classifier loaded would send a class *index* down the regression branch, and
    index 2 clamps to a paddle pinned at the top of the court.
    """
    if feats is None:
        return None
    mode, est = model
    if mode == "Classification":
        class_idx = int(np.argmax(est.predict_proba(feats.reshape(1, -1))[0]))
        # The class names a command; the command is what gets sent. Same alias, same
        # units as the regressor below — a constant instead of a curve. Smoothed like
        # the regressor too, so a class flip slides the paddle instead of teleporting it.
        value = _smooth(POSES[CLASSES[class_idx]])
    else:
        # Proportional and Regression share this branch: both emit one signed number, so
        # a second branch could only drift. Clamped because a regressor fitted on
        # {-1, 0, +1} extrapolates past both ends on noisy EMG.
        value = _smooth(min(max(float(est.predict(feats.reshape(1, -1))[0]), -1.0), 1.0))
        # From the *smoothed* value, so the read-out names where the paddle actually is.
        class_idx = int(np.argmin(np.abs(POSE_VALUES - value)))

    out: dict[str, Any] = {"class": class_idx, "paddle": value}
    bus = link.bus
    if bus is not None:
        # `link.bus`, never `link.ensure()`: binding blocks on an RPC and this runs on
        # the predict thread. `None` is the normal state — VHI is a mirror here, so the
        # game is fully playable with nothing ever bound.
        out["controls"] = bus.push({"paddle": value})
    return out


layout = Layout(
    wide=Grid.areas(
        """
        header   header
        signal   step
        signal   sessions
        log      sessions
        """,
        row_height=[Px(52), Fr(3), Fr(1), Px(110)],
        col_width=[Fr(1), Px(400)],
        bare=("header",),
    ),
    narrow=Grid.areas(
        """
        header
        signal
        step
        sessions
        log
        """,
        row_height=[Px(52), Fr(2), Fr(3), Fr(1.5), Px(110)],
        bare=("header",),
    ),
    breakpoint=Px(1100),
)
steps = StepBar(["Connect", "Record", "Train", "Play"], widget_id="pong_steps")
participant = ParticipantPanel()
header = AppHeader("Pong", steps=steps, participant=participant)

# The cursor is generated here, not acquired — pointing a device at it would replace
# the very thing the block is recording.
device = DevicePicker(
    "emg", selectable=True, exclude=(TARGET_STREAM,), show_header=False,
    # The picker names additional amplifiers; the app owns their geometry.
    on_add=lambda name: app.add_stream(
        Stream(name, source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS)
    ),
    on_remove=app.remove_stream,
)
log = LogPanel(title="Activity log")
# The Source panel owns connecting, so the viewer offers no button of its own.
viewer = SignalViewer("emg", show_connect=False, selectable=True, show_title=True)


def _new_game() -> PongTask:
    """A fresh court at the selected difficulty and control mode.

    Rebuilt rather than retuned because `opponent` and `control` are both constructor
    arguments, and that is the right shape for either here anyway: the score of a rally
    played against a slower paddle — or with a different thing on the other end of the
    command — does not carry over, so changing one *should* reset it.

    `court_height=0` fills the subject's view, so a fixed 260 px court would leave
    most of it dead grey.
    """
    return PongTask(
        court_height=0.0,
        control=CONTROLS[control_mode["index"]].lower(),
        opponent=OPPONENTS[LEVELS[opponent_level["index"]]],
    )


pong = _new_game()
# `launchable`, never `launcher`: a VHI that cannot be launched must not stop this app
# from opening, and one already running needs no button.
hand_processes = vhi.launchable()
processes = ProcessLauncher(hand_processes)
# VHI takes seconds to boot and `ensure()` blocks, so this retries in the background —
# rate-limited and single-flight, safe to poll every frame.
binder = ControlLinkConnector(link)
sessions = SessionManager("sessions", class_names=CLASSES)
train_button = TrainButton(pipeline, size=(-1, 0))
predict_button = PredictButton(pipeline, size=(-1, 0))
training_log = TrainingLog(pipeline)
# No probability bar: three classes on one axis, and the paddle beside it already shows
# the magnitude the bar would. The name is the part the court cannot say.
prediction = PredictionLabel(pipeline, CLASSES)


#: What drives each alias of the control map *in this app*. The map says where a value
#: goes; only the app knows what sends one, and a panel listing bare identifiers leaves
#: the operator to guess which of them the model is actually moving.
ALIAS_ROLES = {"paddle": "the model while predicting, the cue while recording"}
#: A map that declares an alias nothing here pushes would show a control in this panel
#: that never moves, so the fallback should never be reached — it is a warning, not a row.
UNDRIVEN = "declared but never sent — wrong map?"


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
        app.ctx.log("VHI is not answering — launch or bind the Virtual Hand in Connect.")
    return bus


def _on_cue(index: int) -> None:
    """Put the cued class on the paddle.

    Remembering is the whole job. Unlike `myocontrol`, this does **not** bind: the cue is
    shown on the paddle, which needs no bus at all, so binding on every press would log
    "VHI is not answering" along the app's entirely normal path. Binding stays a Connect
    act, for the operator who actually wants the wrist to mirror.
    """
    global held_cue
    held_cue = POSES[CLASSES[index]]


recording = RecordingControls(
    CLASSES,
    on_record=app.start_recording,
    on_stop=app.stop_recording,
    on_gesture=_on_cue,
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


def _cursor() -> float | None:
    """Where the followed cursor is now, or ``None`` when no block is running.

    `TargetSource.elapsed` is the task time of the newest sample it actually *emitted*,
    so this is the level the recording holds — not a second clock reading that would
    put the ghost a frame off the ground truth the model is later fitted against.
    """
    return PURSUIT.value_at(target.elapsed) if target.running else None


#: Live-effort state for the current block. Both references come from the block itself,
#: so the gauge needs no calibration step: `Pursuit` opens with `rest_s` seconds pinned at
#: 0.0, which is the baseline, and it reaches full deflection, which sets the scale.
_EFFORT: dict = {"rest": [], "peak": 0.0, "shape": [], "sign": [], "asked": [], "got": []}


def _effort(ctx) -> float | None:
    """How hard the subject is contracting now, on ``0..1``, with no model involved.

    Total RMS across channels, referenced to this block's own rest phase and scaled by the
    strongest contraction it has seen. That matters because during a block there *is* no
    model: without this the subject is asked to follow a cursor with no feedback of any
    kind, which is not a task anyone can perform. It is deliberately amplitude only —
    direction needs exactly the labels the block is being recorded to provide.

    Self-scaling has one honest cost: the first real contraction defines the top of the
    gauge, so it reads full whatever it was. It settles within a couple of excursions, and
    the tick at the asked-for level is what the subject actually aims at.
    """
    stream = ctx.streams.get("emg")
    if stream is None:
        return None
    data, _ts = stream.get_window()
    if data.size == 0:
        return None
    per_channel = np.sqrt((data.astype(np.float64) ** 2).mean(axis=-1))
    total = float(per_channel.sum())

    level = _cursor()
    if level is not None and PURSUIT.phase_at(target.elapsed) == "rest":
        _EFFORT["rest"].append(total)
    rest_totals = _EFFORT["rest"]
    rest = float(np.median(rest_totals)) if rest_totals else total
    above = max(total - rest, 0.0)

    # Without this floor `peak` is set by the loudest *resting* sample and the gauge
    # reads near full on noise — measured 0.815 two seconds into a block nobody moved in.
    spread = float(np.std(rest_totals)) if len(rest_totals) > 2 else 0.0
    if above > max(4.0 * spread, 1e-9) and above > _EFFORT["peak"]:
        _EFFORT["peak"] = above
    got = above / _EFFORT["peak"] if _EFFORT["peak"] > 0.0 else 0.0
    got = min(max(got, 0.0), 1.0)

    # Kept for the verdict: the spatial pattern says whether the two directions were
    # distinguishable at all, which is the one thing no live gauge can show.
    if level is not None and total > 0.0:
        _EFFORT["shape"].append(per_channel / total)
        _EFFORT["sign"].append(float(np.sign(level)))
        _EFFORT["asked"].append(abs(level))
        _EFFORT["got"].append(got)
    return got


def _verdict() -> str:
    """Was that take any good — as two numbers, straight after the block.

    `r` is how well the subject's effort followed what was asked; `sep` is the best
    single-channel separation between the two directions on the amplitude-normalised
    pattern, in units of pooled standard deviation. `sep` is the one that decides whether
    a decoder can be fitted at all: on real recordings a clean pair reaches 8-11 and
    amplitude alone manages 0.5, so a low number means the two gestures went out on the
    same muscles however well the cursor was tracked.

    Indicative, not a statistic: frames overlap, so the sample count is not an *n*.
    """
    asked, got = np.asarray(_EFFORT["asked"]), np.asarray(_EFFORT["got"])
    sign, shape = np.asarray(_EFFORT["sign"]), np.asarray(_EFFORT["shape"])
    if len(asked) < 20 or sign.min() >= 0.0 or sign.max() <= 0.0:
        return "too short to judge"
    r = float(np.corrcoef(asked, got)[0, 1]) if asked.std() > 0 and got.std() > 0 else 0.0
    dn, up = shape[sign < 0], shape[sign > 0]
    pooled = np.sqrt((dn.var(0) + up.var(0)) / 2.0)
    sep = float(np.max(np.abs(dn.mean(0) - up.mean(0)) / np.maximum(pooled, 1e-12)))
    return f"effort followed the cursor r={r:+.2f} · direction separation {sep:.1f}"


def _start_block() -> None:
    """Connect the cursor stream, start recording, and run the block. One press.

    All three, because any two of them without the third produce a session that looks
    fine and is useless: `App.start_recording` sizes one array per *attached* stream, so
    a cursor connected afterwards is not in the take, and a block run outside a
    recording is a subject tracking something nobody wrote down.

    Nothing here happens on its own. This is the "explicit press" the rule asks for, and
    it is also why the target stream is left disconnected at import.
    """
    _EFFORT.update(rest=[], peak=0.0, shape=[], sign=[], asked=[], got=[])
    block["verdict"] = ""
    if target_stream.info is None and not target_stream.reconnect():
        app.ctx.log(f"cursor stream did not start: {target_stream.last_error}")
        return
    if app.ctx.state == "idle":
        app.start_recording()
        if app.ctx.state != "recording":
            return
        block["recording"] = True
    target.start()


def _end_block() -> None:
    """Stop the block, and the recording if this app's own press started one."""
    block["verdict"] = _verdict()
    app.ctx.log(f"[block] {block['verdict']}")
    target.stop()
    if block["recording"]:
        block["recording"] = False
        app.stop_recording()


def block_ui() -> None:
    """Start and stop a pursuit block, and say how far through it is.

    On the first block the ghost is all the subject has: there is no model yet, so the
    paddle is not their output and they are following the cursor open-loop. Once one is
    trained and the predict loop is running, the same press gives the closed loop the
    protocol is really after — ghost is the target, paddle is what the decoder made of
    the effort, and the gap between them is the error being trained out.
    """
    running = target.running
    with tinted_row(SUCCESS if running else IDLE):
        _detail("Following the cursor" if running else "Ready to follow")
        if running:
            mono_text(f"{target.elapsed:.0f} / {PURSUIT.total_duration:.0f} s", muted())
    if primary_button("Stop" if running else "Follow the cursor",
                      size=(imgui.get_content_region_avail().x, 0)):
        if running:
            _end_block()
        else:
            _start_block()
    _detail("Records the EMG and the cursor it asks for.")
    if block.get("verdict"):
        _detail(block["verdict"], numeric=True)


def _command(ctx) -> float:
    """What the paddle follows: the model while predicting, the cue otherwise.

    One float, computed in one place. `predict` writes it into `pipeline.predictions`
    and the bus gets the same number, so the game and the wrist cannot disagree.
    """
    if ctx.state == "predicting":
        return float(pipeline.predictions.get("paddle", 0.0))
    return held_cue


def _detail(text: str, *, numeric: bool = False) -> None:
    """Keep a detail on one line, with the complete text available on hover."""
    full = text
    width = imgui.get_content_region_avail().x
    font = mono_font() if numeric else None
    if font is not None:
        imgui.push_font(font, imgui.get_style().font_size_base)
    while text and imgui.calc_text_size(text).x > width:
        text = text[:-2] + "…" if len(text) > 1 else ""
    if numeric:
        mono_text(text, muted())
    else:
        imgui.text_colored(muted(), text)
    if font is not None:
        imgui.pop_font()
    imgui.set_item_tooltip(full)


def _choice(key: str, caption: str, options: list[str], selected: int) -> int:
    """Caption a segmented choice, wrapping whole segments in narrow cells."""
    imgui.text_colored(muted(), caption)
    room = imgui.get_content_region_avail().x
    padding = 2 * imgui.get_style().frame_padding.x
    start = 0
    result = selected
    while start < len(options):
        end, width = start + 1, imgui.calc_text_size(options[start]).x + padding
        while end < len(options):
            next_width = imgui.calc_text_size(options[end]).x + padding + ui_px(2)
            if width + next_width > room:
                break
            width += next_width
            end += 1
        choice = segmented(f"{key}:{start}", options[start:end], selected - start)
        if choice != selected - start:
            result = start + choice
        start = end
    return result


def connect_ui(ctx: Context) -> None:
    """Choose acquisition and connect the optional hand mirror."""
    device.ui(ctx)
    imgui.spacing()
    hand_ui()


def record_ui(ctx: Context) -> None:
    """Choose a recording protocol without changing what the next model fits."""
    # This switches controls, not the capture: a cursor block may join a take the
    # operator started by hand, and `_end_block` leaves that take running.
    record_protocol["index"] = _choice("protocol", "Recording protocol", PROTOCOLS, record_protocol["index"])
    imgui.spacing()
    if record_protocol["index"] == 0:
        recording.ui(ctx, visible=False)
        block_ui()
    else:
        recording.ui(ctx)


def model_ui() -> None:
    """Choose the fit and its features, train on selected takes, and read its log."""
    training_mode["index"] = _choice("mode", "Training mode", MODES, training_mode["index"])
    model = pipeline.model
    with tinted_row(IDLE if model is None else
                    WARNING if model[0] != MODES[training_mode["index"]] else SUCCESS):
        _detail("No model yet — train to begin." if model is None else
                f"Driving: {model[0].lower()}" +
                (" — train to switch" if model[0] != MODES[training_mode["index"]] else ""))
    imgui.text_colored(muted(), "Features")
    features.ui()
    imgui.spacing()
    train_button.ui()
    training_log.ui()


def play_ui() -> None:
    """Start prediction and tune the court and the output mirrored by the hand."""
    global pong
    # A model with few distinct outputs is playable under velocity and stuck
    # under position. Changing either court setting resets the rally.
    control = _choice("control", "Paddle control", CONTROLS, control_mode["index"])
    if control != control_mode["index"]:
        control_mode["index"] = control
        pong = _new_game()
    _detail("The command is a speed." if control == 0 else "The command is the height.")
    level = _choice("opponent", "Opponent", LEVELS, opponent_level["index"])
    if level != opponent_level["index"]:
        opponent_level["index"] = level
        pong = _new_game()
    _detail("Changing this clears the court — serve again.")
    imgui.spacing()
    output_filter.ui()
    imgui.spacing()
    imgui.text_colored(muted(), "Sent to the hand")
    # Signed text preserves the negative half a progress bar would hide.
    for line in _pushed().splitlines():
        _detail(line, numeric=True)
    imgui.spacing()
    prediction.ui()
    predict_button.ui()


hand_status = {"error": ""}


def hand_ui() -> None:
    """Keep the optional launcher and mirror connection in one compact row.

    The paddle never reads the bus, so everything here only buys the mirror — a
    wrist that follows the same number the court is already showing.
    """
    bound = link.bus is not None
    running = processes.running(vhi.name)
    error = hand_status["error"] or binder.last_error
    tone = SUCCESS if bound else DANGER if error else WARNING if running else IDLE
    detail = ("Bound — the wrist mirrors the paddle." if bound else
              "Connection failed" if error else
              "Launched — connecting…" if running else "Not connected")
    if not bound and running:
        # Launch arms the background binder; an idle app never polls it.
        binder.poll()
        detail = binder.status or "Binding as soon as VHI answers…"
    mapping = "\n".join(
        f"{alias} → {', '.join(ref.address for ref in binding.targets)} · {ALIAS_ROLES.get(alias, UNDRIVEN)}"
        for alias, binding in CONTROL_MAP.bindings.items()
    )
    hint = ("Launch the Virtual Hand, or bind to one already running." if hand_processes else
            "Start the Virtual Hand, then bind to mirror the paddle.")
    tooltip = f"{detail}\n{error or hint}\nOptional — the game plays without it.\n\n{mapping}"
    if not hand_processes:
        tooltip += f"\n\n{vhi.install_hint.strip()}"
    style = imgui.get_style()
    action_count = int(bool(hand_processes)) + int(not bound)
    action_width = imgui.calc_text_size(fa.ICON_FA_LINK).x + 2 * style.frame_padding.x
    reserved = action_count * (action_width + style.item_spacing.x)
    with tinted_row() as width:
        right = imgui.get_cursor_pos_x() + width
        imgui.align_text_to_frame_padding()
        imgui.text_colored(tone, fa.ICON_FA_CIRCLE)
        imgui.same_line()
        room = max(0.0, right - reserved - imgui.get_cursor_pos_x())
        imgui.text_colored(primary(), fit_text("Virtual Hand", room))
        imgui.set_item_tooltip(tooltip)
        remaining = (right - reserved - imgui.get_item_rect_max().x
                     + imgui.get_window_pos().x - style.item_spacing.x)
        if remaining > ui_px(60):
            imgui.same_line()
            imgui.push_font(mono_font(), style.font_size_base)
            mono_text(fit_text(detail, remaining), muted())
            imgui.pop_font()
            imgui.set_item_tooltip(tooltip)
        if hand_processes:
            imgui.same_line()
            imgui.set_cursor_pos_x(right - reserved + style.item_spacing.x)
            icon = fa.ICON_FA_STOP if running else fa.ICON_FA_PLAY
            if imgui.small_button(f"{icon}##launch_hand"):
                if running:
                    processes.stop(vhi.name)
                else:
                    try:
                        processes.launch(vhi.name)
                        hand_status["error"] = ""
                    except Exception as exc:
                        hand_status["error"] = str(exc)
                        app.ctx.log(f"Virtual Hand launch failed: {exc}")
            imgui.set_item_tooltip("Stop the Virtual Hand" if running else "Launch the Virtual Hand")
        if not bound:
            imgui.same_line()
            imgui.set_cursor_pos_x(right - action_width)
            if imgui.small_button(f"{fa.ICON_FA_LINK}##bind_hand") and _bind() is None:
                app.ctx.log("VHI did not answer. Launch it here, or start it before the app.")
            imgui.set_item_tooltip("Retry binding the Virtual Hand" if error else "Bind the Virtual Hand")


def _step_done(ctx: Context) -> list[bool]:
    """Completion reflects connection, participant takes, a model and live prediction."""
    stream = ctx.streams.get("emg")
    return [
        stream is not None and stream.status == "connected" and stream.info is not None,
        bool(ctx.participant)
        and any(pathlib.Path("sessions", ctx.participant).glob(f"{ctx.participant}_*")),
        pipeline.model is not None,
        ctx.state == "predicting",
    ]


@app.ui
def pong_ui(ctx: Context) -> None:
    """Keep the subject's view, sessions and activity visible around the active step."""
    # `TargetSource` ends its own block on the acquire thread even while another
    # step is open. This just closes the recording that press opened.
    if block["recording"] and not target.running:
        _end_block()

    with layout["header"]:
        active = header.ui(ctx, _step_done(ctx))
    padding = imgui.get_style().window_padding
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(padding.x, ui_px(4)))
    # Recording state advances once each frame, including when its controls are hidden.
    if active != 1:
        recording.ui(ctx, visible=False)
    # Refresh the selection before Train can read it this frame.
    with layout["sessions"]:
        pipeline.training_data = sessions.ui(participant=ctx.participant)
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
            play_ui()
    with layout["signal"]:
        if active == 0:
            viewer.ui(ctx)
        else:
            # The ghost is the cursor and nothing else: `None` outside a block, so
            # the court is exactly what it was whenever no one is being asked to
            # follow anything.
            pong.ui(_command(ctx), _cursor(), _effort(ctx))
    with layout["log"]:
        log.ui(ctx)
    imgui.pop_style_var()

    # Stream it, do not fire it once: VHI holds a pose only while samples keep arriving
    # (5 s, then `StopToRest()`). While predicting the predict loop is already doing that.
    bus = link.bus
    if bus is not None and ctx.state != "predicting":
        bus.push({"paddle": held_cue})


def main() -> None:
    try:
        app.run()
    finally:
        link.stop()
        vhi_control.stop()


if __name__ == "__main__":
    main()
