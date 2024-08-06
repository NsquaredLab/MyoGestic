"""
This module contains the functions to save, load and train sklearn models.
"""

import joblib
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
    output_model_path: str = model_path.split(".")[0] + "_model" + ".pkl"
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


def train(model: object, x_train: object, y_train: object, _: CustomLogger) -> object:
    """
    Train a sklearn model.

    Parameters
    ----------
    model: Any
        The sklearn model to train.
    x_train: Any
        The input data to train the model.
    y_train: Any
        The target data to train the model.
    _: CustomLogger
        The logger to log the training process. This parameter is not used.

    Returns
    -------
    Any
        The trained sklearn model.

    """
    model.fit(x_train, y_train)
    return model
