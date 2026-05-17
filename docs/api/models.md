# Models

`myogestic.models` ships **constructor recipes** for third-party estimators - thin wrappers that return a fitted-or-fittable object (`.fit(X, y)` + `.predict(X)`) with sane defaults. The library never owns the model lifecycle; that stays in your `@pipeline.train`. Optional dependencies are imported lazily, and each constructor raises a clear `ImportError` naming the extra to install.

## CatBoost

::: myogestic.models.catboost_classifier

::: myogestic.models.catboost_regressor

## scikit-learn

::: myogestic.models.sklearn_classifier

::: myogestic.models.sklearn_regressor

::: myogestic.models.sklearn_extra_trees_classifier

::: myogestic.models.sklearn_extra_trees_regressor

::: myogestic.models.sklearn_logistic_classifier

## Dummy estimators (zero deps)

::: myogestic.models.constant_classifier

::: myogestic.models.mean_regressor

## Persistence

::: myogestic.models.save_model

::: myogestic.models.load_model
