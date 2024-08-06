"""
This module contains the functions to save, load and train CatBoost models.
"""
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
    output_model_path: str = model_path.split(".")[0] + "_model" + ".cbm"
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
    model: _CatBoostBase, x_train: np.ndarray, y_train: np.ndarray, logger: CustomLogger
) -> _CatBoostBase:
    """
    Train a CatBoost model.

    Parameters
    ----------
    model: _CatBoostBase
        The CatBoost model to train.
    x_train: np.ndarray
        The training data.
    y_train: np.ndarray
        The training ground truth.
    logger: CustomLogger
        The logger to use.

    Returns
    -------
    _CatBoostBase
        The trained CatBoost model.

    """
    if model.__class__.__name__ == "CatBoostRegressor":
        # add small noise to the target to avoid errors
        y_train[y_train == 0] = np.random.uniform(
            0.0001, 0.001, y_train[y_train == 0].shape
        )

    model.fit(x_train, y_train, log_cerr=logger.print, log_cout=logger.print)
    return model
