"""Pong: pick a device, follow the cursor, train, then play with your wrist.

One signed number in ``[-1, +1]`` moves the paddle. That is the whole protocol, and it
is the point: a rally rewards *graded* contraction where a trapezoid only rewards
tracking and a gesture classifier rewards nothing continuous at all.

There are two ways to record the training set and the Model tab starts either.
**Follow the cursor** runs a `Pursuit` block: a ghost paddle wanders the court and the
subject chases it, with the cursor recorded beside the EMG on the `target` stream. The
Down / Rest / Up buttons cue the older three-class protocol. Prefer the cursor — three
cued classes are three distinct target values, so a tree ensemble fitted on them is a
three-class model whatever it is called, dead below about 30% effort and *non-monotonic*
in it. Densely covered levels cut the CatBoost error at intermediate efforts 14x. Note
what the measurement actually says: the active ingredient is the **number of distinct
target levels**, not pursuit as such — a cued staircase of eleven holds scores at least
as well, and a linear model gains nothing either way, because least squares already
draws a straight line through three points. What a followed cursor buys over a staircase
is human: told "go to 0.6" a subject has no idea what 0.6 feels like, while a cursor
gives continuous visual error feedback, so the intermediate levels are reachable at all.

The Virtual Hand is a **mirror**, not a target. The paddle follows a plain float that
reaches it whether or not VHI ever answers; when the Hand tab is bound, the same float
also goes to the wrist. Nothing here needs a hand to be playable.

The far paddle is played by the app, at a speed the Model tab sets. A wall returns
everything, so a rally against one only ever ends in the subject's own miss and the
score never says they are winning.

Run with:
    uv run --extra examples --extra grpc python examples/start_here/pong.py
"""

import pathlib
import tomllib
from typing import Any

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic import App, Fr, Grid, Stream, TrainingData
from myogestic.controls import ControlBus, ControlLink, ControlLinkConnector, load_control_map
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PipelinePanel
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
    DevicePicker,
    FeatureSelector,
    LogPanel,
    PongTask,
    PostProcessor,
    PredictionLabel,
    ProcessLauncher,
    RecordingControls,
    SessionManager,
    SignalViewer,
    StreamManager,
)
from myogestic.widgets.common import (
    SUCCESS,
    WARNING,
    mono_text,
    muted,
    panel_header,
    segmented,
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
# Proportional first, and it is the default, because the honest baseline is *wrong* in a
# way no read-out shows: the CatBoost regressor is non-monotonic in effort on real data.
# Scaling every channel by 1.0 -> 1.3 -> 1.6 moved its Up prediction 1.000 -> 0.882 ->
# 0.723, so contracting harder walks the paddle the wrong way — it had learned "louder =
# Down" because Down simply happened to be recorded harder. `directional_decoder`
# estimates effort and direction apart and multiplies them, and as long as every ticked
# feature answers a gain the same way (see `_DEGREE_1` below) that gain cancels out of the
# direction term exactly, so it can only change the magnitude and never the sign.
#
# The other two stay. Regression is the baseline that has to be felt to be believed, and
# Classification is the floor under both: it can only ever put the paddle in three places.
MODES = ["Proportional", "Regression", "Classification"]

#: How the command reaches the paddle, in `PongTask`'s own words, lower-cased for it.
#: Velocity first because that is the widget's default and because it is the mode a
#: three-level decoder is still playable in: the command is a *speed*, so integrating
#: even a coarse output reaches every height, where under position the paddle can only
#: ever be in as many places as the model has outputs.
CONTROLS = ["Velocity", "Position"]

#: The stream the followed cursor is recorded on, and the one `train` looks for to tell
#: a pursuit session from a cued one. Named here so the writer and the reader cannot
#: drift; the channel layout is `TargetSource`'s, not this app's.
TARGET_STREAM = "target"
#: The block the subject follows. Signed ``[-1, +1]`` — the same units as `POSES` below,
#: which is the whole reason a pursuit session and a cued session can be trained on
#: together. Defaults are a 58 s block: 5 s rest, 24 hops of 2 s, 5 s recover.
PURSUIT = Pursuit()

#: Opponent difficulty, as a factor on `ball_speed`: the far paddle's top tracking speed
#: is this many court-`y` per second. Fair is a rally the subject wins with graded control
#: and loses by overshooting, which is the drill; Hard covers more court than the ball
#: crosses in the time it has, so only a clean early read gets it past.
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

app = App("MyoGestic — pong", ui_scale=0.85)
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
    default=["RMS", "MAV"],
)
#: How each feature answers a gain ``g`` on the signal: RMS/MAV/WL scale by ``g``, VAR by
#: ``g**2``, ZC not at all. `directional_decoder` divides each row by its own sum, so the
#: gain only cancels if *every* ticked column moves by the same factor. A mix silently
#: costs Proportional mode the one guarantee it is here for, so `train` refuses instead.
#: The other two modes normalise nothing and take the whole palette.
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
        # A class names a pose, so the pose table read backwards is the label: nearest
        # `POSES` row to the target the subject was actually given. It is the same
        # lookup `predict` uses for the read-out, which is what keeps the floor honest
        # — this mode can only ever put the paddle in as many places as there are rows,
        # and a pursuit block quantised down to three of them shows exactly that.
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
        # Proportional and Regression share this branch, deliberately: both emit one
        # signed number from `.predict`, so a second branch could only let them drift.
        # Clamped to the *signed* range, and the clamp is what gets pushed. A regressor
        # fitted on {-1, 0, +1} extrapolates past both ends on noisy EMG, and the paddle
        # would sit against a wall while the read-out beside it still said "Up". The
        # decoder clips to the same range itself, so the clamp is a no-op for it.
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


grid = Grid(6, 3, row_height=[Fr(1)] * 6, col_width=[Fr(1), Fr(1), Fr(1)])

# The cursor is generated here, not acquired — pointing a device at it would replace
# the very thing the block is recording.
device = DevicePicker("emg", selectable=True, exclude=(TARGET_STREAM,))
# Add a second amplifier while the app runs. The panel names the stream; the app owns
# its geometry.
streams = StreamManager(
    on_add=lambda name: app.add_stream(
        Stream(name, source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS)
    ),
    on_remove=app.remove_stream,
)
log = LogPanel()
# The Source panel owns connecting, so the viewer offers no button of its own.
viewer = SignalViewer("emg", show_connect=False, selectable=True, show_title=True)


def _new_game() -> PongTask:
    """A fresh court at the selected difficulty and control mode.

    Rebuilt rather than retuned because `opponent` and `control` are both constructor
    arguments, and that is the right shape for either here anyway: the score of a rally
    played against a slower paddle — or with a different thing on the other end of the
    command — does not carry over, so changing one *should* reset it.

    `court_height=0` fills the cell. The game is this app's whole point and its cell is
    five rows tall, so a fixed 260 px court would leave most of it dead grey.
    """
    return PongTask(
        court_height=0.0,
        control=CONTROLS[control_mode["index"]].lower(),
        opponent=OPPONENTS[LEVELS[opponent_level["index"]]],
    )


pong = _new_game()
# `launchable`, never `launcher`: a VHI that cannot be launched must not stop this app
# from opening, and one already running needs no button.
processes = ProcessLauncher(vhi.launchable())
# Pressing Launch is the intent; a second Connect press would be ceremony. But VHI takes
# seconds to boot and `ensure()` blocks on an RPC, so binding on the click would stall the
# frame and fail anyway. The connector retries in the background instead — rate-limited,
# single-flight, safe to poll every frame.
binder = ControlLinkConnector(link)
sessions = SessionManager("sessions", class_names=CLASSES)
panel = PipelinePanel(pipeline)
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
        app.ctx.log("VHI is not answering — launch it from the Hand tab, or press Bind now.")
    return bus


def _on_cue(index: int) -> None:
    """Put the cued class on the paddle.

    Remembering is the whole job. Unlike `myocontrol`, this does **not** bind: the cue is
    shown on the paddle, which needs no bus at all, so binding on every press would log
    "VHI is not answering" along the app's entirely normal path. Binding stays a Hand-tab
    act, for the operator who actually wants the wrist to mirror.
    """
    global held_cue
    held_cue = POSES[CLASSES[index]]


recording = RecordingControls(
    CLASSES,
    on_record=app.start_recording,
    on_stop=app.stop_recording,
    on_gesture=_on_cue,
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

    # The floor is what makes this usable rather than maddening. Without it `peak` is set
    # by whichever resting sample happened to land highest, so the gauge reads near full
    # on noise and swings 0..1 through the whole rest phase — measured at 0.815 two
    # seconds in. Only an excursion clear of the resting spread is allowed to define the
    # scale, and until one arrives the gauge honestly reads nothing.
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
    panel_header("BLOCK", fa.ICON_FA_CROSSHAIRS, status=SUCCESS if target.running else None)
    full = imgui.ImVec2(-1, 0)
    if target.running:
        if imgui.button(f"{fa.ICON_FA_STOP}  Stop", full):
            _end_block()
        mono_text(f"following · {target.elapsed:.0f} / {PURSUIT.total_duration:.0f} s", muted())
    else:
        if imgui.button(f"{fa.ICON_FA_CROSSHAIRS}  Follow the cursor", full):
            _start_block()
        imgui.text_colored(muted(), "records the EMG and the cursor it asks for")
        if block.get("verdict"):
            mono_text(block["verdict"], muted())


def _command(ctx) -> float:
    """What the paddle follows: the model while predicting, the cue otherwise.

    One float, computed in one place. `predict` writes it into `pipeline.predictions`
    and the bus gets the same number, so the game and the wrist cannot disagree.
    """
    if ctx.state == "predicting":
        return float(pipeline.predictions.get("paddle", 0.0))
    return held_cue


def model_ui() -> None:
    """Model tab: the operator's knobs, and what the current model is doing.

    What the next Train builds, and how hard the opponent plays. Both belong here rather
    than beside the court: everything a *subject* needs is already on the Pong tab, so
    this one can sit on whatever the operator was last adjusting.
    """
    global pong
    panel_header("MODE")
    training_mode["index"] = segmented("mode", MODES, training_mode["index"])
    model = pipeline.model
    if model is None:
        imgui.text_disabled("no model yet — Train binds the mode into it")
    elif model[0] != MODES[training_mode["index"]]:
        imgui.text_colored(WARNING, f"driving: {model[0].lower()} — Train to switch")
    else:
        imgui.text_disabled(f"driving: {model[0].lower()}")
    imgui.spacing()

    # Beside the training mode because the two are read together: a model with few
    # distinct outputs is playable under velocity and stuck under position.
    panel_header("CONTROL")
    control = segmented("control", CONTROLS, control_mode["index"])
    if control != control_mode["index"]:
        control_mode["index"] = control
        pong = _new_game()
    imgui.text_disabled(
        "velocity: the command is a speed" if control == 0 else "position: it is the height"
    )
    imgui.spacing()

    block_ui()
    imgui.spacing()

    panel_header("OPPONENT")
    level = segmented("opponent", LEVELS, opponent_level["index"])
    if level != opponent_level["index"]:
        opponent_level["index"] = level
        pong = _new_game()
    imgui.text_disabled("changing this clears the court — Serve again")
    imgui.spacing()

    features.ui()
    panel.ui()
    output_filter.ui()
    prediction.ui()
    # A read-out, not a progress bar: the paddle command is signed and a bar would clamp
    # the negative half away without saying so.
    panel_header("PUSHED")
    mono_text(_pushed())


def hand_ui() -> None:
    """Hand tab: launch VHI, and bind to it once it answers.

    Optional throughout. The paddle never reads the bus, so everything here only buys
    the mirror — a wrist that follows the same number the court is already showing.
    """
    processes.ui()
    imgui.spacing()
    bound = link.bus is not None
    panel_header("CONTROL MAP", status=SUCCESS if bound else None)
    for alias, binding in CONTROL_MAP.bindings.items():
        mono_text(alias)
        imgui.indent(14)
        targets = binding.targets
        where = (
            f"{len(targets)} controls"
            if len(targets) > 1
            # The leading `vhi.` is the same on every row; the tail is what differs.
            else targets[0].address.split(".", 1)[-1]
        )
        imgui.text_colored(muted(), f"{where} · {ALIAS_ROLES.get(alias, UNDRIVEN)}")
        imgui.unindent(14)
    imgui.spacing()
    if bound:
        imgui.text_disabled("Bound — the wrist mirrors the paddle.")
        return
    if processes.running(vhi.name):
        # Launched from this panel: retry until its manifest answers. `poll` never blocks
        # and never raises, so a VHI that never comes up costs one attempt every 2 s.
        binder.poll()
        imgui.text_disabled(binder.status or "Launched — binding as soon as VHI answers…")
        return
    if imgui.button("Bind now") and _bind() is None:
        app.ctx.log("VHI did not answer. Launch it above, or start it before the app.")
    imgui.same_line()
    imgui.text_disabled("Optional — the game plays without it.")


@app.ui
def pong_ui(ctx):
    # `TargetSource` ends its own block, on the acquire thread, the moment the last
    # sample of the path has been emitted — a widget only ticks while it is drawn, so a
    # block left in a background tab would otherwise run past its end. All that is left
    # here is closing the recording that press opened.
    if block["recording"] and not target.running:
        _end_block()

    with grid[0:5, 0:2]:
        # Pong first: a layout pass draws only a tab bar's first tab, so this is the one
        # CI ever renders — and it is the one a subject looks at all session.
        if imgui.begin_tab_bar("game_cell"):
            selected, _ = imgui.begin_tab_item("Pong")
            if selected:
                # The ghost is the cursor and nothing else: `None` outside a block, so
                # the court is exactly what it was whenever no one is being asked to
                # follow anything.
                pong.ui(_command(ctx), _cursor(), _effort(ctx))
                imgui.end_tab_item()
            selected, _ = imgui.begin_tab_item("Signal")
            if selected:
                viewer.ui(ctx)
                imgui.end_tab_item()
            selected, _ = imgui.begin_tab_item("Model")
            if selected:
                model_ui()
                imgui.end_tab_item()
            imgui.end_tab_bar()
    with grid[5, 0:2]:
        log.ui(ctx)
    with grid[0:3, 2]:
        if imgui.begin_tab_bar("source_cell"):
            selected, _ = imgui.begin_tab_item("Source")
            if selected:
                device.ui(ctx)
                imgui.end_tab_item()
            selected, _ = imgui.begin_tab_item("Streams")
            if selected:
                streams.ui(ctx)
                imgui.end_tab_item()
            selected, _ = imgui.begin_tab_item("Hand")
            if selected:
                hand_ui()
                imgui.end_tab_item()
            imgui.end_tab_bar()
    with grid[3, 2]:
        recording.ui(ctx)
    with grid[4:6, 2]:
        pipeline.training_data = sessions.ui()

    # Stream it, do not fire it once. VHI's prediction hand follows a pose only while its
    # streams are *live* — `ControlPoseStaleAfterSeconds` is 5 s — and on the falling edge
    # it calls `StopToRest()` and hands the rig back to its own movement animation. So one
    # push moves the wrist and five seconds of silence returns it.
    #
    # Not the same thing as the outlet repeating its last value, which it does forever at
    # ~29 Hz. That keeps a value on the wire; VHI's liveness check is on the *arrival* of
    # samples.
    #
    # While predicting, the predict loop is already that producer at PREDICT_HZ. The
    # guard keeps the two from driving one set of outlets at two different rates.
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
