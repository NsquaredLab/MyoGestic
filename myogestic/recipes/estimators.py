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
    "directional_decoder",
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
    """CatBoostClassifier with quiet defaults.

    Examples
    --------
    >>> from myogestic.recipes.estimators import catboost_classifier
    >>> model = catboost_classifier(iterations=100)
    """
    cb = _require("catboost", "examples")
    kwargs.setdefault("verbose", 0)
    kwargs.setdefault("allow_writing_files", False)
    return cb.CatBoostClassifier(**kwargs)


def catboost_regressor(**kwargs: Any) -> Any:
    """CatBoostRegressor with quiet defaults.

    Examples
    --------
    >>> from myogestic.recipes.estimators import catboost_regressor
    >>> model = catboost_regressor(iterations=200, loss_function="MultiRMSE")
    """
    cb = _require("catboost", "examples")
    kwargs.setdefault("verbose", 0)
    kwargs.setdefault("allow_writing_files", False)
    return cb.CatBoostRegressor(**kwargs)


# --- scikit-learn -----------------------------------------------------------


def sklearn_classifier(**kwargs: Any) -> Any:
    """RandomForestClassifier (sklearn).

    Examples
    --------
    >>> from myogestic.recipes.estimators import sklearn_classifier
    >>> model = sklearn_classifier(n_estimators=200, random_state=0)
    """
    skl = _require("sklearn.ensemble", "examples", pip_name="scikit-learn")
    return skl.RandomForestClassifier(**kwargs)


def sklearn_regressor(**kwargs: Any) -> Any:
    """RandomForestRegressor (sklearn).

    Examples
    --------
    >>> from myogestic.recipes.estimators import sklearn_regressor
    >>> model = sklearn_regressor(n_estimators=200, random_state=0)
    """
    skl = _require("sklearn.ensemble", "examples", pip_name="scikit-learn")
    return skl.RandomForestRegressor(**kwargs)


def sklearn_extra_trees_classifier(**kwargs: Any) -> Any:
    """ExtraTreesClassifier (sklearn). Defaults n_estimators=300, n_jobs=-1.

    Examples
    --------
    >>> from myogestic.recipes.estimators import sklearn_extra_trees_classifier
    >>> model = sklearn_extra_trees_classifier()
    """
    skl = _require("sklearn.ensemble", "examples", pip_name="scikit-learn")
    kwargs.setdefault("n_estimators", 300)
    kwargs.setdefault("random_state", 0)
    kwargs.setdefault("n_jobs", -1)
    return skl.ExtraTreesClassifier(**kwargs)


def sklearn_extra_trees_regressor(**kwargs: Any) -> Any:
    """ExtraTreesRegressor (sklearn). Same defaults as the classifier.

    Examples
    --------
    >>> from myogestic.recipes.estimators import sklearn_extra_trees_regressor
    >>> model = sklearn_extra_trees_regressor()
    """
    skl = _require("sklearn.ensemble", "examples", pip_name="scikit-learn")
    kwargs.setdefault("n_estimators", 300)
    kwargs.setdefault("random_state", 0)
    kwargs.setdefault("n_jobs", -1)
    return skl.ExtraTreesRegressor(**kwargs)


def sklearn_logistic_classifier(**kwargs: Any) -> Any:
    """Multinomial LogisticRegression (sklearn). max_iter=1000 default.

    Examples
    --------
    >>> from myogestic.recipes.estimators import sklearn_logistic_classifier
    >>> model = sklearn_logistic_classifier()
    """
    skl = _require("sklearn.linear_model", "examples", pip_name="scikit-learn")
    kwargs.setdefault("max_iter", 1000)
    return skl.LogisticRegression(**kwargs)


# --- Dummy estimators (zero deps) ------------------------------------------


class _ConstantClassifier:
    """Always predicts a fixed class. Use as a placeholder for wiring tests."""

    def __init__(self, class_index: int = 0) -> None:
        self.class_index = int(class_index)
        self._n_classes: int = max(self.class_index + 1, 2)

    def fit(self, X: np.ndarray, y: np.ndarray) -> _ConstantClassifier:
        if y is not None and len(y):
            self._n_classes = max(int(np.max(y)) + 1, self._n_classes)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.full(X.shape[0], self.class_index, dtype=np.int64)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        proba = np.zeros((X.shape[0], self._n_classes), dtype=np.float64)
        proba[:, self.class_index] = 1.0
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
    """Estimator that always predicts ``class_index``. No deps.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.recipes.estimators import constant_classifier
    >>> model = constant_classifier(1)
    >>> model.predict(np.zeros((2, 3), dtype=np.float32)).tolist()
    [1, 1]
    """
    return _ConstantClassifier(class_index=class_index)


def mean_regressor() -> _MeanRegressor:
    """Estimator that predicts the mean of training targets. No deps.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.recipes.estimators import mean_regressor
    >>> model = mean_regressor()
    >>> _ = model.fit(np.zeros((2, 1), dtype=np.float32), np.array([1.0, 3.0]))
    >>> model.predict(np.zeros((2, 1), dtype=np.float32)).tolist()
    [2.0, 2.0]
    """
    return _MeanRegressor()


# --- Directional decoder (zero deps) ----------------------------------------

#: Floor for the row sum, so an all-zero window normalises to zeros instead of NaN,
#: and ridge on the covariance diagonal, so a dead channel (identically zero, hence
#: zero variance) cannot make the solve singular.
_EPS = 1e-12

#: Smallest ``abs(y)`` a window may have and still be used to estimate the effort span.
#: The span estimate divides by ``abs(y)``, so it multiplies that window's noise by
#: ``1 / abs(y)``; at half deflection the amplification is capped at 2x. See `Notes` in
#: `directional_decoder` for the measured bias/count trade-off against other values.
_STRONG_TARGET = 0.5

#: Fewest windows over `_STRONG_TARGET` the span estimate will accept. Three is the
#: smallest count at which a median can reject a single bad window — with two it is the
#: mean of the only two values there are, which is not what the rule asked for. A floor
#: against nonsense, not a claim of precision: see `Notes`.
_MIN_STRONG_WINDOWS = 3


def _effort_and_shape(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split a non-negative feature matrix into row totals and unit-sum rows."""
    X = np.asarray(X, dtype=np.float64)
    total = X.sum(axis=1)
    return total, X / np.maximum(total, _EPS)[:, None]


class _DirectionalDecoder:
    """Signed command as ``activation x direction``. See `directional_decoder`."""

    def __init__(self, shrinkage: float = 0.1) -> None:
        if not 0.0 <= shrinkage <= 1.0:  # False for NaN too, which is the point
            raise ValueError(
                "shrinkage is the fraction of the way from the pooled covariance to "
                f"its own diagonal: pass a number in 0.0..1.0, not {shrinkage!r}. "
                "The default 0.1 is a fine starting point."
            )
        self.shrinkage = float(shrinkage)
        self.rest_: float = 0.0
        self.span_: float = 1.0
        self.w_: np.ndarray = np.zeros(0, dtype=np.float64)
        self.mid_: float = 0.0
        self.scale_: float = 1.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> _DirectionalDecoder:
        """Learn the rest/span effort scale and the Fisher direction axis.

        Parameters
        ----------
        X
            ``(n_windows, n_features)``, non-negative and growing with contraction.
        y
            Signed target in [-1, +1], one per window. ``0`` marks a rest window.
            Both the *sign* and the *magnitude* are used: the sign groups the windows
            into the two directions, and the magnitude says how much of a full
            contraction each one asked for, which is what sets the effort span. A
            block of only -1 / 0 / +1 is the special case where every magnitude is 1.

        Raises
        ------
        ValueError
            If any ``abs(y)`` exceeds 1 — a target in the wrong units, which no other
            guard here can see — if either sign or the rest windows are missing, if
            fewer than ``_MIN_STRONG_WINDOWS`` windows reach
            ``abs(y) >= _STRONG_TARGET``, if the contraction windows are no louder than
            rest, or if the two directions share the same amplitude-normalised mean.
        """
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64).ravel()
        if X.ndim != 2 or len(X) != len(y):
            raise ValueError(
                f"X must be (n_windows, n_features) with one y per window; "
                f"got X{X.shape} and y{y.shape}."
            )
        # Before the guards below, not after: every one of them is a `<= 0` test, and
        # `nan <= 0` is False, so a single NaN sails through all of them and comes back
        # out of `predict` on *every* window, not just the bad one.
        if not np.isfinite(X).all():
            raise ValueError(
                f"X has {int((~np.isfinite(X)).sum())} non-finite value(s) (NaN or inf). "
                "Drop those windows before fitting — a NaN here fits without complaint "
                "and then makes every later prediction NaN."
            )
        # Every guard below is a `<= 0` test on something derived from `y`, and none of
        # them notices a `y` in the wrong *units*. A percent-of-MVC target — what
        # `Trapezoid` records, on a stream named and shaped exactly like a `Pursuit`
        # one — divides through `span_` at up to 100 instead of 1, collapsing it by two
        # orders of magnitude, and `activation` then saturates on everything: the graded
        # command becomes a three-step staircase and the fit reports no problem at all.
        peak = float(np.abs(y).max()) if y.size else 0.0
        if peak > 1.0:
            raise ValueError(
                f"y must be the signed target in [-1, +1] and reaches {peak:.4g}. That "
                "is a percent-of-MVC or raw-unit target; rescale it to the signed "
                "control range, or drop the recording it came from."
            )
        missing = [
            label
            for label, present in (
                ("negative windows (y < 0)", bool(np.any(y < 0))),
                ("positive windows (y > 0)", bool(np.any(y > 0))),
                ("rest windows (y == 0)", bool(np.any(y == 0))),
            )
            if not present
        ]
        if missing:
            raise ValueError(
                "directional_decoder needs both directions and a rest block; missing "
                + " and ".join(missing)
                + ". Record the missing block and fit again."
            )

        total, shape = _effort_and_shape(X)
        self.rest_ = float(np.median(total[y == 0]))
        # Span *per unit of target*, estimated on each window and pooled by median —
        # not `median(total[y != 0]) - rest_`, which reads every non-rest window as a
        # full contraction and so collapses the scale on a graded block. On a discrete
        # block every non-rest window has abs(y) == 1 and the two rules coincide
        # exactly; see `Notes` in `directional_decoder`.
        strong = np.abs(y) >= _STRONG_TARGET
        if int(strong.sum()) < _MIN_STRONG_WINDOWS:
            raise ValueError(
                f"the effort span needs at least {_MIN_STRONG_WINDOWS} windows whose target "
                f"reaches abs(y) >= {_STRONG_TARGET}, and this block has {int(strong.sum())} "
                f"(largest target abs(y) = {float(np.abs(y).max()):.3g}). The span is read off "
                "each window as (total - rest) / abs(y), so a small target multiplies that "
                "window's noise by 1 / abs(y). Record targets that ask for at least half "
                "deflection."
            )
        self.span_ = float(np.median((total[strong] - self.rest_) / np.abs(y[strong])))
        if self.span_ <= 0.0:
            raise ValueError(
                f"contraction windows are not louder than rest (fitted span {self.span_:.6g} "
                f"per unit of target, against a rest level of {self.rest_:.6g}); features must "
                "be non-negative and grow with contraction strength — RMS, MAV, WL, VAR."
            )

        # Every non-rest window, not just the `strong` ones. On a graded block a window
        # at abs(y) ~ 0.05 is shaped almost like rest, so it is fair to ask whether it
        # belongs in a Down-vs-Up mean at all — it was measured and it does not matter.
        # See `Notes` in `directional_decoder`; unlike the span, this is a *mean* of
        # shapes that is then affinely rescaled by `mid_` / `scale_`, so pulling both
        # class means toward rest shrinks a numerator and a denominator together.
        dn = shape[y < 0].mean(axis=0)
        up = shape[y > 0].mean(axis=0)
        deviations = np.vstack([shape[y < 0] - dn, shape[y > 0] - up])
        cov = deviations.T @ deviations / max(len(deviations) - 2, 1)
        # Shrink toward the diagonal, then ridge the diagonal. The *ridge* is what makes
        # the solve go through — every row of `shape` sums to 1, so `cov` is singular
        # along the all-ones direction by construction. Shrinkage is the bias/variance
        # knob on top of that, for n_features (channels x features) near n_windows; it
        # is not what saves the solve. See `Notes` in `directional_decoder`.
        cov = (1.0 - self.shrinkage) * cov + self.shrinkage * np.diag(np.diag(cov))
        cov[np.diag_indices_from(cov)] += _EPS
        self.w_ = np.linalg.solve(cov, up - dn)

        lo, hi = float(self.w_ @ dn), float(self.w_ @ up)
        self.mid_ = (lo + hi) / 2.0
        self.scale_ = (hi - lo) / 2.0
        if self.scale_ <= 0.0:
            raise ValueError(
                "the two directions have no separable spatial pattern — their "
                "amplitude-normalised means project onto the same point. Check that "
                "the sign of y matches the direction that was actually performed."
            )
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return one signed command in [-1, +1] per window."""
        if self.w_.size == 0:
            raise ValueError("directional_decoder is not fitted — call .fit(X, y) first.")
        total, shape = _effort_and_shape(X)
        activation = np.clip((total - self.rest_) / self.span_, 0.0, 1.0)
        direction = np.clip((shape @ self.w_ - self.mid_) / self.scale_, -1.0, 1.0)
        return activation * direction


def directional_decoder(*, shrinkage: float = 0.1) -> _DirectionalDecoder:
    """Bidirectional proportional control as ``command = activation x direction``. No deps.

    **Input contract, and it is not optional.** Every column of ``X`` must be
    **non-negative**, must **grow with contraction strength**, and must answer a gain
    on the electrodes **the same way as every other column**. Multiply the signal by
    ``g`` and RMS, MAV and WL all scale by ``g``; VAR scales by ``g**2`` and ZC not at
    all. So RMS, MAV and WL mix freely (the app default is RMS+MAV) and VAR is fine on
    its own, but a set spanning two of those groups is not: a mix is exactly what costs
    you the gain invariance in `Notes`. Signed or mean-centred features break the split
    outright: the row sum stops being effort and the normalised row stops being a
    spatial pattern.

    Parameters
    ----------
    shrinkage
        How far the pooled within-class covariance is pulled toward its own diagonal,
        0.0..1.0. A conditioning knob, not a correctness requirement — see `Notes`.

    Returns
    -------
    _DirectionalDecoder
        Object with ``.fit(X, y)`` / ``.predict(X)``. ``y`` is the signed target in
        [-1, +1], with ``0`` marking rest; ``predict`` returns one signed command per
        window, also in [-1, +1].

    Notes
    -----
    Effort and direction do not live in the same place, and one regressor over raw
    features conflates them. Measured on three 8-channel bracelet recordings (one take
    each of Down / Rest / Up, 68 windows): overall amplitude barely separates Down from
    Up at all, **d' = 0.52**, with total RMS 4091 / 1188 / 3727 and heavily overlapping
    ranges. The **amplitude-normalised** pattern separates the very same windows
    cleanly — per-channel Down-vs-Up **d' reaches 10.9** (channel 6) and **8.2**
    (channel 4), 0-indexed as the viewer labels them.

    So amplitude says *how much* and the spatial pattern says *which way*. A regressor
    handed the raw features learns whichever cue is louder in the training set: the
    shipped CatBoost regressor learned "louder = Down", because Down simply happened to
    be recorded harder, and its output is therefore non-monotonic in effort — scaling
    every channel by 1.0 -> 1.3 -> 1.6 moved its Up prediction 1.000 -> 0.882 -> 0.723.
    Contract harder, the paddle goes down. It was also dead below ~30% effort.

    Here the two cues are estimated apart and multiplied. ``activation`` is the row
    total rescaled so rest reads 0 and a *full* contraction reads 1; ``direction`` is
    the row's unit-sum shape projected onto the Fisher axis from the mean Down shape to
    the mean Up shape.

    **The effort span is fitted per window, and that is what lets a graded block work.**
    ``span_`` is ``median((total - rest_) / abs(y))`` over the windows whose target
    reaches ``abs(y) >= _STRONG_TARGET`` — *not* ``median(total[y != 0]) - rest_``, which
    is the same number only if every non-rest window is a full contraction. On a
    `myogestic.tracking.Pursuit` block the median non-rest window sits at ``abs(y) =
    0.358``, so the old rule fitted a span of **1.76** against a true **4.23**,
    ``activation`` saturated, and the command pegged at about 40% effort — the paddle
    stopped answering the subject. Transfer curve over nine held levels: **MAE 0.179 and
    non-monotone** (every level past ±0.5 read a hard ±1) under the old rule, **0.084 and
    strictly monotone** under this one, from the identical recording.

    It costs the cued protocol nothing, and the algebra of that is exact rather than
    approximate. There every non-rest window has ``abs(y) == 1``, so ``abs(y) >= 0.5``
    selects the same windows as ``y != 0``, dividing by 1 is a no-op, and a median is
    translation-equivariant — ``median(total - rest_) == median(total) - rest_``. On the
    three cued blocks both rules return ``span_ = 4.254340690``, the same float. Bit-for-
    bit sameness needs an *odd* number of qualifying windows, which is the only place the
    equivalence is arithmetic rather than algebraic: on an even count ``numpy.median``
    averages the two middle elements and ``((a - c) + (b - c)) / 2`` is not
    ``(a + b) / 2 - c`` in float64. Measured over 2000 even-count trials the two rules
    differ in 34% of them by at most 1.8e-15, and in 0 of 2000 odd-count ones.

    ``_STRONG_TARGET`` trades bias for count. The division amplifies a window's noise by
    ``1 / abs(y)``, and an EMG baseline adds to the row total without scaling with
    effort, so low-target windows read *high*: on the block above the fitted span runs
    4.40 / **4.29** / 4.24 / 4.22 at thresholds 0.25 / **0.50** / 0.75 / 0.90 against the
    4.23 reference, on 301 / **165** / 68 / 25 windows. 0.5 caps the noise gain at 2x and
    lands 1.3% high while keeping a third of the block; 0.75 would shave that to 0.1% at
    a fifth of the windows, which is the wrong side of the trade for a short recording.
    ``_MIN_STRONG_WINDOWS`` is a floor against nonsense rather than a precision claim —
    resampling those ratios, the span error is 9% median / 27% at the 90th percentile at
    three windows against 15% / 46% at one, and a real pursuit block clears the bar 55
    times over — 165 qualifying windows against a floor of 3. Below the floor `fit`
    raises instead of falling back to a looser
    threshold: a span quietly fitted on two windows is a decoder that feels wrong on the
    subject's first trial with nothing in the log to say why.

    The **direction** estimate, by contrast, still uses *every* non-rest window. A window
    at ``abs(y) = 0.05`` is shaped almost like rest and has no business in a Down-vs-Up
    contrast, so restricting it to the same strong windows was measured over five
    train/probe seed pairs: mean MAE 0.0820 (all) against 0.0812 (strong), a 1%
    difference that swaps sign across levels — restricting reads ±0.5 better and ±0.25
    worse — for two-thirds fewer rows in the covariance. No effect worth a second rule.
    The asymmetry with ``span_`` is structural: the span divides by ``abs(y)``, so a
    small target directly inflates one estimate, whereas the direction takes a *mean* of
    shapes that ``mid_`` and ``scale_`` then affinely rescale, and pulling both class
    means toward rest shrinks a numerator and its denominator together. A global gain on the electrodes multiplies **every column by the
    same factor** — that is what the input contract above buys — so it cancels out of
    the unit-sum shape exactly, leaves ``direction`` untouched and can only *raise*
    ``activation``. Break that contract and the cancellation goes with it: ticking VAR
    (degree 2) beside RMS+MAV (degree 1) on the recordings above walks the mean Up
    command 0.913 -> 0.901 -> 0.875 -> 0.837 as the gain rises 1.3 -> 3.0, where
    RMS+MAV holds 0.951 flat to float32 noise. That is the same failure as the
    regressor above, from the same cause — one number standing in for two.

    ``shrinkage`` is a conditioning knob, not a correctness requirement. Shape rows sum
    to 1, so the within-class covariance is singular along the all-ones direction
    whatever the window count — but that direction is constant across *every* row, so
    the component the diagonal ridge (``_EPS``) leaves ``w_`` pointing along it adds the
    same offset to every projection and ``mid_`` subtracts it again. Held-out sign
    accuracy on the recordings above is 100% at every value from 0.0 to 1.0. What it
    does buy is the other end: at ``1.0`` the solve is a plain per-feature weighting,
    which cannot cancel a within-class mode shared *across* features — a cuff shifting
    on the arm — the way the full solve can. Raise it toward 1 when n_features runs past
    the window count and the axis wanders between takes; the 0.1 default keeps nearly
    all of the solve.

    Rest needs no dead-zone hack — ``activation`` is 0 at the fitted rest level, so the
    command is exactly 0 there no matter what the (meaningless) direction estimate says.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.recipes.estimators import directional_decoder
    >>> down = np.array([[4.0, 4.0, 1.0, 1.0], [3.0, 5.0, 1.0, 1.0]])
    >>> up = np.array([[1.0, 1.0, 4.0, 4.0], [1.0, 1.0, 5.0, 3.0]])
    >>> rest = np.array([[0.5, 0.5, 0.5, 0.5], [0.5, 0.5, 0.5, 0.5]])
    >>> y = np.array([-1.0, -1.0, 1.0, 1.0, 0.0, 0.0])
    >>> model = directional_decoder().fit(np.vstack([down, up, rest]), y)
    >>> a, b, c = model.predict(np.vstack([down.mean(0), rest.mean(0), up.mean(0)]))
    >>> round(float(a), 3), round(abs(float(b)), 3), round(float(c), 3)
    (-1.0, 0.0, 1.0)

    A far quieter Up contraction still reads Up — loudness sets the magnitude, never
    the sign:

    >>> quiet_up = up.mean(0) / 3.0 + rest.mean(0)
    >>> command = float(model.predict(quiet_up[None])[0])
    >>> round(command, 2), command > 0.0
    (0.26, True)
    """
    return _DirectionalDecoder(shrinkage=shrinkage)
