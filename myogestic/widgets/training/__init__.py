"""Training-workflow widgets: feature selection, session management, trial previews."""

from myogestic.widgets.training.feature_selector import FeatureSelector
from myogestic.widgets.training.prediction_label import PredictionLabel
from myogestic.widgets.training.session_manager import SessionManager
from myogestic.widgets.training.template_inspector import (
    TemplateInspector,
    TemplateInspectorRow,
)
from myogestic.widgets.training.trial_preview import TrialPreview

__all__ = [
    "FeatureSelector",
    "PredictionLabel",
    "SessionManager",
    "TemplateInspector",
    "TemplateInspectorRow",
    "TrialPreview",
]
