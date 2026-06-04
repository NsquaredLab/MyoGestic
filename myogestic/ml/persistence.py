"""Model-persistence hooks for ``pipeline.save_model`` / ``pipeline.load_model``.

The serialization itself lives in :mod:`myogestic.models` (joblib-based, which
handles picklable estimators including NumPy-heavy ones). These thin wrappers
add parent-directory creation and keep the ``save_pickle`` / ``load_pickle``
names used by the pipeline hook API, so there is a single serialization
implementation across the library.

Wire up like:

    from myogestic.ml import save_pickle, load_pickle
    pipeline.save_model = save_pickle
    pipeline.load_model = load_pickle

Then ``save_model_button`` / ``load_model_button`` in ``myogestic.ml.widgets``
work without the example needing custom save/load code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from myogestic.models import load_model, save_model


def save_pickle(model: Any, path: str | Path) -> str:
    """Persist ``model`` to ``path`` (joblib), creating parent dirs as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return save_model(model, str(p))


def load_pickle(path: str | Path) -> Any:
    """Inverse of :func:`save_pickle`."""
    return load_model(str(path))
