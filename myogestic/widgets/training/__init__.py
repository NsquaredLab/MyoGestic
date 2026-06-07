"""Training-workflow widgets: feature selection, session management, trial previews."""

from myogestic.widgets.training.feature_selector import FeatureSelector
from myogestic.widgets.training.prediction_label import prediction_label
from myogestic.widgets.training.session_manager import session_manager
from myogestic.widgets.training.template_inspector import (
    TemplateInspectorRow,
    template_inspector,
)
from myogestic.widgets.training.trial_preview import trial_preview

__all__ = [
    "FeatureSelector",
    "TemplateInspectorRow",
    "prediction_label",
    "session_manager",
    "template_inspector",
    "trial_preview",
]
