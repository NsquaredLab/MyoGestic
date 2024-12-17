"""
This module contains the functions to save, load, train and predict using sklearn models.
"""

from typing import Union

import joblib
import numpy as np

from myogestic.gui.widgets.logger import CustomLogger


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
    x_train = dataset["emg"][()]

    x_train = np.reshape(
        x_train, (x_train.shape[0], x_train.shape[1] * x_train.shape[2])
    )

    if is_classifier:
        y_train = dataset["classes"][()]
    else:
        y_train = dataset["kinematics"][()]
        # add small noise to the target to avoid errors
        y_train[y_train == 0] = np.random.uniform(
            0.0001, 0.001, y_train[y_train == 0].shape
        )

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
    prediction = model.predict(
        np.reshape(input, (input.shape[0], input.shape[1] * input.shape[2]))
    )

    if is_classifier:
        try:
            prediction = prediction[0, 0]
        except IndexError:
            prediction = prediction[0]

        return prediction

    return list(prediction[0])
