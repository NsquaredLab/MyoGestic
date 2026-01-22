"""
This module contains the functions to save, load, train and predict using sklearn models.
"""

from typing import Union

import joblib
import numpy as np

from myogestic.gui.widgets.logger import CustomLogger


def _flatten_3d_to_2d(data: np.ndarray) -> np.ndarray:
    """Flatten 3D data (samples, channels, time) to 2D (samples, features)."""
    if data.ndim == 3:
        return data.reshape(data.shape[0], data.shape[1] * data.shape[2])
    return data


def _extract_classifier_prediction(prediction: np.ndarray):
    """Extract single prediction value for classifier output."""
    if prediction.ndim == 2:
        return prediction[0, 0]
    return prediction[0]


def save(model_path: str, model: object) -> str:
    """
    Save a sklearn model.

    Parameters
    ----------
    model_path: str
        The path to save the model.
    model: Any
        The sklearn model to save.

    Returns
    -------
    str
        The path where the model was saved.

    """
    output_model_path: str = str(model_path).split(".")[0] + "_model" + ".pkl"
    joblib.dump(model, output_model_path)
    return output_model_path


def load(model_path: str, _: object) -> object:
    """
    Load a sklearn model.

    Parameters
    ----------
    model_path: str
        The path to load the model.
    _: Any
        A new instance of the sklearn model. This instance is not used to load the model.

    Returns
    -------
    Any
        The loaded sklearn model

    """
    with open(model_path, "rb") as f:
        model = joblib.load(f)
    return model


def train(model: object, dataset, is_classifier: bool, _: CustomLogger) -> object:
    """
    Train a sklearn model.

    Parameters
    ----------
    model: Any
        The sklearn model to train.
    dataset
    _: CustomLogger
        The logger to log the training process. This parameter is not used.
    is_classifier: bool
        Whether the model is a classifier.

    Returns
    -------
    Any
        The trained sklearn model.

    """
    x_train = _flatten_3d_to_2d(dataset["emg"][()])

    if is_classifier:
        y_train = dataset["classes"][()]
    else:
        y_train = dataset["kinematics"][()]
        # Add small noise to zero targets to avoid numerical errors
        zero_mask = y_train == 0
        y_train[zero_mask] = np.random.uniform(0.0001, 0.001, zero_mask.sum())

    model.fit(x_train, y_train)
    return model


def predict(
    model: object, input: np.ndarray, is_classifier: bool
) -> Union[np.ndarray, list[float]]:
    """
    Predict with a sklearn model.

    Parameters
    ----------
    model: Any
        The sklearn model to predict with.
    input: np.ndarray
        The input data to predict.
    is_classifier: bool
        Whether the model is a classifier.

    Returns
    -------
    Union[np.ndarray, list[float]]
        The prediction of the model. If the model is a classifier, the prediction is a np.array.
        Otherwise, the prediction is a list of floats.

    """
    input_2d = _flatten_3d_to_2d(input)
    prediction = model.predict(input_2d)

    if is_classifier:
        return _extract_classifier_prediction(prediction)

    return list(prediction[0])
