"""Estimator constructor *recipes* — first-party, swappable starting points.

**Constructor recipes** for third-party estimators (CatBoost, scikit-learn).
Each returns a fitted-or-fittable object (``.fit(X, y)`` + ``.predict(X)``)
that user training code can use directly. The library never owns the model
lifecycle — that stays in the user's ``@pipeline.train``.

Optional dependencies (``catboost``, ``scikit-learn``) are imported lazily.
Constructors raise a clear ImportError naming the extra to install.

See also: `myogestic.ml.save_pickle` / `load_pickle` for persisting a trained
model, and `myogestic.recipes.features` for feature recipes.
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = [
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


def _require(module: str, extra: str, pip_name: str | None = None) -> Any:
    """Import a module or raise a friendly error pointing at the extra."""
    try:
        return __import__(module, fromlist=["*"])
    except ImportError as e:
        install = pip_name or module.split(".")[0]
        raise ImportError(
            f"{module} is not installed. Install it with "
            f"`uv sync --extra {extra}` (or `pip install {install}`)."
        ) from e


# --- CatBoost ---------------------------------------------------------------


def catboost_classifier(**kwargs: Any) -> Any:
    """CatBoostClassifier with quiet defaults."""
    cb = _require("catboost", "examples")
    kwargs.setdefault("verbose", 0)
    kwargs.setdefault("allow_writing_files", False)
    return cb.CatBoostClassifier(**kwargs)


def catboost_regressor(**kwargs: Any) -> Any:
    """CatBoostRegressor with quiet defaults."""
    cb = _require("catboost", "examples")
    kwargs.setdefault("verbose", 0)
    kwargs.setdefault("allow_writing_files", False)
    return cb.CatBoostRegressor(**kwargs)


# --- scikit-learn -----------------------------------------------------------


def sklearn_classifier(**kwargs: Any) -> Any:
    """RandomForestClassifier (sklearn)."""
    skl = _require("sklearn.ensemble", "dev", pip_name="scikit-learn")
    return skl.RandomForestClassifier(**kwargs)


def sklearn_regressor(**kwargs: Any) -> Any:
    """RandomForestRegressor (sklearn)."""
    skl = _require("sklearn.ensemble", "dev", pip_name="scikit-learn")
    return skl.RandomForestRegressor(**kwargs)


def sklearn_extra_trees_classifier(**kwargs: Any) -> Any:
    """ExtraTreesClassifier (sklearn). Defaults n_estimators=300, n_jobs=-1."""
    skl = _require("sklearn.ensemble", "dev", pip_name="scikit-learn")
    kwargs.setdefault("n_estimators", 300)
    kwargs.setdefault("random_state", 0)
    kwargs.setdefault("n_jobs", -1)
    return skl.ExtraTreesClassifier(**kwargs)


def sklearn_extra_trees_regressor(**kwargs: Any) -> Any:
    """ExtraTreesRegressor (sklearn). Same defaults as the classifier."""
    skl = _require("sklearn.ensemble", "dev", pip_name="scikit-learn")
    kwargs.setdefault("n_estimators", 300)
    kwargs.setdefault("random_state", 0)
    kwargs.setdefault("n_jobs", -1)
    return skl.ExtraTreesRegressor(**kwargs)


def sklearn_logistic_classifier(**kwargs: Any) -> Any:
    """Multinomial LogisticRegression (sklearn). max_iter=1000 default."""
    skl = _require("sklearn.linear_model", "dev", pip_name="scikit-learn")
    kwargs.setdefault("max_iter", 1000)
    return skl.LogisticRegression(**kwargs)


# --- Dummy estimators (zero deps) ------------------------------------------


class _ConstantClassifier:
    """Always predicts a fixed class. Use as a placeholder for wiring tests."""

    def __init__(self, class_idx: int = 0) -> None:
        self.class_idx = int(class_idx)
        self._n_classes: int = max(self.class_idx + 1, 2)

    def fit(self, X: np.ndarray, y: np.ndarray) -> _ConstantClassifier:
        if y is not None and len(y):
            self._n_classes = max(int(np.max(y)) + 1, self._n_classes)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.full(X.shape[0], self.class_idx, dtype=np.int64)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        proba = np.zeros((X.shape[0], self._n_classes), dtype=np.float64)
        proba[:, self.class_idx] = 1.0
        return proba


class _MeanRegressor:
    """Always predicts the mean of training y."""

    def __init__(self) -> None:
        self.mean_: np.ndarray | float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> _MeanRegressor:
        self.mean_ = np.asarray(y).mean(axis=0)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        mean = np.asarray(self.mean_)
        if mean.ndim == 0:
            return np.full(X.shape[0], float(mean), dtype=np.float64)
        return np.broadcast_to(mean, (X.shape[0], *mean.shape)).copy()


def constant_classifier(class_index: int = 0) -> _ConstantClassifier:
    """Estimator that always predicts ``class_index``. No deps."""
    return _ConstantClassifier(class_idx=class_index)


def mean_regressor() -> _MeanRegressor:
    """Estimator that predicts the mean of training targets. No deps."""
    return _MeanRegressor()
