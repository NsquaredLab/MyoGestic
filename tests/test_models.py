"""Tests for myogestic.models — recipes, optional-dep errors, persistence."""

from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pytest

from myogestic import models

# --- Dummy estimators (no optional deps) ------------------------------------


def test_constant_classifier_predicts_fixed_class():
    clf = models.constant_classifier(class_idx=2)
    X = np.zeros((5, 3))
    y = np.array([0, 1, 2, 1, 2])
    clf.fit(X, y)
    assert np.all(clf.predict(X) == 2)
    proba = clf.predict_proba(X)
    assert proba.shape == (5, 3)
    assert np.allclose(proba[:, 2], 1.0)
    assert np.allclose(proba[:, [0, 1]], 0.0)


def test_mean_regressor_returns_mean_per_dim():
    reg = models.mean_regressor()
    X = np.random.default_rng(0).standard_normal((10, 4))
    y = np.array([[1.0, 2.0], [3.0, 6.0], [5.0, 4.0]])
    reg.fit(np.zeros((3, 4)), y)
    pred = reg.predict(X)
    assert pred.shape == (10, 2)
    assert np.allclose(pred[0], y.mean(axis=0))


def test_save_and_load_dummy_round_trip(tmp_path: Path):
    reg = models.mean_regressor()
    reg.fit(np.zeros((3, 2)), np.array([1.0, 2.0, 3.0]))
    p = tmp_path / "m.joblib"
    out = models.save_model(reg, str(p))
    assert Path(out).exists()
    loaded = models.load_model(str(p))
    assert isinstance(loaded, type(reg))
    assert np.allclose(loaded.predict(np.zeros((1, 2)))[0], 2.0)


# --- Optional-dep behavior --------------------------------------------------


def test_catboost_constructors_when_installed():
    """If CatBoost is installed (dev/examples extras), the constructor returns
    a real estimator with quiet defaults applied."""
    cb = pytest.importorskip("catboost")
    clf = models.catboost_classifier(iterations=1)
    reg = models.catboost_regressor(iterations=1)
    assert isinstance(clf, cb.CatBoostClassifier)
    assert isinstance(reg, cb.CatBoostRegressor)
    # Defaults applied:
    assert clf.get_params().get("verbose") == 0
    assert clf.get_params().get("allow_writing_files") is False


def test_sklearn_constructors_when_installed():
    skl = pytest.importorskip("sklearn.ensemble")
    clf = models.sklearn_classifier(n_estimators=2, random_state=0)
    reg = models.sklearn_regressor(n_estimators=2, random_state=0)
    assert isinstance(clf, skl.RandomForestClassifier)
    assert isinstance(reg, skl.RandomForestRegressor)


def test_extra_trees_constructors_when_installed():
    skl = pytest.importorskip("sklearn.ensemble")
    clf = models.sklearn_extra_trees_classifier(n_estimators=2)
    reg = models.sklearn_extra_trees_regressor(n_estimators=2)
    assert isinstance(clf, skl.ExtraTreesClassifier)
    assert isinstance(reg, skl.ExtraTreesRegressor)
    # Defaults applied (the override sets n_estimators; the rest stays).
    assert clf.get_params()["random_state"] == 0
    assert clf.get_params()["n_jobs"] == -1


def test_logistic_constructor_when_installed():
    lm = pytest.importorskip("sklearn.linear_model")
    clf = models.sklearn_logistic_classifier()
    assert isinstance(clf, lm.LogisticRegression)
    assert clf.get_params()["max_iter"] == 1000


def test_missing_sklearn_extra_trees_error_names_scikit_learn(monkeypatch):
    """The friendly ImportError must point at `scikit-learn`, not the import
    path `sklearn.ensemble` (which is not installable via pip)."""
    real_import = __import__

    def _block(name, *a, **kw):
        if name == "sklearn.ensemble" or name.startswith("sklearn.ensemble."):
            raise ImportError("blocked for test")
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", _block)
    importlib.reload(models)
    try:
        with pytest.raises(ImportError, match="scikit-learn"):
            models.sklearn_extra_trees_classifier()
    finally:
        monkeypatch.setattr("builtins.__import__", real_import)
        importlib.reload(models)


def test_missing_optional_dep_raises_import_error(monkeypatch):
    """When an optional dep is unavailable, the constructor should raise
    ImportError naming the extra to install — not crash with NameError or
    silently return None."""
    real_import = __import__

    def _block(name, *a, **kw):
        if name == "catboost" or name.startswith("catboost."):
            raise ImportError("blocked for test")
        return real_import(name, *a, **kw)

    # Force a clean reload of `models` against a patched __import__ so the
    # internal `_require("catboost", …)` triggers the friendly error path.
    monkeypatch.setattr("builtins.__import__", _block)
    importlib.reload(models)
    try:
        with pytest.raises(ImportError, match="catboost"):
            models.catboost_classifier()
        with pytest.raises(ImportError, match="catboost"):
            models.catboost_regressor()
    finally:
        # Restore real import + reload so other tests see the real module.
        monkeypatch.setattr("builtins.__import__", real_import)
        importlib.reload(models)
