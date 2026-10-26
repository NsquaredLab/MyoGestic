"""ML-pipeline widgets. Take a `Pipeline` argument, not `App`.

from myogestic.ml import Pipeline
from myogestic.ml.widgets import TrainButton, PredictButton, TrainingLog

train = TrainButton(pipeline)
predict = PredictButton(pipeline)
log = TrainingLog(pipeline)

@app.ui
def my_ui(ctx):
    train.ui()
    predict.ui()
    log.ui()
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic._theme import mono_font
from myogestic.ml import PipelineState
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    INFO,
    SUCCESS,
    WARNING,
    _truncate_to_width,
    mono_text,
    muted,
    panel_header,
    pop_selected,
    primary_button,
    push_selected,
    tinted_row,
    ui_px,
)
from myogestic.widgets.panels.log_box import (
    render_log,
    render_log_buttons,
    render_log_popout,
)
from myogestic.widgets.panels.recording import STATE_COLORS
from myogestic.widgets.training._session_state import packed_session_path

# Per-panel log UX state, keyed by widget_id (defaults to "ml"), so each panel
# remembers its own popout state across frames.
_popout_open: dict[str, bool] = {}

# Register ml state colors on the core recording widget's state-pill dict.
# (Inverts coupling: ml depends on widgets, not the other way around.)
STATE_COLORS.setdefault(PipelineState.TRAINING, WARNING)
STATE_COLORS.setdefault(PipelineState.PREDICTING, INFO)

if TYPE_CHECKING:
    from myogestic.ml import Pipeline


# --- Render functions (private; the classes below are the public API) ------


def _scaled_size(size: tuple[float, float]) -> tuple[float, float]:
    """Scale fixed sizes while preserving ImGui's automatic-size sentinels."""
    return tuple(ui_px(value) if value > 0 else value for value in size)


def _disabled_caption(reason: str) -> None:
    """Keep the next step visible, including in a narrow cell."""
    if reason:
        imgui.push_style_color(imgui.Col_.text, muted())
        imgui.push_text_wrap_pos(imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x)
        imgui.text_wrapped(reason)
        imgui.pop_text_wrap_pos()
        imgui.pop_style_color()


def _render_train_button(
    pipeline: Pipeline, size: tuple[float, float] = (92, 0), *, full_width: bool = False,
) -> None:
    state = pipeline.app.ctx.state
    if state == PipelineState.PREDICTING:
        reason = "Stop predicting to train a model."
    elif state == "recording":
        reason = "Stop recording to train a model."
    elif state != "idle":
        reason = "Wait until the current action finishes to train a model."
    elif getattr(pipeline.app.ctx, "pending_saves", None):
        reason = "Wait until the last take is saved to train."
    elif pipeline.on_train is None:
        reason = "Add @pipeline.train to enable training."
    elif pipeline.training_data is None or pipeline.training_data.is_empty:
        reason = "Record a take or select training takes to enable Train."
    else:
        reason = ""
    size = (imgui.get_content_region_avail().x, 0) if full_width else _scaled_size(size)
    imgui.begin_disabled(bool(reason))
    clicked = primary_button(f"{fa.ICON_FA_GEARS}  Train##ml_train", size=size)
    imgui.end_disabled()
    if clicked and not reason:
        # A pack can finish between this frame's session picker and Train.
        data = pipeline.training_data
        paths = [str(packed_session_path(Path(path)) or path) for path in data.paths]
        if paths != data.paths:
            pipeline.training_data = replace(data, paths=list(dict.fromkeys(paths)))
        pipeline.start_training()
    _disabled_caption(reason)


def _render_predict_button(pipeline: Pipeline, size: tuple[float, float] = (92, 0)) -> None:
    state = pipeline.app.ctx.state
    selected = state == PipelineState.PREDICTING
    if selected:
        reason = ""
    elif state != "idle":
        reason = "Finish the current action to enable Predict."
    elif pipeline.model is None:
        reason = "To predict, train or load a model first."
    elif pipeline.on_extract is None or pipeline.on_predict is None:
        reason = "Add @pipeline.extract and @pipeline.predict to enable Predict."
    else:
        reason = ""
    imgui.begin_disabled(bool(reason))
    if selected:
        push_selected()
    icon = fa.ICON_FA_STOP if selected else fa.ICON_FA_PLAY
    clicked = imgui.button(f"{icon}  Predict##ml_pred", imgui.ImVec2(*_scaled_size(size)))
    if selected:
        pop_selected()
    imgui.end_disabled()
    imgui.set_item_tooltip("Stop predicting" if selected else "Start predicting")
    if clicked and not reason:
        if selected:
            pipeline.stop_predicting()
        else:
            pipeline.start_predicting()
    _disabled_caption(reason)


def _render_training_log(
    pipeline: Pipeline, height: float = 100.0, *, widget_id: str = "ml"
) -> None:
    if not pipeline.train_log:
        return
    render_log(widget_id, pipeline.train_log, height=ui_px(height) if height > 0 else height)


def _render_save_model_button(
    pipeline: Pipeline, path: str, size: tuple[float, float] = (92, 0)
) -> None:
    reason = ""
    if pipeline.model is None:
        reason = "To save, train or load a model first."
    elif pipeline.save_model is None:
        reason = "Set pipeline.save_model to enable Save."
    imgui.begin_disabled(bool(reason))
    clicked = imgui.button(f"{fa.ICON_FA_FLOPPY_DISK}##ml_save", imgui.ImVec2(*_scaled_size(size)))
    imgui.end_disabled()
    imgui.set_item_tooltip(f"Save model to {path}")
    _disabled_caption(reason)
    if clicked and not reason:
        try:
            pipeline.save_model(pipeline.model, path)
            pipeline.app.ctx.status_message = f"Saved model to {path}"
            pipeline.app.ctx.log(f"Model saved → {path}")
        except Exception as e:
            pipeline.app.ctx.status_message = f"Save failed: {e}"
            pipeline.app.ctx.log(f"Model save failed: {e}")


def _render_load_model_button(
    pipeline: Pipeline, path: str, size: tuple[float, float] = (92, 0)
) -> None:
    reason = "Set pipeline.load_model to enable Load." if pipeline.load_model is None else ""
    imgui.begin_disabled(bool(reason))
    clicked = imgui.button(f"{fa.ICON_FA_FOLDER_OPEN}##ml_load", imgui.ImVec2(*_scaled_size(size)))
    imgui.end_disabled()
    imgui.set_item_tooltip(f"Load model from {path}")
    _disabled_caption(reason)
    if clicked and not reason:
        try:
            pipeline.model = pipeline.load_model(path)
            pipeline.app.ctx.status_message = f"Loaded model from {path}"
            pipeline.app.ctx.log(f"Model loaded ← {path}")
        except Exception as e:
            pipeline.app.ctx.status_message = f"Load failed: {e}"
            pipeline.app.ctx.log(f"Model load failed: {e}")


def _pipeline_status(pipeline: Pipeline) -> tuple[imgui.ImVec4, str, str]:
    """Read state and failure details from the existing pipeline lifecycle."""
    ctx = pipeline.app.ctx
    if ctx.state == PipelineState.TRAINING:
        return WARNING, "Training…", ""
    if ctx.state == PipelineState.PREDICTING:
        return SUCCESS, "Predicting", f"{pipeline.predict_hz:g} Hz"
    if ctx.status_message.startswith("Training failed: "):
        return DANGER, "Training failed", ctx.status_message.removeprefix("Training failed: ")
    return IDLE, "Trained" if pipeline.model is not None else "Not trained", ""


def _render_state_row(tone: imgui.ImVec4, label: str, detail: str) -> None:
    """Keep state in words and fit mono details with the full text on hover."""
    height = None
    if detail:
        height = (2 * imgui.get_text_line_height() + imgui.get_style().item_spacing.y
                  + ui_px(8))
    with tinted_row(tone, height=height) as width:
        if not detail:
            imgui.align_text_to_frame_padding()
        imgui.text_unformatted(label)
        if detail:
            # Measure in the same face that mono_text uses, so clipping is exact.
            font = mono_font()
            if font is not None:
                imgui.push_font(font, imgui.get_style().font_size_base)
            single_line = " ".join(detail.splitlines())
            clipped = single_line
            if imgui.calc_text_size(clipped).x > width:
                clipped = _truncate_to_width(clipped, width - imgui.calc_text_size("…").x) + "…"
            mono_text(clipped)
            if font is not None:
                imgui.pop_font()
            imgui.set_item_tooltip(detail)


def _render_pipeline_panel(
    pipeline: Pipeline, *, log_height: float = 0.0, widget_id: str = "ml"
) -> None:
    # Render any open popout first so it survives frames even when the surrounding
    # panel scrolls out of view (as in process_launcher._render_open_popouts).
    if _popout_open.get(widget_id, False):
        still_open = render_log_popout(
            widget_id,
            pipeline.train_log,
            title="Model training log",
        )
        if not still_open:
            _popout_open[widget_id] = False

    imgui.push_id(widget_id)
    try:
        tone, label, detail = _pipeline_status(pipeline)
        popped = _popout_open.get(widget_id, False)
        show_log_action = bool(pipeline.train_log) or popped
        style = imgui.get_style()
        icon = (fa.ICON_FA_DOWN_LEFT_AND_UP_RIGHT_TO_CENTER if popped
                else fa.ICON_FA_UP_RIGHT_AND_DOWN_LEFT_FROM_CENTER)
        action_width = imgui.calc_text_size(icon).x + 2 * style.frame_padding.x
        reserve = action_width + style.item_spacing.x if show_log_action else 0.0
        panel_header("MODEL", fa.ICON_FA_BRAIN, status=tone, reserve=reserve)
        if show_log_action:
            imgui.same_line()
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(
                0.0, imgui.get_content_region_avail().x - action_width,
            ))
            _popout_open[widget_id] = render_log_buttons(widget_id, popped_out=popped)

        _render_state_row(tone, label, detail)
        _render_train_button(pipeline, full_width=True)
        _render_predict_button(pipeline, size=(0, 0))

        # Match ProcessLauncher: an inline mono log is explicitly opt-in.
        if log_height > 0 and not _popout_open.get(widget_id, False):
            render_log(widget_id, pipeline.train_log, height=ui_px(log_height))
    finally:
        imgui.pop_id()


# --- Public widgets --------------------------------------------------------


class TrainButton:
    """Primary Train action — calls [`Pipeline.start_training`][] on click.

    Disabled until idle with a training callback and selected takes. A visible
    caption explains what is missing. ``size`` uses logical pixels and follows
    the UI scale.

    Examples
    --------
    >>> from myogestic.ml.widgets import TrainButton
    >>> button = TrainButton(pipeline)
    >>> button.ui()
    """

    def __init__(self, pipeline: Pipeline, *, size: tuple[float, float] = (92, 0)) -> None:
        self._pipeline = pipeline
        self._size = size

    def ui(self) -> None:
        """Render the Train button. Call once per frame inside ``@app.ui``."""
        _render_train_button(self._pipeline, self._size)


class PredictButton:
    """Predict/Stop toggle reflecting the pipeline's predict state.

    Enabled to start only when the state is ``idle``, a model is loaded, and
    both the extract and predict callbacks are wired. The selected chip stops
    prediction when clicked; unavailable states show a visible next-step caption.
    ``size`` uses logical pixels and follows the UI scale.

    Examples
    --------
    >>> from myogestic.ml.widgets import PredictButton
    >>> button = PredictButton(pipeline)
    >>> button.ui()
    """

    def __init__(self, pipeline: Pipeline, *, size: tuple[float, float] = (92, 0)) -> None:
        self._pipeline = pipeline
        self._size = size

    def ui(self) -> None:
        """Render the Predict/Stop button. Call once per frame."""
        _render_predict_button(self._pipeline, self._size)


class TrainingLog:
    """Read-only view of ``pipeline.train_log``.

    The popout *toggle* isn't drawn here — it lives on
    [`PipelinePanel`][]'s header. The compact, selectable console uses the mono
    font, and ``height`` follows the UI scale.

    Examples
    --------
    >>> from myogestic.ml.widgets import TrainingLog
    >>> log = TrainingLog(pipeline)
    >>> log.ui()
    """

    def __init__(self, pipeline: Pipeline, *, height: float = 100.0, widget_id: str = "ml") -> None:
        self._pipeline = pipeline
        self._height = height
        self._widget_id = widget_id

    def ui(self) -> None:
        """Render the training log. Call once per frame."""
        _render_training_log(self._pipeline, self._height, widget_id=self._widget_id)


class SaveModelButton:
    """Save icon action — writes the model to ``path`` via ``pipeline.save_model``.

    Disabled unless both ``pipeline.save_model`` and ``pipeline.model`` are set.
    A visible caption explains how to enable it. ``size`` uses logical pixels
    and follows the UI scale.

    Examples
    --------
    >>> from myogestic.ml.widgets import SaveModelButton
    >>> button = SaveModelButton(pipeline, "models/demo.joblib")
    >>> button.ui()
    """

    def __init__(
        self, pipeline: Pipeline, path: str, *, size: tuple[float, float] = (92, 0)
    ) -> None:
        self._pipeline = pipeline
        self._path = path
        self._size = size

    def ui(self) -> None:
        """Render the Save button. Call once per frame."""
        _render_save_model_button(self._pipeline, self._path, self._size)


class LoadModelButton:
    """Load icon action — reads a model from ``path`` via ``pipeline.load_model``.

    Disabled unless ``pipeline.load_model`` is set, with a visible next-step
    caption. ``size`` uses logical pixels and follows the UI scale.

    Examples
    --------
    >>> from myogestic.ml.widgets import LoadModelButton
    >>> button = LoadModelButton(pipeline, "models/demo.joblib")
    >>> button.ui()
    """

    def __init__(
        self, pipeline: Pipeline, path: str, *, size: tuple[float, float] = (92, 0)
    ) -> None:
        self._pipeline = pipeline
        self._path = path
        self._size = size

    def ui(self) -> None:
        """Render the Load button. Call once per frame."""
        _render_load_model_button(self._pipeline, self._path, self._size)


class PipelinePanel:
    """One model card with pipeline state, Train, Predict and a compact log.

    The header's state dot is repeated in words in a tinted row, with mono
    prediction rate or failure detail. Train is the full-width primary action;
    Predict is a sticky chip. Disabled controls explain their next step visibly.

    The header's icon opens the log in a popout, the same way
    [`ProcessLauncher`][myogestic.widgets.ProcessLauncher]'s does: a window you can move,
    resize and leave open. The selectable mono log is only drawn inline when a
    height is supplied.

    Parameters
    ----------
    pipeline
        The [`Pipeline`][myogestic.Pipeline] to train and predict with.
    log_height
        Logical pixel height of an **optional** inline log, scaled with the UI.
        ``<= 0`` (the default) draws none.
    widget_id
        Unique ID for this panel, so controls and popout state stay independent.

    Examples
    --------
    >>> from myogestic.ml.widgets import PipelinePanel
    >>> panel = PipelinePanel(pipeline)
    >>> panel.ui()
    """

    def __init__(
        self, pipeline: Pipeline, *, log_height: float = 0.0, widget_id: str = "ml"
    ) -> None:
        self._pipeline = pipeline
        self._log_height = log_height
        self._widget_id = widget_id

    def ui(self) -> None:
        """Render the pipeline panel. Call once per frame inside ``@app.ui``."""
        _render_pipeline_panel(
            self._pipeline, log_height=self._log_height, widget_id=self._widget_id
        )


__all__ = [
    "LoadModelButton",
    "PipelinePanel",
    "PredictButton",
    "SaveModelButton",
    "TrainButton",
    "TrainingLog",
]
