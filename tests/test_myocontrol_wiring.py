"""What `examples/start_here/myocontrol.py` claims on a fresh launch.

The load-bearing one is `test_predict_uses_the_models_mode_not_the_switch`. Everything
else here is a smoke check; that one pins a design decision that a plausible-looking
one-line edit would undo, and it fails loudly when it does.
"""

import inspect
import runpy
from pathlib import Path

import numpy as np
import pytest

import myogestic.core
import myogestic.remote
import myogestic.stream
from myogestic.controls import ControlLink

_APP = Path(__file__).resolve().parent.parent / "examples" / "start_here" / "myocontrol.py"


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
        return np.array([[0.1, 0.9]])


def test_nothing_attaches_itself(monkeypatch):
    """"Nothing attaches on its own" is the project's rule, and unlike force_ramps this
    app has no task target to except — so nothing may even *try* to connect.

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
    *index* down the regression branch — the hand snaps to full flexion and nothing
    raises. The stub has no `.predict`, so a live read fails here with AttributeError
    instead of shipping.
    """
    app_module["training_mode"]["index"] = app_module["MODES"].index("Regression")

    out = app_module["predict"](("Classification", OnlyPredictProba()), np.zeros(4))

    assert "class" in out, f"predict took the wrong branch: {out}"
    assert out["class"] == app_module["CLASSES"].index("Fist")


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
    """A layout pass only ever draws a tab bar's *first* tab, so neither of these is
    reached by `test_example_draws_a_frame` — the drawing crashes live in there."""
    implot_frame(app_module["model_ui"])
    implot_frame(app_module["hand_ui"])


def test_the_map_declares_exactly_what_the_app_pushes(app_module):
    """Every alias in the map is driven, and every alias pushed is declared.

    An alias the app never sends is a row in the Hand panel that never moves — the
    operator sees a control and cannot tell whether it is broken or simply unused. The
    other direction is worse: `push` silently drops a key the `ControlSet` does not
    declare, so a typo'd alias is a hand that never moves and a log that says nothing.
    """
    import numpy as np

    pushed: list[dict] = []

    class Bus:
        def push(self, values):
            pushed.append(dict(values))
            return values

    class Clf:
        def predict_proba(self, x):
            return np.array([[0.1, 0.9]])

    app_module["link"]._bus = Bus()
    try:
        app_module["predict"](("Classification", Clf()), np.zeros(4))
    finally:
        app_module["link"]._bus = None

    declared = set(app_module["CONTROL_MAP"].bindings)
    assert pushed and set(pushed[0]) == declared, (
        f"pushed {set(pushed[0]) if pushed else set()} but the map declares {declared}"
    )
    # Both hands are commanded every frame. Omit either and `push` rests it — the
    # control hand would drop a frame after it was set, and the prediction hand would
    # twitch to rest on every button press.
    assert declared == {"prediction", "control"}
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


# --- classification is regression that emits a constant -----------------------
def test_a_class_is_a_pose_and_goes_out_on_the_same_aliases(app_module):
    """The two modes differ in where the numbers come from, not in what is sent.

    A classifier picks a row of `POSES`; a regressor computes one. Both reach the bus as
    the same continuous aliases, in the same units — which is why one control map serves
    both and nothing downstream has to know which mode is running.
    """
    import numpy as np

    sent: list[dict] = []

    class Bus:
        def push(self, values):
            sent.append(dict(values))
            return values

    class Clf:
        def predict_proba(self, x):
            return np.array([[0.1, 0.9]])  # -> "Fist"

    class Reg:
        def predict(self, x):
            return [0.62]

    app_module["link"]._bus = Bus()
    try:
        app_module["predict"](("Classification", Clf()), np.zeros(4))
        app_module["predict"](("Regression", Reg()), np.zeros(4))
    finally:
        app_module["link"]._bus = None

    assert len(sent) == 2
    classified, regressed = sent
    assert set(classified) == set(regressed), "the modes push different aliases"
    assert classified["prediction"] == app_module["POSES"]["Fist"]
    assert regressed["prediction"] == pytest.approx(0.62)


def test_every_class_has_a_pose(app_module):
    """A class with no pose pushes an all-rest frame and reads as a model that never
    fires — a silence, not an error. The module asserts it at import; this pins that the
    assert exists rather than that it happens to pass today."""
    assert set(app_module["POSES"]) == set(app_module["CLASSES"])


def test_the_cue_survives_a_prediction_that_disagrees_with_it(app_module):
    """The two hands are allowed to disagree — that disagreement is the point.

    The operator selects Fist; the model, mid-training or simply wrong, says Rest. The
    prediction hand must open while the control hand stays closed. Leaving `control` out
    of the predict frame rests it instead, so it drops 31 ms after it is set and the
    button reads as doing nothing.
    """
    import numpy as np

    sent: list[dict] = []

    class Bus:
        def push(self, values):
            sent.append(dict(values))
            return values

    class SaysRest:
        def predict_proba(self, x):
            return np.array([[0.9, 0.1]])

    app_module["link"]._bus = Bus()
    try:
        app_module["_on_control"](app_module["CLASSES"].index("Fist"))
        app_module["predict"](("Classification", SaysRest()), np.zeros(4))
    finally:
        app_module["link"]._bus = None

    # One frame, from `predict`. The click only remembers: a push there would complete
    # the frame with `prediction` at rest and twitch the other hand on every press.
    (predicted,) = sent
    assert predicted["control"] == app_module["POSES"]["Fist"], "the predict frame rested it"
    assert predicted["prediction"] == app_module["POSES"]["Rest"]


def test_the_ui_streams_the_frame_while_the_predict_loop_is_not(app_module):
    """VHI drops a control pose whose streams go quiet, so a command has to be sustained.

    `ControlHandSkeleton._Process` follows the pose only while `ControlPoseLive` — five
    seconds since the last sample — and on the falling edge calls `StopToRest()`, giving
    the rig back to its own movement animation. Fire once and the hand closes, then opens
    again five seconds later. The predict loop is that producer while predicting; the
    class buttons are used while *recording*, when it is not running, so the UI has to be.

    Not the same question as whether the outlet repeats its last value — it does, forever.
    That keeps a value on the wire, while VHI's liveness test is on samples *arriving*.
    Conflating the two is what made this take so long to find.

    Asserted on the source: the push sits at the tail of `@app.ui`, and reaching it in a
    layout pass would mean standing up the whole grid.
    """
    source = inspect.getsource(app_module["myocontrol_ui"])

    assert "bus.push" in source, "nothing drives the hands while recording"
    assert 'ctx.state != "predicting"' in source, (
        "the UI would drive the same outlets as the predict loop, at a different rate"
    )


def test_train_refuses_a_take_conditioned_differently_from_the_switch(app_module, tmp_path):
    """Fitting on unfiltered signal and predicting through a notch is silent and fatal.

    The notch conditions acquisition, so a filtered session holds filtered samples and
    nothing in the arrays says so. Train on raw takes with SIGNAL set to 50 Hz and the
    model meets an input distribution it never saw, while every read-out stays healthy —
    the same shape of bug as concatenating %MVC targets with signed control units.
    """

    from myogestic import TrainingData
    from myogestic.session import Session
    from myogestic.stream import StreamInfo

    def _take(notch_hz: int | None) -> str:
        sess = Session(base_path=str(tmp_path))
        sess.init_stream("emg", StreamInfo(n_channels=2, fs=100.0, dtype=np.dtype("float32")))
        sess.append("emg", np.zeros((50, 2), dtype=np.float32), np.arange(50) / 100.0)
        sess.add_label(0.0, 0)
        if notch_hz is not None:
            sess.extras["conditioning"] = {"emg": {"notch_hz": notch_hz}}
        sess.save_meta("test", ["Rest", "Fist"])
        sess.close()
        return str(sess.path)

    raw, filtered = _take(None), _take(50)
    notch = app_module["notch"]
    train = app_module["train"]

    notch["index"] = app_module["NOTCH_HZ"].index(50)  # SIGNAL says 50 Hz
    with pytest.raises(ValueError, match="recorded with notch"):
        train(TrainingData(paths=[raw], classes=set()))

    notch["index"] = 0  # SIGNAL says off
    with pytest.raises(ValueError, match="recorded with notch"):
        train(TrainingData(paths=[filtered], classes=set()))

    # And a matched pair gets past the guard — it fails later, on having no windows,
    # which is a different error and proves the guard is not simply refusing everything.
    notch["index"] = app_module["NOTCH_HZ"].index(50)
    with pytest.raises(ValueError) as excinfo:
        train(TrainingData(paths=[filtered], classes=set()))
    assert "recorded with notch" not in str(excinfo.value), str(excinfo.value)
