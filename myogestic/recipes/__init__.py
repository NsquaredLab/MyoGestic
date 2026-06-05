"""First-party *recipes* — swappable starting points, deliberately not core.

The framework stays out of feature engineering and model choice. ``recipes``
is where small, replaceable starter implementations live so examples don't
re-implement them every time — treat anything here as a *starting point* you'll
usually swap or extend:

- ``recipes.features`` — time-domain EMG feature functions (rms, mav, wl, …).
- ``recipes.estimators`` — constructor recipes for CatBoost / scikit-learn
  (and zero-dependency dummy estimators).

For persisting a trained model, see ``myogestic.ml.save_pickle`` /
``load_pickle``.
"""

from myogestic.recipes.estimators import (
    catboost_classifier,
    catboost_regressor,
    constant_classifier,
    mean_regressor,
    sklearn_classifier,
    sklearn_extra_trees_classifier,
    sklearn_extra_trees_regressor,
    sklearn_logistic_classifier,
    sklearn_regressor,
)
from myogestic.recipes.features import mav, rms, var, wl, zc

__all__ = [
    # features
    "mav",
    "rms",
    "var",
    "wl",
    "zc",
    # estimators
    "catboost_classifier",
    "catboost_regressor",
    "constant_classifier",
    "mean_regressor",
    "sklearn_classifier",
    "sklearn_extra_trees_classifier",
    "sklearn_extra_trees_regressor",
    "sklearn_logistic_classifier",
    "sklearn_regressor",
]
