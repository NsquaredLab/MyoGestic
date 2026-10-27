"""Pipeline cards retain their wiring and fit the 2.0 kit headlessly."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from imgui_bundle import imgui

from myogestic import _scale, _theme
from myogestic.ml import widgets
from myogestic.widgets import common


@pytest.fixture
def pipeline():
    return SimpleNamespace(
        app=SimpleNamespace(ctx=SimpleNamespace(state="idle", status_message="", log=Mock())),
        model=None,
        train_log=[],
        predict_hz=50,
        on_train=Mock(),
        on_extract=Mock(),
        on_predict=Mock(),
        training_data=SimpleNamespace(is_empty=False, paths=["take.zarr"]),
        save_model=Mock(),
        load_model=Mock(),
        start_training=Mock(),
        start_predicting=Mock(),
        stop_predicting=Mock(),
    )


@pytest.mark.parametrize(
    "status, expected, tone",
    [
        ("idle", "Not trained", common.IDLE),
        ("training", "Training…", common.WARNING),
        ("trained", "Trained", common.IDLE),
        ("predicting", "Predicting", common.SUCCESS),
        ("failed", "Training failed", common.DANGER),
    ],
)
def test_pipeline_state_is_in_one_tinted_row(
    imgui_frame,
    monkeypatch,
    pipeline,
    status,
    expected,
    tone,
):
    pipeline.app.ctx.state = status if status in ("training", "predicting") else "idle"
    if status in ("trained", "predicting", "failed"):
        pipeline.model = object()  # A failed retrain must not hide behind the old model.
    if status == "failed":
        pipeline.app.ctx.status_message = "Training failed: missing labels"
    headers, rows, text = [], [], []
    in_row = False

    @contextmanager
    def row(color=None, **kwargs):
        nonlocal in_row
        rows.append(color)
        with common.tinted_row(color, **kwargs) as width:
            in_row = True
            yield width
            in_row = False

    def header(*args, **kwargs):
        headers.append(kwargs.get("status"))
        common.panel_header(*args, **kwargs)

    real_text = imgui.text_unformatted

    def plain(label):
        if in_row:
            text.append(label)
        real_text(label)

    monkeypatch.setattr(widgets, "tinted_row", row, raising=False)
    monkeypatch.setattr(widgets, "panel_header", header)
    monkeypatch.setattr(imgui, "text_unformatted", plain)
    imgui_frame(widgets.PipelinePanel(pipeline).ui)
    assert len(headers) == 1 and headers[0] is tone
    assert len(rows) == 1 and rows[0] is tone
    assert expected in " ".join(text)
    if status == "failed":
        assert "missing labels" in " ".join(text)


def test_train_is_the_only_full_width_primary_action(imgui_frame, monkeypatch, pipeline):
    actions = []

    def primary(label, size=(0, 0)):
        actions.append((label, size[0], imgui.get_content_region_avail().x))
        return common.primary_button(label, size)

    monkeypatch.setattr(widgets, "primary_button", primary, raising=False)
    imgui_frame(widgets.PipelinePanel(pipeline).ui)
    assert len(actions) == 1
    assert "Train" in actions[0][0]
    assert actions[0][1] == pytest.approx(actions[0][2])


def test_predict_chip_pairs_selection_even_when_clicked(imgui_frame, monkeypatch, pipeline):
    pipeline.app.ctx.state = "predicting"
    selected = []

    def push():
        selected.append("push")
        common.push_selected()

    def pop():
        selected.append("pop")
        common.pop_selected()

    real_button = imgui.button

    def click(label, *args):
        real_button(label, *args)
        return "ml_pred" in label

    pipeline.stop_predicting.side_effect = lambda: setattr(pipeline.app.ctx, "state", "idle")
    monkeypatch.setattr(widgets, "push_selected", push, raising=False)
    monkeypatch.setattr(widgets, "pop_selected", pop, raising=False)
    monkeypatch.setattr(imgui, "button", click)
    imgui_frame(widgets.PredictButton(pipeline).ui)
    assert selected == ["push", "pop"]
    pipeline.stop_predicting.assert_called_once()


@pytest.mark.parametrize(
    "action, change, reason",
    [
        ("TrainButton", {"on_train": None}, "@pipeline.train"),
        ("TrainButton", {"training_data": None}, "select"),
        ("PredictButton", {}, "train or load"),
        ("PredictButton", {"model": object(), "on_extract": None}, "@pipeline.extract"),
        ("SaveModelButton", {}, "train or load"),
        ("SaveModelButton", {"model": object(), "save_model": None}, "pipeline.save_model"),
        ("LoadModelButton", {"load_model": None}, "pipeline.load_model"),
    ],
)
def test_disabled_action_has_a_visible_caption_outside_disabled_block(
    imgui_frame,
    monkeypatch,
    pipeline,
    action,
    change,
    reason,
):
    for name, value in change.items():
        setattr(pipeline, name, value)
    disabled, buttons, captions = [], [], []
    real_begin, real_end, real_text = imgui.begin_disabled, imgui.end_disabled, imgui.text_wrapped
    real_button = imgui.button

    def begin(value=True):
        disabled.append(value)
        real_begin(value)

    def end():
        disabled.pop()
        real_end()

    def text(label):
        captions.append((label.lower(), any(disabled)))
        real_text(label)

    def button(label, *args):
        buttons.append(any(disabled))
        return real_button(label, *args)

    monkeypatch.setattr(imgui, "begin_disabled", begin)
    monkeypatch.setattr(imgui, "end_disabled", end)
    monkeypatch.setattr(imgui, "text_wrapped", text)
    monkeypatch.setattr(imgui, "button", button)
    args = (
        (pipeline, "model.joblib")
        if action in ("SaveModelButton", "LoadModelButton")
        else (pipeline,)
    )
    imgui_frame(getattr(widgets, action)(*args).ui)
    assert buttons == [True]
    assert any(reason in label and not dimmed for label, dimmed in captions)


@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("status", ["idle", "training", "trained", "predicting", "failed"])
def test_pipeline_fits_a_320_pixel_cell(imgui_frame, monkeypatch, pipeline, scale, dark, status):
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    pipeline.app.ctx.state = status if status in ("training", "predicting") else "idle"
    if status in ("trained", "predicting"):
        pipeline.model = object()
    if status == "failed":
        pipeline.app.ctx.status_message = "Training failed: " + "missing labelled input " * 20
    pipeline.train_log = ["training input " * 30]
    panel = widgets.PipelinePanel(pipeline, log_height=60, widget_id="narrow")
    overflow = []
    bounds = {}
    overhang = []
    real_button = imgui.button

    def button(label, *args):
        result = real_button(label, *args)
        overhang.append(imgui.get_item_rect_max().x - bounds["right"])
        return result

    monkeypatch.setattr(imgui, "button", button)

    def draw():
        imgui.begin_child(
            "cell", imgui.ImVec2(320, 400), window_flags=imgui.WindowFlags_.horizontal_scrollbar
        )
        bounds["right"] = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        panel.ui()
        overflow.append(imgui.get_scroll_max_x())
        imgui.end_child()

    for _ in range(4):
        imgui_frame(draw)
    assert overflow[-1] == pytest.approx(0.0, abs=1.0)
    assert max(overhang) <= 1.0


@pytest.mark.parametrize(
    "action, suffix, callback",
    [
        ("TrainButton", "ml_train", "start_training"),
        ("PredictButton", "ml_pred", "start_predicting"),
        ("SaveModelButton", "ml_save", "save_model"),
        ("LoadModelButton", "ml_load", "load_model"),
    ],
)
def test_standalone_actions_keep_callbacks_and_scaled_size(
    imgui_frame,
    monkeypatch,
    pipeline,
    action,
    suffix,
    callback,
):
    monkeypatch.setattr(_scale, "_current", 2.0)
    pipeline.model = object()
    old_model = pipeline.model
    labels, sizes = [], []
    real = imgui.button

    def click(label, size):
        labels.append(label.split("##")[0])
        sizes.append((size.x, size.y))
        real(label, size)
        return label.endswith(suffix)

    monkeypatch.setattr(imgui, "button", click)
    args = (
        (pipeline, "model.joblib")
        if action in ("SaveModelButton", "LoadModelButton")
        else (pipeline,)
    )
    imgui_frame(getattr(widgets, action)(*args, size=(70, 24)).ui)
    assert sizes == [(140, 48)]
    if action == "SaveModelButton":
        pipeline.save_model.assert_called_once_with(old_model, "model.joblib")
        assert "Saved model" in pipeline.app.ctx.status_message
        assert len(labels[0]) == 1, "Save is an icon-only secondary action"
    elif action == "LoadModelButton":
        pipeline.load_model.assert_called_once_with("model.joblib")
        assert pipeline.model is pipeline.load_model.return_value
        assert "Loaded model" in pipeline.app.ctx.status_message
        assert len(labels[0]) == 1, "Load is an icon-only secondary action"
    else:
        getattr(pipeline, callback).assert_called_once_with()


@pytest.mark.parametrize(
    "action, callback, message",
    [
        ("SaveModelButton", "save_model", "Save failed: unavailable"),
        ("LoadModelButton", "load_model", "Load failed: unavailable"),
    ],
)
def test_file_action_errors_remain_reported(
    imgui_frame, monkeypatch, pipeline, action, callback, message
):
    pipeline.model = object()
    old_model = pipeline.model
    getattr(pipeline, callback).side_effect = OSError("unavailable")
    real = imgui.button

    def click(*args):
        real(*args)
        return True

    monkeypatch.setattr(imgui, "button", click)
    imgui_frame(getattr(widgets, action)(pipeline, "model.joblib").ui)
    assert pipeline.app.ctx.status_message == message
    assert pipeline.model is old_model
    pipeline.app.ctx.log.assert_called_once()


def test_panel_ids_are_independent_and_log_action_is_in_the_header(
    imgui_frame, monkeypatch, pipeline
):
    pipeline.train_log = ["Training complete"]
    ids, actions = [], []
    real = imgui.button

    def button(label, *args):
        if label.endswith("ml_train"):
            ids.append(imgui.get_id(label))
        real(label, *args)
        actions.append((label, imgui.get_item_rect_min().y))
        return False

    monkeypatch.setattr(imgui, "button", button)
    first = widgets.PipelinePanel(pipeline, widget_id="first")
    second = widgets.PipelinePanel(pipeline, widget_id="second")
    imgui_frame(lambda: (first.ui(), second.ui()))
    assert len(set(ids)) == 2
    for name in ("first", "second"):
        popout = next(y for label, y in actions if label.endswith(f"{name}_popout"))
        assert any(y > popout for label, y in actions if label.endswith("ml_train"))


def test_inline_log_is_scaled_and_monospaced(imgui_frame, monkeypatch, pipeline):
    from myogestic.widgets.panels import log_box

    monkeypatch.setattr(_scale, "_current", 2.0)
    font = imgui.get_io().fonts.fonts[0]
    monkeypatch.setattr(log_box, "mono_font", lambda: font)
    pipeline.train_log = ["fitting", "Training complete"]
    boxes = []
    real = imgui.input_text_multiline

    def box(label, value, size, **kwargs):
        boxes.append((value, size.y, imgui.get_font() is font))
        return real(label, value, size, **kwargs)

    monkeypatch.setattr(imgui, "input_text_multiline", box)
    imgui_frame(widgets.PipelinePanel(pipeline, log_height=60).ui)
    imgui_frame(widgets.TrainingLog(pipeline, height=50).ui)
    assert boxes == [
        ("fitting\nTraining complete", 120, True),
        ("fitting\nTraining complete", 100, True),
    ]
