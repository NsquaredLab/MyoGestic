Models
==============================
MyoGestic supports following models out of the box: CatBoost, Sklearn, and RaulNet.

All models have the following methods predefined: train, save, load, and predict.

.. note:: If you wish to add a new model type, you must provide these methods.

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


