from sklearn.linear_model import LinearRegression, Ridge, LogisticRegression
from sklearn.multioutput import MultiOutputRegressor

from doc_octopy.datasets.filters.temporal import RMSFilter
from myogestic.models.config import CONFIG_REGISTRY
from myogestic.models.definitions import sklearn_models

# Register models
CONFIG_REGISTRY.register_model(
    "Linear Regressor Per Finger",
    lambda **params: MultiOutputRegressor(LinearRegression(**params)),
    False,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
)

CONFIG_REGISTRY.register_model(
    "Ridge Regressor Per Finger",
    lambda **params: MultiOutputRegressor(Ridge(**params)),
    False,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
)

CONFIG_REGISTRY.register_model(
    "Logistic Regression",
    LogisticRegression,
    True,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
    {"C": {"start_value": 1e-4, "end_value": 1e4, "step": 1e-4, "default_value": 1}},
    {"penalty": "l2"},
)


# Register features
class RMSFilterFixedWindow(RMSFilter):
    def __init__(self, is_output: bool = False, name: str = None):
        super().__init__(window_size=120, is_output=is_output, name=name)


CONFIG_REGISTRY.register_feature("RMS Small Window", RMSFilterFixedWindow)
