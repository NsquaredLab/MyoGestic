"""Model persistence for ``pipeline.save_model`` / ``pipeline.load_model``.

The single serialization implementation for the library lives here: joblib
``dump`` / ``load`` (joblib is already a core dependency and handles picklable
estimators, including NumPy-heavy ones). ``save_pickle`` also creates parent
directories. The ``save_pickle`` / ``load_pickle`` names are distinct from the
``pipeline.save_model`` / ``pipeline.load_model`` hook *attributes* you assign
them to:

    from myogestic.ml import save_pickle, load_pickle
    pipeline.save_model = save_pickle
    pipeline.load_model = load_pickle

Then ``save_model_button`` / ``load_model_button`` in ``myogestic.ml.widgets``
work without the example needing custom save/load code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib


def save_pickle(model: Any, path: str | Path) -> str:
    """Persist ``model`` to ``path`` via joblib, creating parent dirs as needed.

    Returns the path as a string.

    Examples
    --------
    >>> from myogestic.ml import save_pickle
    >>> save_pickle({"classes": 2}, "models/demo.joblib")
    'models/demo.joblib'
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, str(p))
    return str(p)


def load_pickle(path: str | Path) -> Any:
    """Inverse of [`save_pickle`][] — load a joblib-saved model.

    Examples
    --------
    >>> from myogestic.ml import load_pickle
    >>> model = load_pickle("models/demo.joblib")
    >>> model["classes"]
    2
    """
    return joblib.load(str(path))
