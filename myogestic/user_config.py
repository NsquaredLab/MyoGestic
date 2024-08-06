from catboost import CatBoostRegressor
from catboost.utils import get_gpu_device_count
from sklearn.linear_model import LinearRegression
from sklearn.multioutput import MultiOutputRegressor

from myogestic.models.definitions import sklearn_models

MODELS_MAP = {
    "Catboost Regressor Per Finger": (
        lambda **params: MultiOutputRegressor(CatBoostRegressor(**params)),
        False,
    ),
    "Linear Regressor Per Finger": (
        lambda **params: MultiOutputRegressor(LinearRegression(**params)),
        False,
    ),
}

FUNCTIONS_MAP = {
    "Catboost Regressor Per Finger": {
        "save_function": sklearn_models.save,
        "load_function": sklearn_models.load,
        "train_function": sklearn_models.train,
    },
    "Linear Regressor Per Finger": {
        "save_function": sklearn_models.save,
        "load_function": sklearn_models.load,
        "train_function": sklearn_models.train,
    },
}

PARAMETERS_MAP = {
    "Catboost Regressor Per Finger": {
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
                "default_value": 128,
            },
        },
        "unchangeable": {
            "task_type": "GPU" if get_gpu_device_count() > 0 else "CPU",
            "train_dir": None,
        },
    },
    "Linear Regressor Per Finger": {
        "changeable": {},
        "unchangeable": {},
    },
}
