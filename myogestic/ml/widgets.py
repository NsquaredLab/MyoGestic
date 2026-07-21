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

from typing import TYPE_CHECKING

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.ml import PipelineState
from myogestic.widgets.common import panel_header
from myogestic.widgets.panels.log_box import (
    render_log,
    render_log_buttons,
    render_log_popout,
)
from myogestic.widgets.panels.recording import STATE_COLORS

# Per-panel persistent log UX state, keyed by widget_id (defaults to "ml").
# Lets each panel remember its own autoscroll + popout state across frames.
_autoscroll: dict[str, bool] = {}
_popout_open: dict[str, bool] = {}

# Register ml state colors on the core recording widget's state-pill dict.
# (Inverts coupling: ml depends on widgets, not the other way around.)
STATE_COLORS.setdefault(PipelineState.TRAINING, imgui.ImVec4(1.0, 0.74, 0.24, 1.0))
STATE_COLORS.setdefault(PipelineState.PREDICTING, imgui.ImVec4(0.31, 0.73, 0.98, 1.0))

if TYPE_CHECKING:
    from myogestic.ml import Pipeline


# --- Render functions (private; the classes below are the public API) ------


def _render_train_button(pipeline: Pipeline, size: tuple[float, float] = (80, 0)) -> None:
    if imgui.button(f"{fa.ICON_FA_GEARS}  Train##ml_train", imgui.ImVec2(*size)):
        pipeline.start_training()


def _render_predict_button(pipeline: Pipeline, size: tuple[float, float] = (92, 0)) -> None:
    state = pipeline.app.ctx.state
    # Predict needs three things together: the state must be idle, a model
    # must be loaded, AND both extract + predict callbacks must be wired.
    can_start = (
        state == "idle"
        and pipeline.model is not None
        and pipeline.on_extract is not None
        and pipeline.on_predict is not None
    )
    if can_start:
        if imgui.button(f"{fa.ICON_FA_PLAY}  Predict##ml_pred", imgui.ImVec2(*size)):
            pipeline.start_predicting()
    elif state == PipelineState.PREDICTING:
        if imgui.button(f"{fa.ICON_FA_STOP}  Predict##ml_pred", imgui.ImVec2(*size)):
            pipeline.stop_predicting()
    else:
        imgui.begin_disabled()
        imgui.button(f"{fa.ICON_FA_PLAY}  Predict##ml_pred", imgui.ImVec2(*size))
        imgui.end_disabled()


def _render_training_log(
    pipeline: Pipeline, height: float = 100.0, *, widget_id: str = "ml"
) -> None:
    if not pipeline.train_log:
        return
    autoscroll = _autoscroll.setdefault(widget_id, True)
    render_log(widget_id, pipeline.train_log, height=height, autoscroll=autoscroll)


def _render_save_model_button(
    pipeline: Pipeline, path: str, size: tuple[float, float] = (100, 0)
) -> None:
    if pipeline.save_model is None or pipeline.model is None:
        imgui.begin_disabled()
        imgui.button(f"{fa.ICON_FA_FLOPPY_DISK}  Save##ml_save", imgui.ImVec2(*size))
        imgui.end_disabled()
        return
    if imgui.button(f"{fa.ICON_FA_FLOPPY_DISK}  Save##ml_save", imgui.ImVec2(*size)):
        try:
            pipeline.save_model(pipeline.model, path)
            pipeline.app.ctx.status_message = f"Saved model to {path}"
            pipeline.app.ctx.log(f"Model saved → {path}")
        except Exception as e:
            pipeline.app.ctx.status_message = f"Save failed: {e}"
            pipeline.app.ctx.log(f"Model save failed: {e}")


def _render_load_model_button(
    pipeline: Pipeline, path: str, size: tuple[float, float] = (100, 0)
) -> None:
    if pipeline.load_model is None:
        imgui.begin_disabled()
        imgui.button(f"{fa.ICON_FA_FOLDER_OPEN}  Load##ml_load", imgui.ImVec2(*size))
        imgui.end_disabled()
        return
    if imgui.button(f"{fa.ICON_FA_FOLDER_OPEN}  Load##ml_load", imgui.ImVec2(*size)):
        try:
            pipeline.model = pipeline.load_model(path)
            pipeline.app.ctx.status_message = f"Loaded model from {path}"
            pipeline.app.ctx.log(f"Model loaded ← {path}")
        except Exception as e:
            pipeline.app.ctx.status_message = f"Load failed: {e}"
            pipeline.app.ctx.log(f"Model load failed: {e}")


def _render_pipeline_panel(
    pipeline: Pipeline, *, log_height: float = 80.0, widget_id: str = "ml"
) -> None:
    # Render any open popout first so it survives frames even when the
    # surrounding panel scrolls out of view (same pattern as
    # process_launcher._render_open_popouts).
    if _popout_open.get(widget_id, False):
        autoscroll = _autoscroll.setdefault(widget_id, True)
        still_open = render_log_popout(
            widget_id,
            pipeline.train_log,
            title="Model training log",
            autoscroll=autoscroll,
        )
        if not still_open:
            _popout_open[widget_id] = False

    panel_header("MODEL", fa.ICON_FA_BRAIN)
    _render_train_button(pipeline)
    imgui.same_line()
    _render_predict_button(pipeline)

    # Autoscroll + popout toggles, same look as the process launcher.
    imgui.same_line()
    autoscroll = _autoscroll.setdefault(widget_id, True)
    popped = _popout_open.get(widget_id, False)
    autoscroll, popped = render_log_buttons(widget_id, autoscroll=autoscroll, popped_out=popped)
    _autoscroll[widget_id] = autoscroll
    _popout_open[widget_id] = popped

    if popped:
        imgui.text_disabled("(log popped out — see 'Model training log' window)")
    elif pipeline.train_log:
        render_log(
            widget_id,
            pipeline.train_log,
            height=log_height,
            autoscroll=autoscroll,
        )


# --- Public widgets --------------------------------------------------------


class TrainButton:
    """Train button — calls :meth:`Pipeline.start_training` on click."""

    def __init__(self, pipeline: Pipeline, *, size: tuple[float, float] = (80, 0)) -> None:
        self._pipeline = pipeline
        self._size = size

    def ui(self) -> None:
        """Render the Train button. Call once per frame inside ``@app.ui``."""
        _render_train_button(self._pipeline, self._size)


class PredictButton:
    """Predict/Stop toggle reflecting the pipeline's predict state.

    Enabled to start only when the state is ``idle``, a model is loaded, and
    both the extract and predict callbacks are wired; shows a Stop button
    while predicting and is disabled otherwise.
    """

    def __init__(self, pipeline: Pipeline, *, size: tuple[float, float] = (92, 0)) -> None:
        self._pipeline = pipeline
        self._size = size

    def ui(self) -> None:
        """Render the Predict/Stop button. Call once per frame."""
        _render_predict_button(self._pipeline, self._size)


class TrainingLog:
    """Read-only view of ``pipeline.train_log`` with smart autoscroll.

    The autoscroll/popout *toggles* aren't drawn here — they're part of
    :class:`PipelinePanel`'s control row so they sit next to Train/Predict.
    """

    def __init__(self, pipeline: Pipeline, *, height: float = 100.0, widget_id: str = "ml") -> None:
        self._pipeline = pipeline
        self._height = height
        self._widget_id = widget_id

    def ui(self) -> None:
        """Render the training log. Call once per frame."""
        _render_training_log(self._pipeline, self._height, widget_id=self._widget_id)


class SaveModelButton:
    """Save button — writes the model to ``path`` via ``pipeline.save_model``.

    Disabled unless both ``pipeline.save_model`` and ``pipeline.model`` are set.
    """

    def __init__(
        self, pipeline: Pipeline, path: str, *, size: tuple[float, float] = (100, 0)
    ) -> None:
        self._pipeline = pipeline
        self._path = path
        self._size = size

    def ui(self) -> None:
        """Render the Save button. Call once per frame."""
        _render_save_model_button(self._pipeline, self._path, self._size)


class LoadModelButton:
    """Load button — reads a model from ``path`` via ``pipeline.load_model``.

    Disabled unless ``pipeline.load_model`` is set.
    """

    def __init__(
        self, pipeline: Pipeline, path: str, *, size: tuple[float, float] = (100, 0)
    ) -> None:
        self._pipeline = pipeline
        self._path = path
        self._size = size

    def ui(self) -> None:
        """Render the Load button. Call once per frame."""
        _render_load_model_button(self._pipeline, self._path, self._size)


class PipelinePanel:
    """Train + Predict + log as a single titled panel.

    Matches the visual style of :class:`RecordingControls`,
    :class:`SessionManager`, and :class:`PostProcessor`. The log inherits the
    same autoscroll + popout UX as the process launcher's log.
    """

    def __init__(
        self, pipeline: Pipeline, *, log_height: float = 80.0, widget_id: str = "ml"
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
