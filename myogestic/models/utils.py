import copy
from typing import TypedDict, Union, Dict, Type, Callable, Any, Literal, Optional

from doc_octopy.datasets.filters._template import FilterBaseClass  # noqa


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

        self.features_map: Dict[str, FilterBaseClass] = {}

        self.real_time_filters_map: Dict[str, callable] = {}

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

    def register_feature(self, feature_name: str, feature: FilterBaseClass):
        """
        Register a feature in the registry.

        .. note:: The feature name must be unique and the attribute `name` of the feature will be set to the feature name.

        Parameters
        ----------
        feature_name : str
            The name of the feature.
        feature : FilterBaseClass
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
