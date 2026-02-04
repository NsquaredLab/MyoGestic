Models
==============================
MyoGestic supports following models out of the box: CatBoost, Sklearn, and RaulNet.

Each model is registered with :class:`~myogestic.utils.config.Registry` and must
provide four functions: **train**, **save**, **load**, and **predict**.

Classifier vs Regressor
--------------------------
Models are registered with ``is_classifier=True`` or ``is_classifier=False``.
Classifiers predict a single integer label (e.g., gesture class), while
regressors predict a vector of continuous values (e.g., joint angles).  The
``is_classifier`` flag determines which output-processing path the
:class:`~myogestic.gui.widgets.templates.OutputSystemTemplate` uses at
runtime.

Temporal Preservation
--------------------------
Some models (e.g., RaulNet CNNs) operate on time-series windows and require
features that **preserve the temporal dimension**.  These models are
registered with ``requires_temporal_preservation=True`` and
``feature_window_size=<int>``.  The Training UI uses these flags to filter
the feature list so that only compatible features are shown.

.. note::
   To add a new model type, implement the four functions and register it
   via :meth:`~myogestic.utils.config.Registry.register_model`.  See the
   :doc:`/auto_examples/01_add_functionality/2_add_model` tutorial for a
   step-by-step guide.

CatBoost
--------------------------
.. currentmodule:: myogestic.models.definitions.catboost_models
.. autosummary::
    :toctree: generated/catboost
    :template: function.rst

    train
    save
    load
    predict

Sklearn
--------------------------
.. currentmodule:: myogestic.models.definitions.sklearn_models
.. autosummary::
    :toctree: generated/sklearn
    :template: function.rst

    train
    save
    load
    predict

RaulNet
--------------------------
.. currentmodule:: myogestic.models.definitions.raulnet_models
.. autosummary::
    :toctree: generated/raulnet
    :template: function.rst

    train
    save
    load
    predict


