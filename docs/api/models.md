# Estimator recipes

`myogestic.recipes.estimators` ships **constructor recipes** for third-party estimators - thin wrappers that return a fitted-or-fittable object (`.fit(X, y)` + `.predict(X)`) with sane defaults. The library never owns the model lifecycle; that stays in your `@pipeline.train`. Optional dependencies are imported lazily, and each constructor raises a clear `ImportError` naming the extra to install.

To persist a trained model, use `myogestic.ml.save_pickle` / `load_pickle` (see the [ML API](ml.md)).

## CatBoost

::: myogestic.recipes.estimators.catboost_classifier

::: myogestic.recipes.estimators.catboost_regressor

## scikit-learn

::: myogestic.recipes.estimators.sklearn_classifier

::: myogestic.recipes.estimators.sklearn_regressor

::: myogestic.recipes.estimators.sklearn_extra_trees_classifier

::: myogestic.recipes.estimators.sklearn_extra_trees_regressor

::: myogestic.recipes.estimators.sklearn_logistic_classifier

## Dummy estimators (zero deps)

::: myogestic.recipes.estimators.constant_classifier

::: myogestic.recipes.estimators.mean_regressor
