import numpy as np
from catboost import CatBoostClassifier
from catboost.utils import get_gpu_device_count as _get_gpu_device_count


def get_gpu_device_count() -> int:
    """Wrap catboost's GPU count to handle mocked imports (e.g. Sphinx)."""
    try:
        result = _get_gpu_device_count()
        return int(result)
    except (TypeError, ValueError):
        return 0
from myoverse.models.raul_net.v17 import RaulNetV17
from myoverse.transforms import (
    Identity,
    MAV,
    RMS,
    SlopeSignChanges,
    VAR,
    WaveformLength,
    ZeroCrossings,
)
from scipy.ndimage import gaussian_filter
from scipy.signal import savgol_filter
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.linear_model import LinearRegression
from sklearn.neural_network import MLPClassifier
from sklearn.svm import SVC

from myogestic.gui.widgets.visual_interfaces.virtual_cursor_interface import (
    VirtualCursorInterface_RecordingInterface,
    VirtualCursorInterface_SetupInterface,
)
from myogestic.gui.widgets.visual_interfaces.virtual_cursor_interface.output_interface import (
    VirtualCursorInterface_OutputSystem,
)
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface import (
    VirtualHandInterface_RecordingInterface,
    VirtualHandInterface_SetupInterface,
)
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface.output_interface import (
    VirtualHandInterface_OutputSystem,
)
from myogestic.models.definitions import catboost_models, raulnet_models, sklearn_models
from myogestic.utils.config import CONFIG_REGISTRY

CONFIG_REGISTRY.register_model(
    "RaulNet",
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
    requires_temporal_preservation=True,
    feature_window_size=120,
)

CONFIG_REGISTRY.register_model(
    "CatBoost",
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
    "Cursor CatBoost",
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
        },
    },
    {
        "task_type": "GPU" if get_gpu_device_count() > 0 else "CPU",
        "train_dir": None,
    },
)

CONFIG_REGISTRY.register_model(
    "Linear",
    LinearRegression,
    False,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
    unchangeable_parameters={"fit_intercept": True},
)

CONFIG_REGISTRY.register_model(
    "SVM",
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
    "MLP",
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
    "LDA",
    LinearDiscriminantAnalysis,
    True,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
)

# Register features (TensorTransform classes from MyoVerse v2)
# Note: These are transform CLASSES, not instances. They will be instantiated
# with window_size parameter when used in dataset creation/preprocessing.
CONFIG_REGISTRY.register_feature("Root Mean Square", RMS)
CONFIG_REGISTRY.register_feature("Mean Absolute Value", MAV)
CONFIG_REGISTRY.register_feature("Variance", VAR)
CONFIG_REGISTRY.register_feature("Waveform Length", WaveformLength)
CONFIG_REGISTRY.register_feature("Zero Crossings", ZeroCrossings)
CONFIG_REGISTRY.register_feature("Slope Sign Change", SlopeSignChanges)
CONFIG_REGISTRY.register_feature(
    "Identity", Identity, requires_temporal_preservation=True
)

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
# CONFIG_REGISTRY.register_visual_interface(
#     "VCI",
#     setup_interface_ui=VirtualCursorInterface_SetupInterface,
#     recording_interface_ui=VirtualCursorInterface_RecordingInterface,
# )

CONFIG_REGISTRY.register_output_system("VHI", VirtualHandInterface_OutputSystem)
# CONFIG_REGISTRY.register_output_system("VCI", VirtualCursorInterface_OutputSystem)
