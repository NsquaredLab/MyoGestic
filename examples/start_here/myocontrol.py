"""Myocontrol: pick a device, record labelled trials, train, drive the Virtual Hand.

Classification or regression — the switch in the Model tab chooses what the *next*
Train builds, and the mode is bound into the model it returns.

Run with:
    uv run --extra examples --extra grpc python examples/start_here/myocontrol.py
"""

import pathlib
import tomllib
from typing import Any

import numpy as np
from imgui_bundle import imgui

from myogestic import App, Fr, Grid, Stream, TrainingData
from myogestic.controls import ControlBus, ControlLink, ControlLinkConnector, load_control_map
from myogestic.ml import Pipeline
from myogestic.ml.widgets import PipelinePanel
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

app = App("MyoGestic — myocontrol", ui_scale=0.85)
app.streams(Stream("emg", source=DEFAULT_DEVICES[0].factory(), window_ms=WINDOW_MS))
pipeline = Pipeline(app, predict_hz=PREDICT_HZ)
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
                f"SIGNAL is set to {want or 'off'}. Match the setting to the take, or "
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


grid = Grid(6, 3, row_height=[Fr(1)] * 6, col_width=[Fr(1), Fr(1), Fr(1)])

# No `exclude`: every stream here is a device stream.
device = DevicePicker("emg", selectable=True)
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
# `launchable`, never `launcher`: a VHI that cannot be launched must not stop this app
# from opening, and one already running needs no button.
processes = ProcessLauncher(vhi.launchable())
# VHI takes seconds to boot and `ensure()` blocks, so this retries in the background —
# rate-limited and single-flight, safe to poll every frame.
binder = ControlLinkConnector(link)
sessions = SessionManager("sessions", class_names=CLASSES)
panel = PipelinePanel(pipeline)
prediction = PredictionLabel(pipeline, CLASSES, show_probability=True)


#: What drives each alias here. The map says where a value goes, not what sends one.
ALIAS_ROLES = {
    "prediction": "the model, every predict tick",
    "control": "the Rest / Fist buttons",
}
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


def _on_control(index: int) -> None:
    """Put the selected class on the control hand.

    Remembering is the whole job: the frame that carries it is sent by `myocontrol_ui`
    while recording, and by the predict loop while predicting. Pushing here too would
    only add a frame in which `prediction` is completed to rest, twitching the other hand
    on every class press.

    It does bind, though. A UI handler is where that is affordable — `predict` must never
    call it — and binding on first press is what lets the buttons work without visiting
    the Hand tab.
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
    """Model tab: what the next Train builds, and what the current model is doing."""
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

    # Beside FEATURES: the same kind of decision, what the model is fed.
    panel_header("SIGNAL")
    notch["index"] = segmented("notch", NOTCH_CHOICES, notch["index"])
    stream = app.ctx.streams.get("emg")
    if stream is not None:
        stream.notch_hz = NOTCH_HZ[notch["index"]]
    imgui.text_disabled("mains notch on the recorded and modelled signal")
    imgui.spacing()

    features.ui()
    panel.ui()
    output_filter.ui()
    prediction.ui()
    # A read-out, not a progress bar: `fist` resolves to [-1, 1] and a bar would clamp
    # the negative half away without saying so.
    panel_header("PUSHED")
    mono_text(_pushed())


def hand_ui() -> None:
    """Hand tab: launch VHI, and bind to it once it answers.

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
    imgui.same_line()
    imgui.text_disabled("Launch VHI above, or bind to one already running.")


@app.ui
def myocontrol_ui(ctx):
    with grid[0:5, 0:2]:
        if imgui.begin_tab_bar("signal_cell"):
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

    # Stream it, do not fire it once: VHI holds a pose only while samples keep arriving
    # (5 s, then `StopToRest()`). While predicting the predict loop is already doing that.
    bus = link.bus
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
