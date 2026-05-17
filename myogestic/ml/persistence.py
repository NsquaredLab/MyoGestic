"""Generic pickle helpers for ``pipeline.save_model`` / ``pipeline.load_model``.

Any model the user assigns to ``pipeline.model`` (the value returned from
``@pipeline.train``) can be persisted with these helpers as long as the model
is pickleable. Numba-JIT'd ``@njit`` functions referenced by the model are not
pickled because they live at module scope, so a model that only holds NumPy
arrays + primitives + dataclasses round-trips cleanly.

Wire up like:

    from myogestic.ml import save_pickle, load_pickle
    pipeline.save_model = save_pickle
    pipeline.load_model = load_pickle

Then ``save_model_button`` / ``load_model_button`` in ``myogestic.ml.widgets``
work without the example needing custom save/load code.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any


def save_pickle(model: Any, path: str | Path) -> str:
    """Pickle ``model`` to ``path``. Creates parent directories if needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as f:
        pickle.dump(model, f)
    return str(p)


def load_pickle(path: str | Path) -> Any:
    """Inverse of ``save_pickle``."""
    with Path(path).open("rb") as f:
        return pickle.load(f)
