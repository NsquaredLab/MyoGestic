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

## Bidirectional proportional control (zero deps)

One signed command in `[-1, +1]` for a bidirectional DOF - a wrist going down *or* up, not a wrist going more or less. Reach for this instead of a plain regressor whenever the target has two directions: overall amplitude says *how much*, it does not say *which way*, and a regressor handed raw features will happily learn the wrong one. `examples/start_here/pong.py` trains it as its default mode.

`y` is the signed target per window, and both its sign and its **magnitude** are read: the sign groups the windows into the two directions, the magnitude says how much of a full contraction each one asked for. The effort span is therefore fitted per window as `median((total - rest_) / abs(y))` over the windows reaching `abs(y) >= 0.5`, which is what lets a graded block work and costs a cued block nothing - there every non-rest window has `abs(y) == 1` and the two rules return the same float. `fit` **raises** if fewer than three windows clear that bar rather than fitting a span on two. [Record for proportional control](../how-to/record-for-proportional-control.md) covers what that means for the recording protocol.

::: myogestic.recipes.estimators.directional_decoder

## Dummy estimators (zero deps)

::: myogestic.recipes.estimators.constant_classifier

::: myogestic.recipes.estimators.mean_regressor
