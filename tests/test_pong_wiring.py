"""What `examples/start_here/pong.py` claims on a fresh launch.

Most of this is ported from `test_myocontrol_wiring.py`, because the two apps share
every invariant that was hard to get right: the mode is bound into the model, `predict`
reads `link.bus` and never `ensure()`, nothing attaches at import, and the UI keeps the
frame alive while the predict loop is not running.

What is new is the **sign**. This is the first shipped app whose command is genuinely
bidirectional, and "the signed path, end to end" covers the ways that quietly stops
being true: a clamp copied from a one-way app, a cue table that only spans the positive
half, and a paddle that turns out to need a Virtual Hand after all.

The last section covers the third mode. `directional_decoder` is the default, so the
switch nobody touches is the one that has to be right — and unlike the two CatBoost
modes it has a real input contract (non-negative features, a signed target with a rest
block), which a wiring mistake satisfies just well enough to fit and then gets wrong.

One mechanical note that costs an afternoon otherwise: `runpy.run_path` returns a *copy*
of the module namespace, so a `global` rebind inside the module is invisible through the
dict it hands back. Live state is read through a function's ``__globals__``.
"""

import inspect
import runpy
from pathlib import Path

import numpy as np
import pytest
from imgui_bundle import imgui

import myogestic.core
import myogestic.remote
import myogestic.stream
from myogestic import TrainingData
from myogestic.controls import ControlLink
from myogestic.recipes.estimators import directional_decoder
from myogestic.session import Session
from myogestic.sources.target import PHASE_CODES
from myogestic.stream import StreamInfo
from myogestic.tracking import Pursuit
from myogestic.widgets import PongTask

_APP = Path(__file__).resolve().parent.parent / "examples" / "start_here" / "pong.py"


@pytest.fixture
def app_module(monkeypatch):
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    # `launchable()` swallows the FileNotFoundError, so this only spares a dev box
    # without VHI installed a pointless env probe at import.
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    monkeypatch.syspath_prepend(str(_APP.parent))
    return runpy.run_path(str(_APP), run_name="__main__")


class OnlyPredictProba:
    """A classifier. Asking it for `.predict` is the bug this stub detects."""

    def predict_proba(self, x):
        return np.array([[0.1, 0.2, 0.7]])  # -> "Up"


class Bus:
    """A bound bus that records the frames it is given."""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    def push(self, values):
        self.frames.append(dict(values))
        return values


def test_nothing_attaches_itself(monkeypatch):
    """ "Nothing attaches on its own" is the project's rule, and this app has no task
    target to except — so nothing may even *try* to connect.

    Asserted on the attempt, not on the outcome. ``DEFAULT_DEVICES[0]`` is a Muovi, real
    hardware that is not on this machine, so a module that did auto-connect would still
    leave every ``_connected`` False — the obvious version of this test passes whatever
    the module does, and its only symptom is a 30 s import while the socket times out.
    """
    called: list[str] = []
    monkeypatch.setattr(
        myogestic.stream.Stream, "reconnect", lambda self, *a, **k: called.append(self.name)
    )
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    monkeypatch.syspath_prepend(str(_APP.parent))
    runpy.run_path(str(_APP), run_name="__main__")

    assert called == [], f"connected without being asked: {called}"


def test_predict_uses_the_models_mode_not_the_switch(app_module):
    """The mode is bound into the model at Train, never read off the live switch.

    Reading it live means flipping the switch under a loaded classifier sends a class
    *index* down the regression branch — index 2 clamps to +1 and the paddle parks at
    the top of the court. The stub has no `.predict`, so a live read fails here with
    AttributeError instead of shipping.
    """
    app_module["training_mode"]["index"] = app_module["MODES"].index("Regression")

    out = app_module["predict"](("Classification", OnlyPredictProba()), np.zeros(4))

    assert out["class"] == app_module["CLASSES"].index("Up"), f"wrong branch: {out}"
    assert out["paddle"] == app_module["POSES"]["Up"]


def test_predict_never_binds_the_bus(app_module, monkeypatch):
    """`ensure()` costs a blocking RPC and `predict` runs on a deadline.

    RuntimeError, not ValueError: the example catches ValueError around `ensure` in its
    UI handlers, so a ValueError would be swallowed by a `predict` that routed through
    one of those and this would pass while the RPC still blocked the thread.
    """

    def boom(self):
        raise RuntimeError("predict must read link.bus, never call link.ensure()")

    monkeypatch.setattr(ControlLink, "ensure", boom)

    out = app_module["predict"](("Classification", OnlyPredictProba()), np.zeros(4))

    assert "controls" not in out, "nothing is bound, so nothing can have been pushed"


def test_the_model_and_hand_tabs_draw(app_module, implot_frame):
    """A layout pass only ever draws a tab bar's *first* tab, and that is Pong — so
    neither of these is reached by `test_example_draws_a_frame`."""
    implot_frame(app_module["model_ui"])
    implot_frame(app_module["hand_ui"])


def test_the_map_declares_exactly_what_the_app_pushes(app_module):
    """Every alias in the map is driven, and every alias pushed is declared.

    An alias the app never sends is a row in the Hand panel that never moves — the
    operator sees a control and cannot tell whether it is broken or simply unused. The
    other direction is worse: `push` silently drops a key the `ControlSet` does not
    declare, so a typo'd alias is a wrist that never moves and a log that says nothing.
    """
    bus = Bus()
    app_module["link"]._bus = bus
    try:
        app_module["predict"](("Classification", OnlyPredictProba()), np.zeros(4))
    finally:
        app_module["link"]._bus = None

    declared = set(app_module["CONTROL_MAP"].bindings)
    assert bus.frames and set(bus.frames[0]) == declared, (
        f"pushed {set(bus.frames[0]) if bus.frames else set()} but the map declares {declared}"
    )
    # One number, one alias. A second control here would be completed to rest on every
    # frame this app did not name it in.
    assert declared == {"paddle"}


def test_launching_vhi_is_what_arms_the_binder(app_module, monkeypatch, implot_frame):
    """Pressing Launch is the operator's intent; a second Connect press is ceremony.

    "Nothing attaches on its own" survives — the binding follows an act they performed.
    What must not happen is binding with no act at all, so the connector is polled only
    while the panel reports the process it started is alive.
    """
    polled: list[bool] = []
    monkeypatch.setattr(
        type(app_module["binder"]), "poll", lambda self, force=False: polled.append(True)
    )
    launcher = app_module["processes"]

    monkeypatch.setattr(type(launcher), "running", lambda self, name: False)
    implot_frame(app_module["hand_ui"])
    assert polled == [], "bound without anyone launching or pressing anything"

    monkeypatch.setattr(type(launcher), "running", lambda self, name: True)
    implot_frame(app_module["hand_ui"])
    assert polled == [True], "launched the target and then did not bind to it"


def test_the_binder_never_blocks_a_frame(app_module):
    """`poll` is the whole reason the connector exists: `ControlLink.ensure` blocks on an
    RPC, and this runs inside `@app.ui`."""
    source = inspect.getsource(app_module["hand_ui"])
    assert "binder.poll()" in source
    assert "link.ensure()" not in source, "ensure() would stall the render thread"


def test_every_class_has_a_command(app_module):
    """A class with no command pushes a rest frame and reads as a model that never
    fires — a silence, not an error. The module asserts it at import; this pins that the
    assert exists rather than that it happens to pass today."""
    assert set(app_module["POSES"]) == set(app_module["CLASSES"])


def test_a_class_is_a_command_and_goes_out_on_the_same_alias(app_module):
    """The two modes differ in where the number comes from, not in what is sent.

    A classifier picks a row of `POSES`; a regressor computes one. Both reach the bus as
    the same alias in the same units, which is why one control map serves both.

    The filter is reset between them because these are two models, not two frames of
    one run — without it the regressor's number arrives blended with the classifier's
    and the test would be measuring the smoother instead of the alias.
    """

    class Reg:
        def predict(self, x):
            return [0.42]

    bus = Bus()
    app_module["link"]._bus = bus
    try:
        app_module["predict"](("Classification", OnlyPredictProba()), np.zeros(4))
        app_module["output_filter"].reset()
        app_module["predict"](("Regression", Reg()), np.zeros(4))
    finally:
        app_module["link"]._bus = None

    classified, regressed = bus.frames
    assert set(classified) == set(regressed), "the modes push different aliases"
    assert classified["paddle"] == app_module["POSES"]["Up"]
    assert regressed["paddle"] == pytest.approx(0.42)


def test_the_paddle_and_the_hand_get_one_smoothed_number(app_module):
    """The mirror invariant, and the reason smoothing sits before the fork.

    The paddle cannot go through the bus — the game has to stay playable with VHI down
    — so both consumers are fed from one value inside `predict`. Hand the filter to
    `ControlLink(smoothing=...)` instead, which is where it looks like it belongs, and
    only the hand is filtered: it then trails the paddle it exists to mirror, by a few
    frames that grow with the cutoff. Nothing reports this. The bus still receives a
    number, the paddle still moves, and every read-out looks healthy.
    """

    class Ramp:
        """Rest, then a held contraction — the step a smoother has to round off."""

        def __init__(self) -> None:
            self.values = iter([0.0] + [1.0] * 5)

        def predict(self, x):
            return [next(self.values)]

    bus = Bus()
    est = Ramp()  # one estimator, six frames — a fresh one replays its first value
    app_module["output_filter"].reset()
    app_module["link"]._bus = bus
    try:
        outs = [app_module["predict"](("Regression", est), np.zeros(4)) for _ in range(6)]
    finally:
        app_module["link"]._bus = None

    for out, frame in zip(outs, bus.frames, strict=True):
        assert out["paddle"] == frame["paddle"], "the hand and the paddle diverged"

    # And it is genuinely filtered: the step does not arrive whole, but it does arrive.
    assert outs[1]["paddle"] < 1.0, "the step reached the paddle unsmoothed"
    assert outs[1]["paddle"] < outs[-1]["paddle"] <= 1.0, "the filter never converges"


def test_a_cue_press_neither_binds_nor_pushes(app_module, monkeypatch):
    """The deliberate difference from `myocontrol`, and it is worth a test.

    There the cue shows on VHI's control hand, so a press that reaches no VHI has to say
    so. Here it shows on the *paddle*, which needs no bus at all — binding on every press
    would log "VHI is not answering" along this app's entirely normal path. The press
    only remembers; `pong_ui` is what streams it once someone has bound by hand.
    """

    def boom(self):
        raise RuntimeError("a cue press must not bind")

    monkeypatch.setattr(ControlLink, "ensure", boom)
    bus = Bus()
    app_module["link"]._bus = bus
    try:
        app_module["_on_cue"](app_module["CLASSES"].index("Down"))
    finally:
        app_module["link"]._bus = None

    assert bus.frames == [], "the press pushed a frame of its own"
    # Through `__globals__`: `runpy` hands back a copy, so the rebind is invisible in it.
    assert app_module["_on_cue"].__globals__["held_cue"] == app_module["POSES"]["Down"]


def test_the_ui_streams_the_frame_while_the_predict_loop_is_not(app_module):
    """VHI drops a pose whose streams go quiet, so a command has to be sustained.

    `ControlPoseStaleAfterSeconds` is five seconds since the last sample, and on the
    falling edge VHI calls `StopToRest()` and gives the rig back to its own movement
    animation. Fire once and the wrist moves, then returns five seconds later. The
    predict loop is that producer while predicting; the cue buttons are used while
    *recording*, when it is not running, so the UI has to be.

    Not the same question as whether the outlet repeats its last value — it does,
    forever. That keeps a value on the wire, while VHI's liveness test is on samples
    *arriving*.

    Asserted on the source: the push sits at the tail of `@app.ui`, and reaching it in a
    layout pass would mean standing up the whole grid.
    """
    source = inspect.getsource(app_module["pong_ui"])

    assert "bus.push" in source, "nothing drives the wrist while recording"
    assert 'ctx.state != "predicting"' in source, (
        "the UI would drive the same outlets as the predict loop, at a different rate"
    )


# --- the signed path, end to end ----------------------------------------------
def test_the_regressor_is_not_clamped_to_the_positive_half(app_module):
    """`myocontrol`'s clamp is `[0, 1]` and copying it here is the silent failure.

    A lower bound of zero pins the paddle to the top half of the court with nothing ever
    lowering it, and every read-out still looks healthy: the model fires, the label
    changes, the bus receives a number. Only the negative half is gone.
    """

    class Reg:
        def predict(self, x):
            return [-0.62]

    bus = Bus()
    app_module["link"]._bus = bus
    try:
        out = app_module["predict"](("Regression", Reg()), np.zeros(4))
    finally:
        app_module["link"]._bus = None

    assert out["paddle"] == pytest.approx(-0.62), "the paddle never sees the low half"
    (frame,) = bus.frames
    assert frame["paddle"] == pytest.approx(-0.62), "the wrist never sees the low half"
    assert out["class"] == app_module["CLASSES"].index("Down"), "the read-out disagrees"


def test_the_cues_span_both_signs(app_module):
    """Three cues on one signed axis, and nothing gating them back to one-way.

    `threshold_fraction` is the gate that would: it forces `lo = 0.0`, so a binding
    carrying one turns a bidirectional command into an on/off one — and the training
    data would still look perfectly good, because the loss is downstream of the model.
    """
    values = app_module["POSES"].values()
    assert min(values) < 0.0 < max(values), f"the cues are one-way: {app_module['POSES']}"
    assert (app_module["POSE_VALUES"] < 0).any(), "the regression target has no low half"

    for alias, binding in app_module["CONTROL_MAP"].bindings.items():
        assert binding.threshold_fraction is None, f"{alias} is gated back to on/off"


def test_the_paddle_moves_with_no_bus_at_all(app_module, imgui_frame):
    """The architecture in one test: VHI is a mirror, never a dependency.

    `link.bus is None` is this app's *normal* state, so every step from the model to the
    court has to work through it. A paddle wired to the bus instead of to the prediction
    would pass every other test in this file and be a dead court on a machine with no
    Virtual Hand — which is most of them.
    """

    class Reg:
        def predict(self, x):
            return [-0.75]

    assert app_module["link"].bus is None, "the fixture bound a bus; this test is void"
    out = app_module["predict"](("Regression", Reg()), np.zeros(4))
    assert "controls" not in out, "pushed to a bus that does not exist"

    class Ctx:
        state = "predicting"

    app_module["pipeline"].predictions = out
    command = app_module["_command"](Ctx())
    assert command == pytest.approx(-0.75), "the prediction never reaches the paddle"

    # And the game takes it. `PongTask.ui` is the last link in the chain and the only
    # one a pure-arithmetic test cannot reach.
    imgui_frame(lambda: app_module["pong"].ui(command))


# --- the decoder, and the paddle it plays against -----------------------------
def _synthetic_windows(rng, n_per_class=8, channels=4, samples=64):
    """Three cued classes as EMG windows, separated by *where* the signal is.

    Down loads the low channels and Up the high ones, at the same overall loudness, so
    amplitude alone cannot tell them apart — which is the case `directional_decoder`
    exists for and the case a plain regressor gets wrong. Rest is the same shape at a
    tenth the amplitude, because a rest block that is *also* spatially different would
    let a broken fit pass on a cue it will never see live.
    """
    gains = {
        "Down": np.array([1.0, 1.0, 0.2, 0.2]),
        "Up": np.array([0.2, 0.2, 1.0, 1.0]),
        "Rest": np.full(channels, 0.1),
    }
    for name, gain in gains.items():
        for _ in range(n_per_class):
            noise = rng.standard_normal((channels, samples)).astype(np.float32)
            yield (noise * gain[:, None]).astype(np.float32), name


def test_the_default_mode_is_the_decoder(app_module):
    """Proportional is what a fresh launch trains, and the other two are still offered.

    The default matters more than it looks: the CatBoost regressor is non-monotonic in
    effort on real data — contract harder and its output *falls* — so an operator who
    never touches this switch must not be handed that. The other two stay because the
    example exists partly to let a reader feel the difference, and a one-mode switch
    would make that impossible.
    """
    modes = app_module["MODES"]
    assert modes[app_module["training_mode"]["index"]] == "Proportional"
    assert set(modes) == {"Proportional", "Regression", "Classification"}


def test_the_new_mode_is_also_taken_from_the_model(app_module):
    """The same invariant as above, in the direction the new mode added.

    `test_predict_uses_the_models_mode_not_the_switch` covers switch-says-regression
    with a classifier loaded. This is the other way round, and it is the one the third
    mode created: the switch says Classification while a *decoder* is driving. A live
    read would reach for `predict_proba`, which this estimator does not have, so the
    stub is the oracle — with a live read this raises AttributeError instead of
    quietly sending a class index to the court.
    """

    class OnlyPredict:
        """A decoder. Asking it for `.predict_proba` is the bug this stub detects."""

        def predict(self, x):
            return np.array([-0.5])

    app_module["training_mode"]["index"] = app_module["MODES"].index("Classification")
    app_module["output_filter"].reset()

    out = app_module["predict"](("Proportional", OnlyPredict()), np.zeros(8))

    assert out["paddle"] == pytest.approx(-0.5), f"wrong branch: {out}"
    assert out["class"] == app_module["CLASSES"].index("Down"), "the read-out disagrees"


def test_the_decoder_round_trips_from_train_to_the_paddle_and_the_bus(app_module, monkeypatch):
    """Train the default mode on cued windows and drive the court with what comes back.

    The one test that runs the real path end to end: `train` picks the estimator off the
    live switch and *binds the mode into the model*, `predict` reads that mode back, and
    one number reaches both consumers. It is also the only place the target encoding is
    checked against the decoder's contract — hand it `y` as class indices instead of
    `POSE_VALUES[y]` and `fit` raises, because indices have no negative half.

    `iter_labeled_windows` is patched through `train.__globals__` rather than on the
    module: `runpy` hands back a copy of the namespace, so patching the dict the fixture
    returned would leave the function still calling the real one.
    """
    windows = list(_synthetic_windows(np.random.default_rng(0)))
    classes = app_module["CLASSES"]
    monkeypatch.setitem(
        app_module["train"].__globals__,
        "iter_labeled_windows",
        lambda *a, **k: ((w, 0.0, classes.index(name)) for w, name in windows),
    )
    data = TrainingData(paths=["fake.session.zip"], class_names=classes, classes=set())

    mode, est = app_module["train"](data)
    assert mode == "Proportional", "the switch did not reach the model"
    # The label is not the estimator. Without this, renaming "Regression" to
    # "Proportional" and changing nothing else passes every assertion below — the
    # CatBoost regressor gets these separable windows right too, on 24 clean ones.
    assert isinstance(est, type(directional_decoder())), f"Proportional fitted a {type(est)}"

    # A held Up window, through the same `extract` training used — a second feature path
    # here would make this test pass while the shipped one diverged.
    up = next(w for w, name in windows if name == "Up")
    feats = app_module["extract"]({"emg": up})

    bus = Bus()
    app_module["output_filter"].reset()
    app_module["link"]._bus = bus
    try:
        out = app_module["predict"]((mode, est), feats)
    finally:
        app_module["link"]._bus = None

    assert out["paddle"] > 0.0, f"a trained Up window did not move the paddle up: {out}"
    (frame,) = bus.frames
    assert frame["paddle"] == out["paddle"], "the hand and the paddle diverged"

    # And the sign is genuinely decoded, not a constant: Down is the other way.
    down = next(w for w, name in windows if name == "Down")
    app_module["output_filter"].reset()
    other = app_module["predict"]((mode, est), app_module["extract"]({"emg": down}))
    assert other["paddle"] < 0.0, f"Down and Up land on the same side: {other}"


def test_proportional_refuses_a_feature_set_that_mixes_gain_degrees(app_module):
    """Ticking VAR next to RMS is one click and it silently breaks the headline promise.

    `directional_decoder` divides each feature row by its own sum, so an electrode gain
    only cancels when every column scales by the same power of it: RMS/MAV/WL by `g`,
    VAR by `g**2`, ZC not at all. Mixed, a hotter amplifier moves `direction` itself —
    contract harder, the paddle goes the wrong way, which is the failure the whole recipe
    is here to avoid. Refused at train time, where there is a subject to tell.
    """
    features = app_module["features"]
    data = TrainingData(paths=["fake.session.zip"], class_names=app_module["CLASSES"])
    features.set_active("VAR", True)
    try:
        with pytest.raises(ValueError, match="the same way"):
            app_module["train"](data)
        # Same set, a mode that normalises nothing: allowed through to the data check.
        app_module["training_mode"]["index"] = app_module["MODES"].index("Regression")
        with pytest.raises(ValueError, match="No sessions selected"):
            app_module["train"](TrainingData(paths=[], class_names=app_module["CLASSES"]))
    finally:
        features.set_active("VAR", False)
        app_module["training_mode"]["index"] = app_module["MODES"].index("Proportional")


def test_train_and_predict_share_one_feature_path(app_module):
    """Both go through `extract`, so a feature ticked off cannot change only one.

    Asserted on the source because the divergence is silent: `train` calling `features`
    directly would still fit, still predict, and still look healthy — right up to the
    moment someone unticks WL and the model is fed a vector of a different length, or
    worse, the same length in a different order.
    """
    source = inspect.getsource(app_module["train"])
    assert "extract({" in source, "training builds its own features"
    assert "features(" not in source, "training bypasses `extract`"


def test_the_app_plays_an_opponent_at_a_fair_setting(app_module):
    """A wall returns everything, so a rally against one can only ever be lost.

    The score says as much: against the wall it is the subject's own hits and misses,
    and there is no column in which they are ahead. An opponent is what makes the drill
    a game, so the app ships with one — and at Fair, not Hard, because a paddle that
    covers more court than the ball crosses in its flight time teaches nothing.

    `_opponent` is private and read here anyway: the widget offers no getter, and the
    alternative is not testing that the default arrived.
    """
    assert app_module["LEVELS"][app_module["opponent_level"]["index"]] == "Fair"
    assert app_module["pong"]._opponent == app_module["OPPONENTS"]["Fair"]


def test_every_difficulty_builds_a_playable_court(app_module, implot_frame):
    """`PongTask` rejects a non-positive `opponent`, so a preset typo is an import-time
    crash for whoever picks that level — and only that level, which is how it ships.

    Drawn as well as built: the opponent's paddle is the one thing on the court that
    only renders when there *is* an opponent, so a level that constructs but does not
    draw would otherwise pass.
    """
    for index, name in enumerate(app_module["LEVELS"]):
        app_module["opponent_level"]["index"] = index
        game = app_module["_new_game"]()
        assert game._opponent == app_module["OPPONENTS"][name], name
        implot_frame(lambda game=game: game.ui(0.3))


# --- the pursuit block, and the two kinds of session it makes -----------------
#: Short enough to build in a test, long enough to have real rest at exactly 0.0 and
#: dense intermediate levels — which is the entire difference being tested for.
_BLOCK = Pursuit(rest_s=2.0, hop_s=1.0, hops=12, recover_s=2.0)
#: The two spatial patterns `_synthetic_windows` uses, as a function of level: Down
#: loads the low channels, Up the high ones, and loudness follows ``abs(level)``.
_DOWN = np.array([1.0, 1.0, 0.2, 0.2])
_UP = np.array([0.2, 0.2, 1.0, 1.0])


def _emg_for(levels: np.ndarray, rng) -> np.ndarray:
    """EMG whose *shape* carries the sign and whose loudness carries the effort.

    Samples-first ``(n, 4)``, the layout a `Session` stores. Amplitude alone cannot say
    which way the wrist went, which is the case `directional_decoder` exists for; the
    ``0.1`` floor is the baseline that keeps a rest sample from being all zeros.
    """
    gains = np.where(levels[:, None] < 0.0, _DOWN, _UP) * (0.1 + np.abs(levels)[:, None])
    return (rng.standard_normal((len(levels), 4)) * gains).astype(np.float32)


def _pursuit_session(base: str, *, fs: float = 500.0, target_fs: float = 20.0) -> str:
    """A followed-cursor session: EMG, a recorded `target` stream, and **no labels**.

    No labels on purpose. It is what makes the auto-detection falsifiable — route this
    session to `iter_labeled_windows` and it yields nothing at all, so a `train` that
    ignores the target stream fails loudly here instead of quietly training on a third
    of the data.
    """
    rng = np.random.default_rng(3)
    emg_ts = np.arange(int(_BLOCK.total_duration * fs)) / fs
    target_ts = np.arange(int(_BLOCK.total_duration * target_fs)) / target_fs

    target = np.empty((len(target_ts), 2), dtype=np.float32)
    for i, t in enumerate(target_ts):
        target[i] = (_BLOCK.value_at(float(t)), PHASE_CODES[_BLOCK.phase_at(float(t))])
    emg = _emg_for(np.array([_BLOCK.value_at(float(t)) for t in emg_ts]), rng)

    session = Session(base_path=base)
    session.init_stream("emg", StreamInfo(n_channels=4, fs=fs, dtype=np.dtype("float32")))
    session.append("emg", emg, emg_ts)
    session.init_stream(
        "target",
        StreamInfo(
            n_channels=2,
            fs=target_fs,
            dtype=np.dtype("float32"),
            channel_names=["target_pct", "phase"],
        ),
    )
    session.append("target", target, target_ts)
    session.save_meta("PongPursuit")
    return str(session.pack_to_zip())


def _cued_session(base: str, classes: list[str], *, fs: float = 500.0, hold_s: float = 3.0) -> str:
    """A three-class cued session: EMG, a label track, and **no target stream**.

    The mirror of `_pursuit_session`, and falsifiable the same way — `iter_target_windows`
    *raises* on a session missing its target rather than skipping it, so a `train` that
    sends everything down the continuous path dies here.
    """
    rng = np.random.default_rng(4)
    per = int(hold_s * fs)
    levels = np.concatenate(
        [np.full(per, {"Down": -1.0, "Rest": 0.0, "Up": 1.0}[name]) for name in classes]
    )
    ts = np.arange(len(levels)) / fs

    session = Session(base_path=base)
    session.init_stream("emg", StreamInfo(n_channels=4, fs=fs, dtype=np.dtype("float32")))
    session.append("emg", _emg_for(levels, rng), ts)
    for i, name in enumerate(classes):
        session.add_label(classes.index(name), timestamp=float(ts[i * per]))
    session.save_meta("PongCued")
    return str(session.pack_to_zip())


class Recorder:
    """Stands in for the estimator, so the *targets* `train` built can be read back."""

    def __init__(self) -> None:
        self.x: np.ndarray | None = None
        self.y: np.ndarray | None = None

    def fit(self, x, y):
        self.x, self.y = np.asarray(x), np.asarray(y)


def _targets_from_training(app_module, monkeypatch, paths) -> np.ndarray:
    """Train Proportional on `paths` against a `Recorder`, and hand back the targets.

    Patched through `train.__globals__` for the reason the file docstring gives: `runpy`
    returns a copy of the namespace, so patching the dict would leave `train` calling the
    real recipe. A recorder rather than a real fit because what is under test is which
    iterator each session went through, and a CatBoost is a slow way not to answer that.
    """
    est = Recorder()
    monkeypatch.setitem(app_module["train"].__globals__, "directional_decoder", lambda: est)
    data = TrainingData(paths=list(paths), class_names=app_module["CLASSES"], classes=set())
    mode, returned = app_module["train"](data)
    assert (mode, returned) == ("Proportional", est)
    assert est.y is not None, "train fitted nothing"
    return est.y


def test_a_pursuit_session_trains_on_the_cursor_it_recorded(app_module, monkeypatch, tmp_path):
    """The continuous path: targets come off the recorded cursor, not off a label track.

    The three assertions are the three things a cued block cannot give and the reason
    this protocol exists at all: **many** distinct levels rather than three, genuine
    *intermediate* effort, and a rest that is still exactly zero so the decoder keeps
    somewhere to put its baseline. A tree ensemble's output is an average of the targets
    it was trained on, so a level the block never asked for is a level it can never
    emit — which is how a three-class regressor ends up non-monotonic in effort.
    """
    y = _targets_from_training(app_module, monkeypatch, [_pursuit_session(str(tmp_path))])

    assert len(np.unique(y)) > 20, f"the cursor collapsed to {sorted(set(y.tolist()))}"
    assert np.abs(y).max() <= 1.0, "the cursor left the signed control range"
    mid = np.abs(y)[(np.abs(y) > 0.1) & (np.abs(y) < 0.9)]
    assert len(mid) > 20, "no intermediate effort — this is a three-class block in disguise"
    assert (y == 0.0).any(), "the rest segments did not survive as an exact zero"


def test_a_cued_session_still_trains_through_the_label_path(app_module, monkeypatch, tmp_path):
    """Recordings made before the cursor existed have to keep training, unchanged.

    `iter_target_windows` raises on a session with no target stream rather than skipping
    it, so "everything goes down the continuous path" is not a silent regression here —
    but it would still be a broken app for every session already on disk.
    """
    path = _cued_session(str(tmp_path), app_module["CLASSES"] * 2)
    y = _targets_from_training(app_module, monkeypatch, [path])

    assert set(y.tolist()) == set(app_module["POSE_VALUES"].tolist()), (
        f"a cued block produced {sorted(set(y.tolist()))}, not the pose table"
    )


def test_the_kind_is_detected_per_session_so_a_mixed_selection_trains_on_the_union(
    app_module, monkeypatch, tmp_path
):
    """Auto-detection, and the reason it is per session rather than a switch.

    A selection holding one of each has to train on both — the targets are in the same
    signed units by construction (see the test below, which checks that rather than
    assuming it), so the union is a strictly better training set than either half. A
    switch would make the operator pick one, and picking wrong is silent.

    The log line is asserted too, and it is asserted in `ctx.logs` rather than on stdout
    because that is the only one an operator can see — `LogPanel` renders `ctx.logs` and
    nothing in `Pipeline` captures a `print`. "Trained on 231 windows" over a mixed
    selection hides the failure this whole mechanism has: a session that contributed
    *nothing* because its stream is named something else looks exactly like one that
    contributed well.
    """
    pursuit = _pursuit_session(str(tmp_path / "a"))
    cued = _cued_session(str(tmp_path / "b"), app_module["CLASSES"] * 2)

    y = _targets_from_training(app_module, monkeypatch, [pursuit, cued])

    poses = set(app_module["POSE_VALUES"].tolist())
    assert poses <= set(y.tolist()), "the cued session's levels are missing from the union"
    assert len(np.unique(y)) > 20, "the pursuit session's levels are missing from the union"
    assert np.abs(y).max() <= 1.0, "the union left the signed control range"

    line = next(entry for entry in app_module["app"].ctx.logs if "[train]" in entry)
    assert "pursuit," in line and "cued," in line, f"the log does not name the kinds: {line}"
    assert Path(pursuit).name in line and Path(cued).name in line, (
        f"the log does not name each session: {line}"
    )
    assert " 0 windows" not in line, f"a session contributed nothing and said so: {line}"


def test_the_two_protocols_are_recorded_in_the_same_units(app_module, tmp_path):
    """The claim the union rests on, checked rather than asserted in a comment.

    `Pursuit` is signed, normalised control units and `POSES` is the same scale read at
    three points — so a cued window and a pursuit window mean the same thing by the value
    alone, with nothing to rescale between them. What would break it is either side
    drifting: a `Pursuit` in percent of MVC, or a pose table in degrees.

    Checked on what a *session* holds, not on the classes, because the recording is where
    the two actually meet. `TargetSource` streams the trajectory verbatim — its own
    docstring says the level channel carries whatever unit the trajectory works in — so
    the round trip through the recording is part of the claim.
    """
    from myogestic.session import iter_target_windows

    recorded = np.array(
        [
            value
            for _w, _ts, value in iter_target_windows(
                [_pursuit_session(str(tmp_path))], "emg", "target", 200, 100
            )
        ]
    )
    poses = app_module["POSE_VALUES"]

    assert np.abs(recorded).max() <= 1.0, "the recorded cursor is not in [-1, +1]"
    assert recorded.min() < 0.0 < recorded.max(), "the recorded cursor is one-way"
    # The cues are the endpoints and the shared zero of the range the cursor sweeps —
    # the same axis sampled at three points, which is what makes the union legitimate.
    assert float(poses.min()) == pytest.approx(-1.0)
    assert float(poses.max()) == pytest.approx(1.0)
    assert 0.0 in set(poses.tolist()), "the two protocols do not share a rest"
    assert np.abs(recorded).min() == pytest.approx(0.0, abs=1e-6), (
        "the cursor never rests, so its zero is not the cues' zero"
    )


def test_a_pursuit_session_fits_the_real_decoder_end_to_end(app_module, monkeypatch, tmp_path):
    """One test with nothing stubbed between the recording and the paddle.

    The recorders above answer "which iterator", which is the wiring question. This
    answers the one they cannot: that what `iter_target_windows` hands back is something
    `directional_decoder` will actually accept — it has a real input contract now (a
    signed target with a rest block, and at least three windows past half deflection),
    and continuous targets satisfy it differently from a cued block's ``{-1, 0, +1}``.
    """
    monkeypatch.setitem(
        app_module["train"].__globals__, "catboost_regressor", None  # unused; fails loudly
    )
    data = TrainingData(
        paths=[_pursuit_session(str(tmp_path))],
        class_names=app_module["CLASSES"],
        classes=set(),
    )
    mode, est = app_module["train"](data)
    assert mode == "Proportional"
    assert isinstance(est, type(directional_decoder())), f"Proportional fitted a {type(est)}"

    rng = np.random.default_rng(9)
    up = app_module["extract"]({"emg": _emg_for(np.full(100, 1.0), rng).T})
    app_module["output_filter"].reset()
    assert app_module["predict"]((mode, est), up)["paddle"] > 0.0, "a full Up did not move up"

    down = app_module["extract"]({"emg": _emg_for(np.full(100, -1.0), rng).T})
    app_module["output_filter"].reset()
    assert app_module["predict"]((mode, est), down)["paddle"] < 0.0, "Down landed on the Up side"


# --- the block press, the ghost, and the control switch -----------------------
def test_the_block_connects_the_cursor_before_it_opens_the_take(app_module, monkeypatch):
    """One press does all three, and the order is the part that is easy to get wrong.

    `App.start_recording` sizes one array per *attached* stream, so a cursor stream
    connected a moment later is simply not in the session — and every read-out still
    looks healthy, right up to the training run that finds no target and silently falls
    back to the label path. Connect, then record, then run.
    """
    order: list[str] = []
    monkeypatch.setattr(
        myogestic.stream.Stream,
        "reconnect",
        lambda self, *a, **k: (order.append(f"connect:{self.name}"), True)[1],
    )
    monkeypatch.setattr(
        myogestic.core.App, "start_recording", lambda self, *a, **k: order.append("record")
    )
    monkeypatch.setattr(myogestic.core.App, "stop_recording", lambda self: order.append("stop"))

    app_module["_start_block"]()
    assert order == ["connect:target", "record"], f"wrong order: {order}"
    assert app_module["target"].running, "the press did not start the block"

    app_module["_end_block"]()
    assert order == ["connect:target", "record", "stop"]
    assert not app_module["target"].running


def test_the_block_closes_only_the_take_it_opened(app_module, monkeypatch):
    """An operator recording by hand keeps their take when the cursor reaches its end.

    `TargetSource` ends its own block on the acquire thread, and `pong_ui` notices. If
    that noticing called `stop_recording` unconditionally it would cut short a recording
    this app never started — a long free-play take ended by a block nobody was in.
    """
    stopped: list[str] = []
    monkeypatch.setattr(myogestic.core.App, "stop_recording", lambda self: stopped.append("stop"))

    app_module["target"].start()  # the block, without the press that owns the recording
    app_module["target"].stop()
    app_module["_end_block"]()
    assert stopped == [], "stopped a recording this app did not start"


def test_the_ghost_is_driven_only_while_a_block_runs(app_module, monkeypatch, implot_frame):
    """The cursor reaches the court, and only then — asserted at `PongTask.ui` itself.

    `_cursor` returning the right float proves nothing on its own: the ghost is an
    argument to a widget call two functions away, and the failure that matters is the
    app forgetting to pass it. Outside a block it must be `None` rather than ``0.0``,
    which is a real distinction — a ghost parked at centre court is a target the subject
    would try to hold.
    """
    seen: list[float | None] = []
    monkeypatch.setattr(
        type(app_module["pong"]), "ui", lambda self, command, target=None: seen.append(target)
    )
    ctx = app_module["app"].ctx

    implot_frame(lambda: app_module["pong_ui"](ctx))
    assert seen == [None], f"a ghost with no block running: {seen}"

    target = app_module["target"]
    target.start()
    # Task time is normally advanced by the acquire thread out of each emitted chunk;
    # this test is about the path from there to the court, not about the source.
    target._elapsed = app_module["PURSUIT"].rest_s + app_module["PURSUIT"].hop_s * 1.5
    implot_frame(lambda: app_module["pong_ui"](ctx))

    expected = app_module["PURSUIT"].value_at(target._elapsed)
    assert seen[1] == pytest.approx(expected), f"the court got {seen[1]}, cursor is at {expected}"
    assert seen[1] != 0.0, "the fixture picked a moment the cursor is resting at; pick another"

    target.stop()
    implot_frame(lambda: app_module["pong_ui"](ctx))
    assert seen[2] is None, f"the ghost outlived the block: {seen[2]}"


def test_the_control_switch_reaches_the_court(app_module, implot_frame):
    """Velocity by default, position on request, and both draw.

    The default is read off `PongTask` rather than written down again: "defaults as the
    widget does" is the requirement, and a second copy of the answer is a second thing
    to forget. Velocity matters here beyond taste — under position a model with three
    outputs can only put the paddle in three places, so the classification mode this app
    still offers would be unplayable.
    """
    controls = app_module["CONTROLS"]
    widget_default = inspect.signature(PongTask.__init__).parameters["control"].default
    assert controls[app_module["control_mode"]["index"]].lower() == widget_default

    drawn: dict[str, int] = {}

    def draw(game, ghost, key) -> None:
        """One court into a child window, counting what it put on the draw list."""
        imgui.begin_child("cell", imgui.ImVec2(600, 400))
        before = imgui.get_window_draw_list().vtx_buffer.size()
        game.ui(0.3, ghost)
        drawn[key] = imgui.get_window_draw_list().vtx_buffer.size() - before
        imgui.end_child()

    for index, name in enumerate(controls):
        app_module["control_mode"]["index"] = index
        game = app_module["_new_game"]()
        assert game._control == name.lower(), name
        # Counting the draw list is all a headless frame can see of "it rendered", and
        # it is the check `tests/test_pong_task.py` uses on the marker itself. Here it
        # is the *app's* court, built by `_new_game`, so what it adds is that the mode
        # this switch chose still draws a court and still takes a ghost.
        implot_frame(lambda game=game, name=name: draw(game, None, f"{name}:bare"))
        implot_frame(lambda game=game, name=name: draw(game, 0.6, f"{name}:ghost"))
        assert drawn[f"{name}:bare"] > 0, f"{name} drew no court at all"
        assert drawn[f"{name}:ghost"] > drawn[f"{name}:bare"], f"{name} drew no ghost"


# --- what "carries a target stream" does and does not mean --------------------
def _idle_target(duration: float, *, target_fs: float = 20.0) -> tuple[np.ndarray, np.ndarray]:
    """Exactly what `TargetSource.read` emits with no block running: baseline and `idle`.

    Verified against the source rather than guessed at — `stop()` leaves the stream
    attached and emitting, which is the whole reason a cued take inherits one.
    """
    ts = np.arange(int(duration * target_fs)) / target_fs
    rows = np.zeros((len(ts), 2), dtype=np.float32)
    rows[:, 1] = PHASE_CODES["idle"]
    return rows, ts


def _add_target(path: str, rows: np.ndarray, ts: np.ndarray, *, target_fs: float = 20.0) -> str:
    """Rewrite a session with a `target` stream bolted on, as a `.session.zip`."""
    from myogestic.session import open_session_store

    source = open_session_store(path)
    try:
        emg, emg_ts = np.array(source.stores["emg"]), np.array(source.ts_stores["emg"])
        info, labels = source.stream_info("emg"), list(source.label_track)
    finally:
        source.close()

    session = Session(base_path=str(Path(path).parent / "rewritten"))
    session.init_stream("emg", info)
    session.append("emg", emg, emg_ts)
    session.init_stream(
        "target",
        StreamInfo(
            n_channels=2,
            fs=target_fs,
            dtype=np.dtype("float32"),
            channel_names=["target_pct", "phase"],
        ),
    )
    if len(ts):
        session.append("target", rows, ts)
    for event in labels:
        session.add_label(event.class_index, timestamp=float(event.timestamp))
    session.save_meta("PongRewritten")
    return str(session.pack_to_zip())


def test_a_cued_take_that_inherited_an_idle_target_stream_still_trains_on_its_labels(
    app_module, monkeypatch, tmp_path
):
    """`_end_block` stops the task and leaves the *stream* attached — by design.

    So every cued take recorded after a pursuit block carries a `target` stream full of
    `idle`, `split_sessions_by_stream` puts it in `with_stream`, and `iter_target_windows`
    correctly drops every window of it because `idle` is not a followed phase. Routing on
    presence alone therefore threw the session away with its label track unread, and said
    so only on stdout. The target path is the preferred reading, not the other branch of
    an either/or.
    """
    cued = _cued_session(str(tmp_path / "b"), app_module["CLASSES"] * 2)
    rows, ts = _idle_target(9.0)
    inherited = _add_target(cued, rows, ts)

    from myogestic.session import split_sessions_by_stream

    assert split_sessions_by_stream([inherited], "target").with_stream == [inherited], (
        "the premise moved: this session no longer looks like a pursuit block"
    )

    y = _targets_from_training(app_module, monkeypatch, [inherited])
    assert set(app_module["POSE_VALUES"].tolist()) <= set(y.tolist()), (
        "the label track was never read — the idle target stream ate the session"
    )
    assert any("cued," in entry for entry in app_module["app"].ctx.logs), (
        "the operator was not told which path the session took"
    )


def test_one_empty_target_stream_does_not_throw_away_every_other_session(
    app_module, monkeypatch, tmp_path
):
    """A recording stopped inside the source's 100 ms chunk leaves it present and empty.

    `App.start_recording` calls `init_stream` for every attached stream, so the session
    holds a `target` with zero rows; `iter_target_windows` raises on it, by design, since
    it cannot invent a target. What must not follow is the whole selection dying with it —
    `train` already goes out of its way to keep one unreadable session from killing the
    run, and one mis-pressed take is the same class of accident.
    """
    stray = _add_target(
        _cued_session(str(tmp_path / "c"), app_module["CLASSES"]), np.empty((0, 2)), np.empty(0)
    )
    good = _pursuit_session(str(tmp_path / "a"))

    y = _targets_from_training(app_module, monkeypatch, [good, stray])

    assert len(np.unique(y)) > 20, "the good session's windows went down with the stray one"
    assert any("unusable" in entry for entry in app_module["app"].ctx.logs), (
        "the stray session was dropped without saying so"
    )


def test_a_force_ramp_session_is_refused_by_name_rather_than_trained_on(
    app_module, monkeypatch, tmp_path
):
    """The other recorded-target protocol writes the same stream in percent of MVC.

    `force_ramps.py` records a `Trapezoid` through the same `TargetSource`, under the same
    stream name, with the identical channel names, into the same `sessions/` folder. A
    `StreamInfo` carries no unit, so nothing in the recording distinguishes it — and
    ticked beside a cursor session its 0..100 column collapsed `directional_decoder`'s
    `span_` from 4.17 to 0.046, turning a graded transfer curve into a hard three-step
    staircase with every one of that recipe's own guards passing.
    """
    from myogestic.tracking import Trapezoid

    ramp = Trapezoid(rest_s=2.0, ramp_up_s=3.0, hold_s=4.0, ramp_down_s=3.0, recover_s=2.0)
    ts = np.arange(int(ramp.total_duration * 20.0)) / 20.0
    rows = np.array(
        [(ramp.value_at(float(t)), PHASE_CODES[ramp.phase_at(float(t))]) for t in ts],
        dtype=np.float32,
    )
    assert rows[:, 0].max() > 1.0, "the fixture is not in percent of MVC"
    force = _add_target(_cued_session(str(tmp_path / "f"), app_module["CLASSES"]), rows, ts)

    data = TrainingData(
        paths=[_pursuit_session(str(tmp_path / "a")), force],
        class_names=app_module["CLASSES"],
        classes=set(),
    )
    with pytest.raises(ValueError, match=r"\[-1, \+1\]") as raised:
        app_module["train"](data)
    assert Path(force).name in str(raised.value), "the operator is not told which file to untick"
