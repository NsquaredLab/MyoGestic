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

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import joblib

if TYPE_CHECKING:
    from myogestic.controls import ControlMap


def _sidecar(path: str | Path) -> Path:
    """Where a model's control-space provenance lives, beside the model itself."""
    return Path(str(path) + ".controls.json")


def save_pickle(model: Any, path: str | Path, *, controls: ControlMap | None = None) -> str:
    """Persist ``model`` to ``path`` via joblib, creating parent dirs as needed.

    Returns the path as a string.

    Parameters
    ----------
    model
        Any picklable object.
    path
        Destination file.
    controls
        Optional `myogestic.controls.ControlMap` the model was trained against,
        written to a ``<path>.controls.json`` sidecar. A model is only meaningful
        in the output space it was fitted for: loading one trained on a one-way
        ``[0, 1]`` DOF against a signed ``[-1, 1]`` configuration produces motion
        in a direction the model never learned, and nothing in the artifact itself
        would say so. A sidecar keeps `load_pickle`'s signature and leaves older
        artifacts loadable.

    Examples
    --------
    >>> from myogestic.ml import save_pickle
    >>> save_pickle({"classes": 2}, "models/demo.joblib")
    'models/demo.joblib'
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, str(p))
    if controls is not None:
        _sidecar(p).write_text(json.dumps(controls.as_control_space(), indent=2))
    return str(p)


def load_pickle(
    path: str | Path,
    *,
    controls: ControlMap | None = None,
    allow_unverified: bool = False,
) -> Any:
    """Inverse of [`save_pickle`][] — load a joblib-saved model.

    Parameters
    ----------
    path
        The model file.
    controls
        Optional `myogestic.controls.ControlMap` to check the model against. When
        given, the model's sidecar must describe the same control space, or this
        raises rather than driving a target through a space the model never saw.
        Wire it in one line::

            pipeline.load_model = partial(load_pickle, controls=CONTROLS)
    allow_unverified
        Permit loading a model that carries no sidecar even though ``controls``
        was supplied. Off by default: an artifact saved before provenance existed
        cannot be distinguished from one trained in a different space, and
        silently accepting it is how a polarity change ships.

    Raises
    ------
    ValueError
        If the sidecar disagrees with ``controls``, or is absent without
        ``allow_unverified``.

    Examples
    --------
    >>> from myogestic.ml import load_pickle
    >>> model = load_pickle("models/demo.joblib")
    >>> model["classes"]
    2
    """
    if controls is not None:
        from myogestic.controls import read_control_space

        side = _sidecar(path)
        if not side.exists():
            if not allow_unverified:
                raise ValueError(
                    f"{path} has no control-space sidecar ({side.name}), so it cannot be "
                    f"checked against the current configuration. Retrain with "
                    f"save_pickle(..., controls=...), or pass allow_unverified=True to "
                    f"load it anyway."
                )
        else:
            recorded = read_control_space(json.loads(side.read_text()))
            if recorded != controls:
                raise ValueError(
                    f"{path} was trained for {list(recorded.bindings)} but the current "
                    f"configuration declares {list(controls.bindings)}. Restore that "
                    f"configuration, or retrain."
                )
    return joblib.load(str(path))
