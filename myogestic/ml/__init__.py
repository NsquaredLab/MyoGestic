"""Opt-in ML pipeline layer for myogestic.

Core ``App`` knows only idle ↔ recording. Create a :class:`Pipeline` (via
``Pipeline(app)``) to add the training/predicting lifecycle plus a predict
daemon thread. See :class:`~myogestic.ml.pipeline.Pipeline` for the full
decorator workflow, and :mod:`myogestic.ml.widgets` for the matching widgets
(which take ``pipeline``, not ``app``).

For estimator constructor recipes and feature recipes see
:mod:`myogestic.recipes`; model persistence helpers (``save_pickle`` /
``load_pickle``) are re-exported here.
"""

from myogestic.ml.persistence import load_pickle, save_pickle
from myogestic.ml.pipeline import Pipeline, PipelineState

__all__ = ["Pipeline", "PipelineState", "load_pickle", "save_pickle"]
