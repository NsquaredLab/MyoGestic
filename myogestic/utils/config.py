import copy
from typing import TypedDict, Union, Dict, Type, Callable, Any, Literal, Optional

import numpy as np
from catboost import CatBoostClassifier, CatBoostRegressor
from catboost.utils import get_gpu_device_count
from doc_octopy.datasets.filters._template import FilterBaseClass  # noqa
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
from scipy.ndimage import gaussian_filter
from scipy.signal import savgol_filter
from sklearn.ensemble import AdaBoostClassifier
from sklearn.gaussian_process import GaussianProcessClassifier
from sklearn.linear_model import LinearRegression
from sklearn.neural_network import MLPClassifier

from myogestic.gui.widgets.monitoring.template import _MonitoringWidgetBaseClass  # noqa
from myogestic.gui.widgets.monitoring.umap_monitoring import UMAPMonitoringWidget
from myogestic.models.definitions import sklearn_models, catboost_models, raulnet_models


class IntParameter(TypedDict):
    start_value: int
    end_value: int
    step: int
    default_value: int


class FloatParameter(TypedDict):
    start_value: float
    end_value: float
    step: float
    default_value: float


class StringParameter(TypedDict):
    default_value: str


class BoolParameter(TypedDict):
    default_value: bool


class CategoricalParameter(TypedDict):
    values: list[str]
    default_value: str


ChangeableParameter = Union[
    IntParameter, FloatParameter, StringParameter, BoolParameter, CategoricalParameter
]
UnchangeableParameter = Union[int, float, str, bool, list[str], None]


class Registry:
    """
    Base class for registration of models and features in the MyoGestic application.

    Attributes
    ----------
    models_map : dict[str, tuple[type, bool]]
        A dictionary mapping model names to tuples of the model class and a boolean indicating whether the model is a classifier.
    models_functions_map : dict[str, dict[Literal["save", "load", "train"], Callable]]
        A dictionary mapping model names to dictionaries of functions to save, load and train the model.
    models_parameters_map : dict[str, dict[Literal["changeable", "unchangeable"], Union[ChangeableParameter, UnchangeableParameter]]]
        A dictionary mapping model names to dictionaries of changeable and unchangeable parameters.
    features_map : dict[str, FilterBaseClass]
        A dictionary mapping feature names to filters or partial functions.
    """

    def __init__(self):
        self.models_map: Dict[str, tuple[Any, bool]] = {}
        self.models_functions_map: Dict[
            str, Dict[Literal["save", "load", "train", "predict"], Callable]
        ] = {}
        self.models_parameters_map: Dict[
            str,
            Dict[
                Literal["changeable", "unchangeable"],
                Union[ChangeableParameter, UnchangeableParameter],
            ],
        ] = {}

        self.features_map: Dict[str, Type[FilterBaseClass]] = {}

        self.real_time_filters_map: Dict[str, callable] = {}

        self.monitoring_widgets_map: Dict[str, Type[_MonitoringWidgetBaseClass]] = {}

    def register_model(
        self,
        model_name: str,
        model_class: Type,
        is_classifier: bool,
        save_function: Callable,
        load_function: Callable,
        train_function: Callable,
        predict_function: Callable,
        changeable_parameters: Optional[Dict[str, ChangeableParameter]] = None,
        unchangeable_parameters: Optional[Dict[str, UnchangeableParameter]] = None,
    ):
        """
        Register a model in the registry.

        .. note:: The model name must be unique.

        Parameters
        ----------
        model_name : str
            The name of the model.
        model_class : type
            The class of the model.
        is_classifier : bool
            Whether the model is a classifier.
        save_function : callable
            The function to save the model.
        load_function : callable
            The function to load the model.
        train_function : callable
            The function to train the model.
        predict_function : callable
            The function to predict with the model.
        changeable_parameters : dict[str, ChangeableParameter], optional
            The changeable parameters of the model, by default None.
        unchangeable_parameters : dict[str, UnchangeableParameter], optional
            The unchangeable parameters of the model, by default None.

        Raises
        ------
        ValueError
            If the model is already registered.
        """
        if model_name in self.models_map:
            raise ValueError(
                f'Model "{model_name}" is already registered. Please choose a different name.'
            )

        self.models_map[model_name] = (model_class, is_classifier)

        self.models_functions_map[model_name] = {
            "save": save_function,
            "load": load_function,
            "train": train_function,
            "predict": predict_function,
        }

        self.models_parameters_map[model_name] = {
            "changeable": changeable_parameters or {},
            "unchangeable": unchangeable_parameters or {},
        }

    def register_feature(self, feature_name: str, feature: Type[FilterBaseClass]):
        """
        Register a feature in the registry.

        .. note:: The feature name must be unique and the attribute `name` of the feature will be set to the feature name.

        Parameters
        ----------
        feature_name : str
            The name of the feature.
        feature : Type[FilterBaseClass]
            The feature to register.

        Raises
        ------
        ValueError
            If the feature is already registered
        """
        if feature_name in self.features_map:
            raise ValueError(
                f'Feature "{feature_name}" is already registered. Please choose a different name.'
            )

        feature.name = feature_name

        self.features_map[feature_name] = copy.deepcopy(feature)

    def register_real_time_filter(self, filter_name: str, filter_function: callable):
        """
        Register a real-time filter in the registry.

        .. note:: The filter name must be unique.

        Parameters
        ----------
        filter_name : str
            The name of the filter.
        filter_function : callable
            The filter function.

        Raises
        ------
        ValueError
            If the filter is already registered.
        """
        if filter_name in self.real_time_filters_map:
            raise ValueError(
                f'Filter "{filter_name}" is already registered. Please choose a different name.'
            )

        self.real_time_filters_map[filter_name] = filter_function

    def register_monitoring_widget(
        self, widget_name: str, widget: Type[_MonitoringWidgetBaseClass]
    ):
        """
        Register a monitoring widget in the registry.
        """
        if widget_name in self.monitoring_widgets_map:
            raise ValueError(
                f'Monitoring widget "{widget_name}" is already registered. Please choose a different name.'
            )

        self.monitoring_widgets_map[widget_name] = widget


# ------------------------------------------------------------------------------
if "CONFIG_REGISTRY" not in globals():
    CONFIG_REGISTRY = Registry()


def _set_config_registry() -> None:
    """
    Set the global CONFIG_REGISTRY.

    """
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
        {
            "task_type": "GPU" if get_gpu_device_count() > 0 else "CPU",
            "train_dir": None,
        },
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

    # Register real-time filters
    CONFIG_REGISTRY.register_real_time_filter("Identity", lambda x: x)
    CONFIG_REGISTRY.register_real_time_filter(
        "Gaussian", lambda x: gaussian_filter(np.array(x), 15, 0, axes=(0,))
    )

    CONFIG_REGISTRY.register_real_time_filter(
        "Savgol", lambda x: savgol_filter(np.array(x), 111, 3, axis=0)
    )

    # Register monitoring widgets
    CONFIG_REGISTRY.register_monitoring_widget("UMAP", UMAPMonitoringWidget)
    # load user configuration
    import myogestic.user_config  # noqa
