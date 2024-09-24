from typing import TypedDict, Literal

from catboost import CatBoostClassifier, CatBoostRegressor
from catboost.utils import get_gpu_device_count
from sklearn.ensemble import AdaBoostClassifier
from sklearn.gaussian_process import GaussianProcessClassifier
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.svm import SVC

import myogestic.models.definitions.catboost_models as catboost_models
from doc_octopy.datasets.filters._template import FilterBaseClass
from doc_octopy.datasets.filters.temporal import (
    RMSFilter,
    MAVFilter,
    IAVFilter,
    VARFilter,
    WFLFilter,
    ZCFilter,
    SSCFilter,
)
from myogestic.models.definitions import sklearn_models
from myogestic.user_config import (
    FUNCTIONS_MAP as USER_FUNCTIONS_MAP,
    MODELS_MAP as USER_MODELS_MAP,
    PARAMETERS_MAP as USER_PARAMETERS_MAP,
)


class IntParameter(TypedDict):
    """TypedDict for integer parameters.

    Parameters
    ----------
    start_value : int
        The start value for the parameter.
    end_value : int
        The end value for the parameter.
    step : int
        The step for the parameter.
    default_value : int
        The default value for the parameter.
    """

    start_value: int
    end_value: int
    step: int
    default_value: int


class FloatParameter(TypedDict):
    """TypedDict for float parameters.

    Parameters
    ----------
    start_value : float
        The start value for the parameter.
    end_value : float
        The end value for the parameter.
    step : float
        The step for the parameter.
    default_value : float
        The default value for the parameter.
    """

    start_value: float
    end_value: float
    step: float
    default_value: float


class StringParameter(TypedDict):
    """TypedDict for string parameters.

    Parameters
    ----------
    default_value : str
        The default value for the parameter.
    """

    default_value: str


class BoolParameter(TypedDict):
    """TypedDict for boolean parameters.

    Parameters
    ----------
    default_value : bool
        The default value for the parameter.
    """

    default_value: bool


class CategoricalParameter(TypedDict):
    """TypedDict for categorical parameters.

    Parameters
    ----------
    values : list[str]
        The values for the parameter.
    default_value : str
        The default value for the parameter.
    """

    values: list[str]
    default_value: str


ChangeableParameter = (
    IntParameter
    | FloatParameter
    | StringParameter
    | BoolParameter
    | CategoricalParameter
)
"""
Union of the TypedDicts for the changeable parameters.
"""

UnchangeableParameter = int | float | str | bool | list[str] | None
"""
Union of the types for the unchangeable parameters.
"""

MODELS_MAP: dict[str, tuple[object, bool]] = {
    "CatBoost Classifier": (CatBoostClassifier, True),
    "CatBoost Regressor": (CatBoostRegressor, False),
    "Linear Regressor": (LinearRegression, False),
    "Logistic Classifier": (LogisticRegression, True),
    "Gaussian Process Classifier": (GaussianProcessClassifier, True),
    "AdaBoost Classifier": (AdaBoostClassifier, True),
    "MLP Classifier": (MLPClassifier, True),
    "Support Vector Classifier": (SVC, True),
}
"""
Dictionary to get the models class and whether it is a classifier or regressor.

The keys are the models names, the values are tuples with the models class and a boolean
indicating whether the models is a classifier.

The model class must be a callable that receives the parameters as keyword arguments.
"""

FUNCTIONS_MAP: dict[
    str, dict[Literal["save_function", "load_function", "train_function"], callable]
] = {
    "CatBoost Classifier": {
        "save_function": catboost_models.save,
        "load_function": catboost_models.load,
        "train_function": catboost_models.train,
    },
    "CatBoost Regressor": {
        "save_function": catboost_models.save,
        "load_function": catboost_models.load,
        "train_function": catboost_models.train,
    },
    "Linear Regressor": {
        "save_function": sklearn_models.save,
        "load_function": sklearn_models.load,
        "train_function": sklearn_models.train,
    },
    "Linear Regressor Per Finger": {
        "save_function": sklearn_models.save,
        "load_function": sklearn_models.load,
        "train_function": sklearn_models.train,
    },
    "Gaussian Process Classifier": {
        "save_function": sklearn_models.save,
        "load_function": sklearn_models.load,
        "train_function": sklearn_models.train,
    },
    "AdaBoost Classifier": {
        "save_function": sklearn_models.save,
        "load_function": sklearn_models.load,
        "train_function": sklearn_models.train,
    },
    "MLP Classifier": {
        "save_function": sklearn_models.save,
        "load_function": sklearn_models.load,
        "train_function": sklearn_models.train,
    },
    "Support Vector Classifier": {
        "save_function": sklearn_models.save,
        "load_function": sklearn_models.load,
        "train_function": sklearn_models.train,
    },
}
"""
Dictionary to get the functions to save and load the models.

The keys are the models names, the values are dictionaries with the keys "save_function",
"load_function" and "train_function" and the values are the functions to save, load and train
the models, respectively.
"""

PARAMETERS_MAP: dict[
    str,
    dict[
        Literal["changeable", "unchangeable"],
        dict[str, ChangeableParameter | UnchangeableParameter],
    ],
] = {
    "CatBoost Classifier": {
        "changeable": {
            "iterations": {
                "start_value": 10,
                "end_value": 10000,
                "step": 100,
                "default_value": 1000,
            },
            "l2_leaf_reg": {
                "start_value": 1,
                "end_value": 10,
                "step": 1,
                "default_value": 5,
            },
            "border_count": {
                "start_value": 1,
                "end_value": 255,
                "step": 1,
                "default_value": 254,
            },
        },
        "unchangeable": {
            "task_type": "GPU" if get_gpu_device_count() > 0 else "CPU",
            "train_dir": None,
        },
    },
    "CatBoost Regressor": {
        "changeable": {
            "iterations": {
                "start_value": 10,
                "end_value": 1000,
                "step": 10,
                "default_value": 100,
            },
            "l2_leaf_reg": {
                "start_value": 1,
                "end_value": 10,
                "step": 1,
                "default_value": 5,
            },
            "border_count": {
                "start_value": 1,
                "end_value": 255,
                "step": 1,
                "default_value": 254,
            },
        },
        "unchangeable": {
            "task_type": "GPU" if get_gpu_device_count() > 0 else "CPU",
            "train_dir": None,
            "loss_function": "MultiRMSE",
            "boosting_type": "Plain",
        },
    },
    "Linear Regressor": {
        "changeable": {},
        "unchangeable": {},
    },
    "Logistic Classifier": {
        "changeable": {},
        "unchangeable": {},
    },
    "Gaussian Process Classifier": {
        "changeable": {},
        "unchangeable": {},
    },
    "AdaBoost Classifier": {
        "changeable": {},
        "unchangeable": {},
    },
    "MLP Classifier": {
        "changeable": {},
        "unchangeable": {},
    },
    "Support Vector Classifier": {
        "changeable": {},
        "unchangeable": {},
    },
}
"""
Dictionary to get the parameters for the models.

The keys are the models names, the values are dictionaries with two keys: "changeable"
and "unchangeable". The values are dictionaries with the parameter names as keys and
the parameter values as values.

The changeable parameters must be of type ChangeableParameter and the unchangeable parameters must be of type UnchangeableParameter.
"""

FEATURES_MAP: dict[str, FilterBaseClass] = { # noqa
    "Root Mean Square": RMSFilter,
    "Mean Absolute Value": MAVFilter,
    "Integrated Absolute Value": IAVFilter,
    "Variance": VARFilter,
    "Waveform Length": WFLFilter,
    "Zero Crossings": ZCFilter,
    "Slope Sign Change": SSCFilter,
    # TODO: Add these back
    # "Difference Absolute Standard Deviation": DASDVFilter,
    # "V-Order": VOrderFilter,
    # "Average Amplitude Change": AACFilter,
    # "Maximum Fractal Length": MFLFilter,
}
"""
Dictionary to get the EMG features class.

The keys are the feature names, the values are the features class.
The features must subclass the FilterBaseClass.
"""

# Make the user configurations appear first.
# This reduces the amount of clicks necessary to find the user configurations.
MODELS_MAP = {**USER_MODELS_MAP, **MODELS_MAP}
FUNCTIONS_MAP = {**USER_FUNCTIONS_MAP, **FUNCTIONS_MAP}
PARAMETERS_MAP = {**USER_PARAMETERS_MAP, **PARAMETERS_MAP}
