"""Tests for myogestic.widgets.panels.recording.

Tests the pure-logic helpers — full widget rendering needs ImGui context.
"""

import pytest

from myogestic.widgets.panels.recording import _safe_label_index


@pytest.fixture
def timed_controls():
    from types import SimpleNamespace

    from myogestic.core import Context
    from myogestic.widgets.panels import recording

    now, calls, labels = [0.0], [], []
    ctx = Context(participant="P-014", current_label=1)
    ctx.streams["emg"] = SimpleNamespace(status="connected", info=object())

    def start():
        calls.append("record")
        ctx.state = "recording"
        ctx.recording = True
        ctx.session = SimpleNamespace(add_label=labels.append)

    def stop():
        calls.append("stop")
        ctx.state = "idle"
        ctx.recording = False

    controls = recording.RecordingControls(
        ["Rest", "Fist"],
        on_record=start,
        on_stop=stop,
        take_lengths=(3.0, 5.0, 10.0),
        warmups=(0.0, 1.0, 2.0, 3.0),
        timed=True,
        take_length=5.0,
        warmup=2.0,
    )
    controls._machine._clock = lambda: now[0]
    return controls, ctx, now, calls, labels


@pytest.mark.parametrize("options", [{}, {"take_length": None, "warmup": None}])
def test_initial_timing_defaults_to_first_choices_and_start_stop(options):
    from myogestic.widgets import RecordingControls

    controls = RecordingControls(
        on_record=lambda: None,
        on_stop=lambda: None,
        take_lengths=(3.0, 5.0, 10.0),
        warmups=(0.0, 1.0, 2.0, 3.0),
        **options,
    )
    assert controls._timed is False
    assert controls._take_lengths[controls._length_index] == 3.0
    assert controls._warmups[controls._warmup_index] == 0.0


def test_initial_timing_without_take_lengths_is_start_stop():
    from myogestic.widgets import RecordingControls

    controls = RecordingControls(on_record=lambda: None, on_stop=lambda: None)
    assert controls._timed is False
    assert controls._take_lengths == ()
    assert controls._warmups[controls._warmup_index] == 0.0


@pytest.mark.parametrize("take_length,warmup", [(10.0, 3.0), (3.0, 0.0), (5.0, 2.0)])
def test_initial_timing_selects_explicit_choices(take_length, warmup):
    from myogestic.widgets import RecordingControls

    controls = RecordingControls(
        on_record=lambda: None,
        on_stop=lambda: None,
        take_lengths=(3.0, 5.0, 10.0),
        warmups=(0.0, 1.0, 2.0, 3.0),
        take_length=take_length,
        warmup=warmup,
    )
    assert controls._timed is False
    assert controls._take_lengths[controls._length_index] == take_length
    assert controls._warmups[controls._warmup_index] == warmup


def test_initial_timed_mode_renders_selected_choices(imgui_frame, monkeypatch):
    from myogestic.core import Context
    from myogestic.widgets import RecordingControls
    from myogestic.widgets.panels import _recording_controls

    controls = RecordingControls(
        on_record=lambda: None,
        on_stop=lambda: None,
        take_lengths=(3.0, 5.0, 10.0),
        warmups=(0.0, 1.0, 2.0, 3.0),
        timed=True,
        take_length=10.0,
        warmup=3.0,
    )
    selections = {}
    original = _recording_controls.segmented

    def selected(key, options, index):
        selections[key] = options[index]
        return original(key, options, index)

    monkeypatch.setattr(_recording_controls, "segmented", selected)
    imgui_frame(lambda: controls.ui(Context()))
    assert selections == {"take-mode": "Timed", "length": "10 s", "warmup": "3 s"}


@pytest.mark.parametrize("options", [{"timed": True}, {"timed": True, "take_lengths": ()}])
def test_initial_timed_mode_requires_take_lengths(options):
    from myogestic.widgets import RecordingControls

    with pytest.raises(ValueError, match="take_lengths"):
        RecordingControls(on_record=lambda: None, on_stop=lambda: None, **options)


@pytest.mark.parametrize(
    "name,value,choices",
    [
        ("take_length", 5.0, (3.0, 10.0)),
        ("take_length", 5.0, ()),
        ("take_length", float("nan"), (3.0, 10.0)),
        ("warmup", 2.0, (0.0, 3.0)),
        ("warmup", float("inf"), (0.0, 3.0)),
    ],
)
def test_invalid_initial_timing_names_allowed_choices(name, value, choices):
    from myogestic.widgets import RecordingControls

    sequence = "take_lengths" if name == "take_length" else "warmups"
    with pytest.raises(ValueError, match=name) as exc:
        RecordingControls(
            on_record=lambda: None,
            on_stop=lambda: None,
            **{name: value, sequence: choices},
        )
    assert str(choices) in str(exc.value)


def test_timed_widget_labels_only_when_capture_begins(timed_controls, imgui_frame):
    controls, ctx, now, calls, labels = timed_controls
    controls._start(ctx)
    assert controls.take.phase == "warmup"
    assert controls.take.length_s == 5.0
    assert controls.take.warmup_left_s == 2.0
    assert calls == labels == []
    now[0] = 2.0
    imgui_frame(lambda: controls.ui(ctx))
    assert calls == ["record"]
    assert labels == [1]
    now[0] = 7.0
    imgui_frame(lambda: controls.ui(ctx))
    assert calls == ["record", "stop"]
    assert controls.take.saved_text == "Saved · Fist · 5.0 s"


def test_timed_take_uses_first_gesture_by_default(timed_controls):
    controls, ctx, _, calls, _ = timed_controls
    ctx.current_label = -1
    controls._start(ctx)
    assert controls.take.phase == "warmup"
    assert controls.take.gesture == "Rest"
    assert ctx.current_label == 0
    assert calls == []


def test_external_gesture_change_cancels_warmup(timed_controls, imgui_frame):
    controls, ctx, now, calls, _ = timed_controls
    controls._start(ctx)
    ctx.current_label = 0
    now[0] = 3.0
    imgui_frame(lambda: controls.ui(ctx))
    assert controls.take.phase == "idle"
    assert calls == []


@pytest.mark.parametrize("phase", ["warmup", "recording"])
@pytest.mark.parametrize("change", ["participant", "stream", "session", "state"])
def test_external_changes_cancel_pending_work(timed_controls, imgui_frame, phase, change):
    controls, ctx, now, calls, _ = timed_controls
    controls._start(ctx)
    if phase == "recording":
        now[0] = 2.0
        imgui_frame(lambda: controls.ui(ctx))
    if change == "participant":
        ctx.participant = "P-015"
    elif change == "stream":
        ctx.streams["emg"].status = "disconnected"
    elif change == "session":
        ctx.session = object()
    else:
        ctx.state = "training" if phase == "warmup" else "idle"
        ctx.recording = False
    now[0] = 20.0
    imgui_frame(lambda: controls.ui(ctx, visible=False))
    assert controls.take.phase == "idle"
    assert calls == (
        []
        if phase == "warmup"
        else ["record", "stop"]
        if change in ("participant", "stream")
        else ["record"]
    )


def test_outside_stop_during_warmup_cancels(timed_controls, imgui_frame):
    from myogestic.core import App

    controls, ctx, now, calls, _ = timed_controls
    app = App("test")
    app.ctx = ctx
    # Repeating the same rejected Stop has no new state or message to observe.
    app.stop_recording()
    controls._start(ctx)
    app.stop_recording()
    now[0] = 3.0
    imgui_frame(lambda: controls.ui(ctx))
    assert controls.take.phase == "idle"
    assert calls == []


@pytest.mark.parametrize("timed", [True, False])
def test_only_timed_takes_lock_gestures(timed_controls, imgui_frame, monkeypatch, timed):
    from imgui_bundle import imgui

    controls, ctx, now, _, labels = timed_controls
    controls._timed = timed
    controls._start(ctx)
    now[0] = 2.0
    imgui_frame(lambda: controls.ui(ctx))
    original = imgui.button

    def click(label, *args):
        original(label, *args)
        return label.endswith("##rec_gesture0")

    monkeypatch.setattr(imgui, "button", click)
    imgui_frame(lambda: controls.ui(ctx))
    assert ctx.current_label == (1 if timed else 0)
    assert labels == ([1] if timed else [1, 0])
    assert controls.take.gesture == ("Fist" if timed else "Rest")


@pytest.mark.parametrize(
    "options",
    [
        {"take_lengths": (0.0,)},
        {"take_lengths": (float("nan"),)},
        {"warmups": (-1.0,)},
        {"warmups": ()},
    ],
)
def test_invalid_timing_choices_are_rejected(options):
    from myogestic.widgets import RecordingControls

    with pytest.raises(ValueError):
        RecordingControls(on_record=lambda: None, on_stop=lambda: None, **options)


def test_action_row_height_is_constant(timed_controls, imgui_frame, monkeypatch):
    from imgui_bundle import imgui

    from myogestic.widgets.panels import _recording_controls as module

    controls, ctx, now, _, _ = timed_controls
    heights = []
    action = module._action

    def measured(*args):
        # The row itself: a lock caption may follow it, so it is not the last item.
        action(*args)
        heights.append(imgui.get_item_rect_size().y)

    monkeypatch.setattr(module, "_action", measured)

    def draw():
        controls.ui(ctx)

    imgui_frame(draw)
    controls._start(ctx)
    imgui_frame(draw)
    now[0] = 2.0
    imgui_frame(draw)
    now[0] = 7.0
    imgui_frame(draw)
    assert heights == pytest.approx([heights[0]] * 4)


def test_timing_columns_share_caption_and_control_baselines(
    timed_controls, imgui_frame, monkeypatch
):
    from imgui_bundle import imgui

    from myogestic import _theme

    controls, ctx, _, _, _ = timed_controls
    _theme.apply_theme()
    captions, buttons = [], []
    text, button = imgui.text_colored, imgui.button

    def caption(tone, label):
        text(tone, label)
        if label in ("Take length", "Warm-up"):
            captions.append(imgui.get_item_rect_min().y)

    def segment(label, *args):
        result = button(label, *args)
        if label in ("3 s##length_seg0", "Off##warmup_seg0"):
            buttons.append(imgui.get_item_rect_min().y)
        return result

    monkeypatch.setattr(imgui, "text_colored", caption)
    monkeypatch.setattr(imgui, "button", segment)
    imgui_frame(lambda: controls.ui(ctx))
    assert captions[0] == captions[1]
    assert buttons[0] == buttons[1]


def test_timed_save_duration_is_within_one_frame(tmp_path, monkeypatch):
    import json
    import zipfile

    import numpy as np

    from myogestic.core import App
    from myogestic.session import Session
    from myogestic.stream import StreamInfo
    from myogestic.widgets import RecordingControls

    # Capture a paced sample clock, with an offset 60 Hz UI clock. Packing runs
    # synchronously here so the assertion reads the actual saved archive.
    monkeypatch.setattr("myogestic._browser.IS_BROWSER", True)
    app = App("timed")
    app.ctx.current_label = 0
    now = [0.0]
    starts = []

    def start():
        starts.append(now[0])
        app.ctx.state = "recording"
        app.ctx.recording = True
        app.ctx.session = Session(str(tmp_path))
        app.ctx.session.init_stream("emg", StreamInfo(n_channels=1, fs=1000.0))

    controls = RecordingControls(
        ["Fist"], on_record=start, on_stop=app.stop_recording, take_lengths=(5.0,), warmups=(2.0,)
    )
    controls._timed = True
    controls._machine._clock = lambda: now[0]
    controls._start(app.ctx)
    assert not list(tmp_path.iterdir())
    now[0] = 2.0
    controls.ui(app.ctx, visible=False)
    session = app.ctx.session
    sample_index = 0
    for frame in range(1, 302):
        now[0] = 2.0 + frame / 60 + 0.001
        end = int((now[0] - starts[0]) * 1000)
        timestamps = starts[0] + np.arange(sample_index, end) / 1000
        session.append("emg", np.zeros((len(timestamps), 1)), timestamps)
        sample_index = end
        controls.ui(app.ctx, visible=False)
        if app.ctx.state == "idle":
            break
    assert frame == 300
    assert starts == [2.0]
    with zipfile.ZipFile(session.path) as archive:
        duration = json.loads(archive.read("meta.json"))["duration_s"]
    assert duration == pytest.approx(5.0, abs=1 / 60)
    assert controls.take.phase == "saved"


def test_recording_controls_optional_header(imgui_frame, monkeypatch):
    from myogestic.core import Context
    from myogestic.widgets.panels import _recording_controls, recording

    headers = []
    monkeypatch.setattr(
        _recording_controls, "panel_header", lambda title, *a: headers.append(title)
    )
    for options, expected in [({}, ["RECORDING"]), ({"show_header": False}, [])]:
        headers.clear()
        controls = recording.RecordingControls(
            on_record=lambda: None, on_stop=lambda: None, **options
        )
        imgui_frame(lambda controls=controls: controls.ui(Context()))
        assert headers == expected


def test_safe_label_index_in_range():
    assert _safe_label_index(0, 3) == 0
    assert _safe_label_index(2, 3) == 2


def test_safe_label_index_negative():
    """-1 means 'no class selected' — preserved as-is."""
    assert _safe_label_index(-1, 3) == -1


def test_safe_label_index_out_of_range_clamps_to_negative_one():
    """Stale index from a previous CLASSES list is reset to -1, not silently
    coerced into a different class. The bug this guards against: a session
    with CLASSES=['A','B','C','D'] leaves current_label=3, then user reduces
    to CLASSES=['A','B'] — without this clamp, label 3 would wrap or write
    a class index that doesn't exist."""
    assert _safe_label_index(3, 2) == -1
    assert _safe_label_index(99, 5) == -1
    assert _safe_label_index(-2, 3) == -1  # weird negatives also rejected


def test_safe_label_index_zero_classes():
    """Edge: no class_names — every index is invalid."""
    assert _safe_label_index(0, 0) == -1
    assert _safe_label_index(-1, 0) == -1


def test_state_colors_default_entries():
    """Core states are populated; ml states get added by myogestic.ml.widgets."""
    from myogestic.core import AppState
    from myogestic.widgets.panels.recording import STATE_COLORS

    assert AppState.IDLE in STATE_COLORS
    assert AppState.RECORDING in STATE_COLORS


from myogestic.core import Context
from myogestic.widgets.panels.recording import _transport


def test_transport_offers_record_from_idle_and_stop_while_recording():
    ctx = Context()
    assert _transport(ctx) == "record"
    ctx.recording = True
    ctx.state = "recording"
    ctx.recording = True
    assert _transport(ctx) == "stop"


def test_transport_offers_nothing_from_an_unregistered_state():
    # Only "training" is safe to assert on: any earlier test module that built a
    # Pipeline has registered "predicting" in the process-global set for good.
    ctx = Context()
    ctx.state = "training"
    assert _transport(ctx) == ""


def test_transport_offers_record_from_a_registered_state(recordable_predicting):
    ctx = Context()
    ctx.state = "predicting"
    assert _transport(ctx) == "record"
    ctx.recording = True
    assert _transport(ctx) == "stop"  # state still predicting, take open


def test_recording_controls_predicting_uses_flag_for_tiles_and_stop(
    tmp_path,
    imgui_frame,
    monkeypatch,
    recordable_predicting,
):
    from imgui_bundle import imgui

    from myogestic.core import App
    from myogestic.widgets import RecordingControls

    app = App("predicting take")
    app.ctx.state = "predicting"
    controls = RecordingControls(
        ["Rest", "Fist"],
        on_record=lambda: app.start_recording(str(tmp_path)),
        on_stop=lambda: app.stop_recording(wait=True),
    )
    button = imgui.button
    pressed = ["rec_btn"]

    def click(label, *args):
        result = button(label, *args)
        return label.endswith("##" + pressed[0]) or result

    monkeypatch.setattr(imgui, "button", click)
    imgui_frame(lambda: controls.ui(app.ctx))
    assert app.ctx.recording and app.ctx.state == "predicting"
    assert app.ctx.session.label_track[0].class_index == 0
    pressed[0] = "rec_gesture1"
    imgui_frame(lambda: controls.ui(app.ctx))
    assert app.ctx.session.label_track[-1].class_index == 1
    pressed[0] = "rec_btn"
    imgui_frame(lambda: controls.ui(app.ctx))
    assert not app.ctx.recording and app.ctx.state == "predicting"
    assert app.ctx.session.path.is_file()
