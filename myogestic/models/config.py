from catboost import CatBoostClassifier, CatBoostRegressor
from catboost.utils import get_gpu_device_count
from sklearn.ensemble import AdaBoostClassifier
from sklearn.gaussian_process import GaussianProcessClassifier
from sklearn.linear_model import LinearRegression
from sklearn.neural_network import MLPClassifier

from doc_octopy.datasets.filters.generic import IdentityFilter
from doc_octopy.datasets.filters.temporal import (
    RMSFilter,
    MAVFilter,
    IAVFilter,
    VARFilter,
    WFLFilter,
    ZCFilter,
    SSCFilter,
)
from doc_octopy.models.definitions.raul_net.online.v16 import RaulNetV16
from myogestic.models.definitions import sklearn_models, catboost_models, raulnet_models
from myogestic.models.utils import Registry

CONFIG_REGISTRY = Registry()

# Register models
CONFIG_REGISTRY.register_model(
    "RaulNet Regressor",
    RaulNetV16,
    False,
    raulnet_models.save,
    raulnet_models.load,
    raulnet_models.train,
    raulnet_models.predict,
    unchangeable_parameters={
        "learning_rate": 1e-4,
        "nr_of_input_channels": 1,
        "input_length__samples": 360,
        "nr_of_outputs": 5,
        "nr_of_electrode_grids": 1,
        "nr_of_electrodes_per_grid": 32,
        "cnn_encoder_channels": (64, 32, 32),
        "mlp_encoder_channels": (128, 128),
        "event_search_kernel_length": 31,
        "event_search_kernel_stride": 8,
    },
)

CONFIG_REGISTRY.register_model(
    "RaulNet Regressor per Finger",
    RaulNetV16,
    False,
    raulnet_models.save_per_finger,
    raulnet_models.load_per_finger,
    raulnet_models.train_per_finger,
    raulnet_models.predict_per_finger,
    unchangeable_parameters={
        "learning_rate": 1e-4,
        "nr_of_input_channels": 1,
        "input_length__samples": 360,
        "nr_of_outputs": 1,
        "nr_of_electrode_grids": 1,
        "nr_of_electrodes_per_grid": 32,
        "cnn_encoder_channels": (64, 32, 32),
        "mlp_encoder_channels": (128, 128),
        "event_search_kernel_length": 31,
        "event_search_kernel_stride": 8,
    },
)

CONFIG_REGISTRY.register_model(
    "CatBoost Classifier",
    CatBoostClassifier,
    True,
    catboost_models.save,
    catboost_models.load,
    catboost_models.train,
    catboost_models.predict,
    {
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
    {"task_type": "GPU" if get_gpu_device_count() > 0 else "CPU", "train_dir": None},
)

CONFIG_REGISTRY.register_model(
    "CatBoost Regressor",
    CatBoostRegressor,
    False,
    catboost_models.save,
    catboost_models.load,
    catboost_models.train,
    catboost_models.predict,
    {
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
    {
        "task_type": "GPU" if get_gpu_device_count() > 0 else "CPU",
        "train_dir": None,
        "loss_function": "MultiRMSE",
        "boosting_type": "Plain",
    },
)

CONFIG_REGISTRY.register_model(
    "AdaBoost Classifier",
    AdaBoostClassifier,
    True,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
    {
        "n_estimators": {
            "start_value": 10,
            "end_value": 1000,
            "step": 10,
            "default_value": 100,
        },
        "learning_rate": {
            "start_value": 0.1,
            "end_value": 1,
            "step": 0.1,
            "default_value": 0.1,
        },
    },
)

CONFIG_REGISTRY.register_model(
    "Gaussian Process Classifier",
    GaussianProcessClassifier,
    True,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
    unchangeable_parameters={"kernel": None},
)

CONFIG_REGISTRY.register_model(
    "Linear Regression",
    LinearRegression,
    False,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
    unchangeable_parameters={"fit_intercept": True},
)

CONFIG_REGISTRY.register_model(
    "MLP Classifier",
    MLPClassifier,
    True,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
    {
        "hidden_layer_sizes": {
            "start_value": 10,
            "end_value": 1000,
            "step": 10,
            "default_value": 100,
        },
        "alpha": {
            "start_value": 1e-4,
            "end_value": 1,
            "step": 1e-4,
            "default_value": 1e-4,
        },
    },
    {"activation": "relu"},
)

# Register features
CONFIG_REGISTRY.register_feature("Root Mean Square", RMSFilter)
CONFIG_REGISTRY.register_feature("Mean Absolute Value", MAVFilter)
CONFIG_REGISTRY.register_feature("Integrated Absolute Value", IAVFilter)
CONFIG_REGISTRY.register_feature("Variance", VARFilter)
CONFIG_REGISTRY.register_feature("Waveform Length", WFLFilter)
CONFIG_REGISTRY.register_feature("Zero Crossings", ZCFilter)
CONFIG_REGISTRY.register_feature("Slope Sign Change", SSCFilter)
CONFIG_REGISTRY.register_feature("Identity", IdentityFilter)

# load user configuration
