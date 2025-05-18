import numpy as np
from catboost import CatBoostClassifier
from catboost.utils import get_gpu_device_count
from myoverse.datasets.filters.generic import IdentityFilter
from myoverse.datasets.filters.temporal import (
    SSCFilter,
    ZCFilter,
    WFLFilter,
    VARFilter,
    IAVFilter,
    MAVFilter,
    RMSFilter,
)
from myoverse.models.definitions.raul_net.online.v17 import RaulNetV17
from scipy.ndimage import gaussian_filter
from scipy.signal import savgol_filter
from sklearn.ensemble import AdaBoostClassifier
from sklearn.linear_model import LinearRegression
from sklearn.neural_network import MLPClassifier
from sklearn.svm import SVC
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis

from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface import (
    VirtualHandInterface_RecordingInterface,
    VirtualHandInterface_SetupInterface,
)
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface.output_interface import (
    VirtualHandInterface_OutputSystem,
)
from myogestic.gui.widgets.visual_interfaces.virtual_cursor_interface import (
    VirtualCursorInterface_RecordingInterface,
    VirtualCursorInterface_SetupInterface,
)
from myogestic.gui.widgets.visual_interfaces.virtual_cursor_interface.output_interface import (
    VirtualCursorInterface_OutputSystem,
)
from myogestic.models.definitions import raulnet_models, sklearn_models, catboost_models
from myogestic.utils.config import CONFIG_REGISTRY

CONFIG_REGISTRY.register_model(
    "RaulNet Regressor",
    RaulNetV17,
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
    RaulNetV17,
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
    {
        "task_type": "GPU" if get_gpu_device_count() > 0 else "CPU",
        "train_dir": None,
    },
)

CONFIG_REGISTRY.register_model(
    "Cursor CatBoost Classifier",
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
            "step": 10,
            "default_value": 300,
        },
        "depth": {
            "start_value": 1,
            "end_value": 100,
            "step": 1,
            "default_value": 10,
        },
        "l2_leaf_reg": {
            "start_value": 0.001,
            "end_value": 10,
            "step": 0.001,
            "default_value": 0.014,
        },
        "border_count": {
            "start_value": 1,
            "end_value": 255,
            "step": 1,
            "default_value": 254,
        },
        "learning_rate": {
            "start_value": 0.01,
            "end_value": 10,
            "step": 0.01,
            "default_value": 0.04,
        }
    },
    {
        "task_type": "GPU" if get_gpu_device_count() > 0 else "CPU",
        "train_dir": None,
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
    "SVM Classifier",
    SVC,
    True,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
    {
        "C": {
            "start_value": 1e-4,
            "end_value": 1,
            "step": 1e-4,
            "default_value": 1e-2,
        },
        "gamma": {
            "start_value": 1e-4,
            "end_value": 1,
            "step": 1e-4,
            "default_value": 1e-2,
        },
    },
    {"kernel": "rbf"},
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

CONFIG_REGISTRY.register_model(
    "LDA Classifier",
    LinearDiscriminantAnalysis,
    True,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
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

# Register real-time filters
CONFIG_REGISTRY.register_real_time_filter("Identity", lambda x: x)
CONFIG_REGISTRY.register_real_time_filter(
    "Gaussian", lambda x: gaussian_filter(np.array(x), 15, 0, axes=(0,))
)

CONFIG_REGISTRY.register_real_time_filter(
    "Savgol", lambda x: savgol_filter(np.array(x), 111, 3, axis=0)
)

CONFIG_REGISTRY.register_visual_interface(
    "VHI",
    setup_interface_ui=VirtualHandInterface_SetupInterface,
    recording_interface_ui=VirtualHandInterface_RecordingInterface,
)
CONFIG_REGISTRY.register_visual_interface(
    "VCI",
    setup_interface_ui=VirtualCursorInterface_SetupInterface,
    recording_interface_ui=VirtualCursorInterface_RecordingInterface,
)
# TODO: uncomment VHI when done
# CONFIG_REGISTRY.register_output_system("VHI", VirtualHandInterface_OutputSystem)
CONFIG_REGISTRY.register_output_system("VCI", VirtualCursorInterface_OutputSystem)
