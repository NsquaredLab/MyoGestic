"""
This module contains the functions to save, load, train and predict using CatBoost models.
"""
from typing import Union

import numpy as np
from catboost.core import _CatBoostBase
from myogestic.gui.widgets.logger import CustomLogger


def save(model_path: str, model: _CatBoostBase) -> str:
    """
    Save a CatBoost model.

    Parameters
    ----------
    model_path: str
        The path to save the model.
    model: catboost.core._CatBoostBase
        The CatBoost model to save.

    Returns
    -------
    str
        The path where the model was saved.

    """
    output_model_path = model_path.split(".")[0] + "_model" + ".cbm"
    model.save_model(output_model_path)
    return output_model_path


def load(model_path: str, model: _CatBoostBase) -> _CatBoostBase:
    """
    Load a CatBoost model.

    Parameters
    ----------
    model_path: str
        The path to load the model.
    model: _CatBoostBase
        A new instance of the CatBoost model. This instance is used to load the model.

    Returns
    -------
    _CatBoostBase
        The loaded CatBoost model.

    """
    model.load_model(model_path)
    return model


def train(
    model: _CatBoostBase, dataset: dict, is_classifier: bool, logger: CustomLogger
) -> _CatBoostBase:
    """
    Train a CatBoost model.

    Parameters
    ----------
    model: _CatBoostBase
        The CatBoost model to train.
    dataset: dict
        The dataset to train the model.
    is_classifier: bool
        If the model is a classifier.
    logger: CustomLogger
        The logger to use.

    Returns
    -------
    _CatBoostBase
        The trained CatBoost model.

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

    model.fit(x_train, y_train, log_cerr=logger.print, log_cout=logger.print)
    return model


def predict(
    model: _CatBoostBase, input: np.ndarray, is_classifier: bool
) -> Union[np.array, list[float]]:
    """
    Predict with a CatBoost model.

    Parameters
    ----------
    model: _CatBoostBase
        The CatBoost model to predict with.
    input: np.ndarray
        The input data to predict. The shape of the input data will be (1, n_features, n_samples).
    is_classifier: bool
        If the model is a classifier.

    Returns
    -------
    Union[np.array, list[float]]
        The prediction. If the model is a classifier, the prediction will be a np.array.
        If the model is a regressor, the prediction will be a list of floats.

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
