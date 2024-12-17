from myoverse.datasets.filters.temporal import RMSFilter
from sklearn.linear_model import LinearRegression, Ridge, LogisticRegression
from sklearn.multioutput import MultiOutputRegressor

from myogestic.models.definitions import sklearn_models
from myogestic.utils.config import CONFIG_REGISTRY

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


# Register features
class RMSFilterFixedWindow(RMSFilter):
    def __init__(self, is_output: bool = False, name: str = None):
        super().__init__(window_size=120, is_output=is_output, name=name)


CONFIG_REGISTRY.register_feature("RMS Small Window", RMSFilterFixedWindow)
