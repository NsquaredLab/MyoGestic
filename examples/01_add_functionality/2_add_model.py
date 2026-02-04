"""
===========================================================
Add a Model
===========================================================

This example shows how to register a new model (classifier or regressor)
in MyoGestic.  Every model needs four functions -- ``train``, ``predict``,
``save``, and ``load`` -- plus some metadata describing its parameters and
capabilities.

Models are registered through ``CONFIG_REGISTRY.register_model()``.  Once
registered, the model appears in the **Training** tab's model dropdown and
can be trained, saved, loaded, and used for real-time prediction.

Classifier vs Regressor
------------------------
MyoGestic distinguishes between **classifiers** and **regressors**:

- **Classifier** (``is_classifier=True``): Outputs a single integer label
  (e.g., ``0`` for rest, ``1`` for index finger).  Used with
  classification-based output systems.
- **Regressor** (``is_classifier=False``): Outputs a list of continuous
  values (e.g., joint angles).  Used with regression-based output systems
  and can be post-filtered.

Temporal Preservation
---------------------
Some models (e.g., RaulNet with CNN layers) require their input to
preserve the time dimension.  Standard features like RMS collapse the
time axis into a single value per channel, which is fine for
sklearn/CatBoost models but incompatible with CNNs.

When registering such a model, set:

- ``requires_temporal_preservation=True`` -- The Training UI will only
  show features that preserve the time dimension (e.g., Identity,
  RMS Small Window).
- ``feature_window_size=120`` -- Specifies the sliding window size for
  feature extraction, producing multiple time steps from a single buffer.

Parameters
----------
Models can define two kinds of parameters:

- **Changeable parameters** -- Exposed as spinboxes in the Training UI.
  Defined as dicts with ``start_value``, ``end_value``, ``step``, and
  ``default_value``.  See :ref:`changeable_parameter`.
- **Unchangeable parameters** -- Fixed values passed directly to the
  model constructor (e.g., ``kernel="rbf"``).  See
  :ref:`unchangeable_parameter`.

.. admonition:: Add your model in :mod:`~myogestic.user_config`

   Keep custom model registrations in :mod:`~myogestic.user_config` to stay separate
   from core MyoGestic code.

Example Overview
-----------------
1. **Define** the four required functions (save, load, train, predict).
2. **Register** the model with ``CONFIG_REGISTRY``.

"""

# %%
# ----------------------------------------
# Step 1: Define Save and Load Functions
# ----------------------------------------
# The ``save`` function receives a file path and the trained model object.
# It must persist the model to disk and return the path where it was saved.
#
# The ``load`` function receives a file path and a *fresh instance* of the
# model class.  It must return the loaded model object.

import joblib
import numpy as np


def save(model_path: str, model: object) -> str:
    """Save a sklearn-compatible model using joblib."""
    output_path = str(model_path).split(".")[0] + "_model.pkl"
    joblib.dump(model, output_path)
    return output_path


def load(model_path: str, model: object) -> object:
    """Load a sklearn-compatible model using joblib.

    The ``model`` argument is a fresh instance (unused here but required
    by the registry interface).
    """
    with open(model_path, "rb") as f:
        return joblib.load(f)


# %%
# --------------------------------------------
# Step 2: Define Train and Predict Functions
# --------------------------------------------
# ``train`` receives the model instance, a dataset dict (from the Zarr
# store), the ``is_classifier`` flag, and a logger.  It must return the
# trained model.
#
# ``predict`` receives the model, a single input sample, and the
# ``is_classifier`` flag.  It must return:
#
# - For classifiers: a single integer label.
# - For regressors: a list of floats (one per DOF).

from myogestic.gui.widgets.logger import CustomLogger


def train(model: object, dataset: dict, is_classifier: bool, logger: CustomLogger) -> object:
    """Train a sklearn-compatible model.

    Parameters
    ----------
    model : object
        Fresh model instance (constructed from ``model_class`` with the
        registered parameters).
    dataset : dict
        Zarr-backed dataset with keys ``"emg"`` (shape
        ``(n_samples, n_features*channels, time)``), ``"classes"`` (labels),
        and ``"kinematics"`` (regression targets).
    is_classifier : bool
        Whether the model should be trained for classification.
    logger : CustomLogger
        Logger for status messages.
    """
    x_train = dataset["emg"][()]
    # Flatten 3D to 2D if needed (sklearn expects 2D input)
    if x_train.ndim == 3:
        x_train = x_train.reshape(x_train.shape[0], -1)

    if is_classifier:
        y_train = dataset["classes"][()]
    else:
        y_train = dataset["kinematics"][()]

    model.fit(x_train, y_train)
    return model


def predict(model: object, input_data: np.ndarray, is_classifier: bool):
    """Run a single prediction.

    Parameters
    ----------
    input_data : np.ndarray
        Shape ``(1, n_features, n_time)`` or ``(1, n_features)``.

    Returns
    -------
    int or list[float]
        A single class label (classifier) or list of DOF values (regressor).
    """
    if input_data.ndim == 3:
        input_data = input_data.reshape(input_data.shape[0], -1)

    prediction = model.predict(input_data)

    if is_classifier:
        return prediction[0] if prediction.ndim == 1 else prediction[0, 0]
    return list(prediction[0])


# %%
# --------------------------------------------------
# Step 3: Register a Classifier in CONFIG_REGISTRY
# --------------------------------------------------
# A classifier example using sklearn's SVM.  Changeable parameters appear
# as spinboxes in the Training UI.  Unchangeable parameters are passed
# directly to the model constructor.

from sklearn.svm import SVC
from myogestic.utils.config import CONFIG_REGISTRY

CONFIG_REGISTRY.register_model(
    name="My SVM Classifier",
    model_class=SVC,
    is_classifier=True,
    save_function=save,
    load_function=load,
    train_function=train,
    predict_function=predict,
    changeable_parameters={
        "C": {
            "start_value": 1e-4,
            "end_value": 1.0,
            "step": 1e-4,
            "default_value": 0.01,
        },
    },
    unchangeable_parameters={
        "kernel": "rbf",
    },
)

# %%
# -----------------------------------------------
# Step 4: Register a Regressor in CONFIG_REGISTRY
# -----------------------------------------------
# A regressor example using sklearn's Linear Regression.

from sklearn.linear_model import LinearRegression

CONFIG_REGISTRY.register_model(
    name="My Linear Regressor",
    model_class=LinearRegression,
    is_classifier=False,
    save_function=save,
    load_function=load,
    train_function=train,
    predict_function=predict,
    unchangeable_parameters={"fit_intercept": True},
)

# %%
# --------------------------------------------------------
# Step 5 (Advanced): Temporal-Preserving Model (e.g., CNN)
# --------------------------------------------------------
# If your model's architecture requires multiple time steps (e.g., a CNN),
# set ``requires_temporal_preservation=True`` and specify
# ``feature_window_size``.  This ensures that only compatible features
# (Identity, RMS Small Window) are shown in the Training UI.
#
# .. code-block:: python
#
#    CONFIG_REGISTRY.register_model(
#        name="MyCNN",
#        model_class=MyCNNModel,
#        is_classifier=False,
#        save_function=cnn_save,
#        load_function=cnn_load,
#        train_function=cnn_train,
#        predict_function=cnn_predict,
#        requires_temporal_preservation=True,
#        feature_window_size=120,  # Sliding window for feature extraction
#    )
#
# Reference: RaulNet registration in :mod:`~myogestic.default_config`:
#
# .. literalinclude:: /../../myogestic/default_config.py
#    :language: python
#    :lines: 45-67
#    :caption: RaulNet registration with temporal preservation
