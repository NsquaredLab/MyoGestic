from typing import Any, Callable, Literal, TypedDict

from myoverse.transforms import Transform

from myogestic.gui.widgets.templates.output_system import OutputSystemTemplate
from myogestic.gui.widgets.templates.visual_interface import (
    RecordingInterfaceTemplate,
    SetupInterfaceTemplate,
)


def _custom_message_handler(mode, context, message):
    """
    Custom message handler for the "warnings" module.

    This function is used to suppress a QLayout warning that is not relevant to the user.
    This warning is printed to the console when a new widget is added to a layout that already has a layout.

    Parameters
    ----------
    mode : str
        The mode of the message.
    context : dict
        The context of the message.
    message : str
        The message to display.
    """
    # Suppress the specific warning
    if "QLayout: Attempting to add QLayout" in message:
        return
    # Print other messages to the console
    print(f"{mode}: {message}")


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


ChangeableParameter = (
    IntParameter | FloatParameter | StringParameter | BoolParameter | CategoricalParameter
)
UnchangeableParameter = int | float | str | bool | list[str] | None


class Registry:
    """
    The registry class is used to store different components of a MyoGestic application pipeline.

    Attributes
    ----------
    models_map : dict[str, tuple[Any, bool]], optional
        A dictionary that maps model names to tuples of model classes and whether the model is a classifier, by default {}. The tuple is in the form (model_class, is_classifier).
    models_functions_map : dict[str, dict[Literal["save", "load", "train", "predict"], callable]], optional
        A dictionary that maps model names to dictionaries of model functions, by default {}. The functions are `save`, `load`, `train`, and `predict`.
    models_parameters_map : dict[str, dict[Literal["changeable", "unchangeable"], Union[ChangeableParameter, UnchangeableParameter]]], optional
        A dictionary that maps model names to dictionaries of model parameters, by default {}. The parameters are `changeable` and `unchangeable`.
        The `changeable` parameters are dictionaries of changeable parameters, while the `unchangeable` parameters are dictionaries of unchangeable parameters.
        See the `ChangeableParameter` and `UnchangeableParameter` types for more information.
    features_map : dict[str, type[Transform]], optional
        A dictionary that maps feature names to feature classes, by default {}.
        The feature class must be subclasses of `Transform` (TensorTransform).
    real_time_filters_map : dict[str, callable], optional
        A dictionary that maps filter names to filter functions, by default {}.
        A filter function is a callable that takes a single argument, which is the data to filter.
        The data will be a list of floats that represent the regression output of a model.
    visual_interfaces_map : dict[str, tuple[type[SetupInterfaceTemplate], type[RecordingInterfaceTemplate]]], optional
        A dictionary that maps visual interface names to tuples of setup and recording interface classes, by default {}.
        The setup interface class must be a subclass of `SetupInterfaceTemplate`, while the recording interface class must be a subclass of `RecordingInterfaceTemplate`.
    output_systems_map : dict[str, type[OutputSystemTemplate]], optional
        A dictionary that maps output system names to output system classes, by default {}.
        The output system class must be a subclass of `OutputSystemTemplate`.
    """

    def __init__(self):
        self.models_map: dict[str, tuple[Any, bool]] = {}
        self.models_functions_map: dict[
            str, dict[Literal["save", "load", "train", "predict"], Callable]
        ] = {}
        self.models_parameters_map: dict[
            str,
            dict[
                Literal["changeable", "unchangeable"],
                ChangeableParameter | UnchangeableParameter,
            ],
        ] = {}
        self.models_metadata_map: dict[str, dict] = {}

        self.features_map: dict[str, type[Transform]] = {}
        self.features_metadata_map: dict[str, dict] = {}
        self.real_time_filters_map: dict[str, Callable] = {}
        self.visual_interfaces_map: dict[
            str, tuple[type[SetupInterfaceTemplate], type[RecordingInterfaceTemplate]]
        ] = {}
        self.output_systems_map: dict[str, type[OutputSystemTemplate]] = {}

    def register_model(
        self,
        name: str,
        model_class: type,
        is_classifier: bool,
        save_function: Callable,
        load_function: Callable,
        train_function: Callable,
        predict_function: Callable,
        changeable_parameters: dict[str, ChangeableParameter] | None = None,
        unchangeable_parameters: dict[str, UnchangeableParameter] | None = None,
        requires_temporal_preservation: bool = False,
        feature_window_size: int | None = None,
    ) -> None:
        """
        Register a model in the registry.

        The model name must be unique.

        Parameters
        ----------
        name : str
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
            The function to make predictions with the model.
        changeable_parameters : dict of str to ChangeableParameter, optional
            A dictionary of changeable parameters for the model. Default is None.
        unchangeable_parameters : dict of str to UnchangeableParameter, optional
            A dictionary of unchangeable parameters for the model. Default is None.
        requires_temporal_preservation : bool, optional
            Whether the model requires temporal preservation in features. Default is False.
            Models like RaulNet with CNN layers need multiple temporal samples, so features
            should use smaller window sizes to preserve time dimension.
        feature_window_size : int, optional
            The window size to use for feature extraction. Default is None, which uses
            the full buffer size. For models requiring temporal preservation, this should
            be smaller than the buffer size (e.g., 120 for RaulNet with buffer of 360).

        Raises
        ------
        ValueError
            If the model is already registered.
        """

        if name in self.models_map:
            raise ValueError(
                f'Model "{name}" is already registered. Please choose a different name.'
            )

        self.models_map[name] = (model_class, is_classifier)

        self.models_functions_map[name] = {
            "save": save_function,
            "load": load_function,
            "train": train_function,
            "predict": predict_function,
        }

        self.models_parameters_map[name] = {
            "changeable": changeable_parameters or {},
            "unchangeable": unchangeable_parameters or {},
        }

        self.models_metadata_map[name] = {
            "requires_temporal_preservation": requires_temporal_preservation,
            "feature_window_size": feature_window_size,
        }

    def register_feature(
        self,
        name: str,
        feature: type[Transform],
        requires_temporal_preservation: bool = False,
    ) -> None:
        """
        Register a feature in the registry.

        .. note:: The feature name must be unique.

        Parameters
        ----------
        name : str
            The name of the feature.
        feature : type[Transform]
            The feature transform class to register.
        requires_temporal_preservation : bool, optional
            Whether this feature requires temporal preservation (keeps time dimension).
            Features like RMS Small Window that preserve the time dimension should
            set this to True. Default is False.

        Raises
        ------
        ValueError
            If the feature is already registered
        """
        if name in self.features_map:
            raise ValueError(
                f'Feature "{name}" is already registered. Please choose a different name.'
            )

        self.features_map[name] = feature
        self.features_metadata_map[name] = {
            "requires_temporal_preservation": requires_temporal_preservation,
        }

    def register_real_time_filter(self, name: str, function: Callable) -> None:
        """
        Register a real-time filter in the registry.

        .. note:: The filter name must be unique.

        Parameters
        ----------
        name : str
            The name of the filter.
        function : callable
            The filter function.

        Raises
        ------
        ValueError
            If the filter is already registered.
        """
        if name in self.real_time_filters_map:
            raise ValueError(
                f'Filter "{name}" is already registered. Please choose a different name.'
            )

        self.real_time_filters_map[name] = function

    def register_visual_interface(
        self,
        name: str,
        setup_interface_ui: type[SetupInterfaceTemplate],
        recording_interface_ui: type[RecordingInterfaceTemplate],
    ) -> None:
        """
        Register a visual interface in the registry.

        .. note:: The output modality name must be unique.

        Parameters
        ----------
        name : str
            The name of the visual interface.
        setup_interface_ui : type[SetupInterfaceTemplate]
            The setup interface class.
        recording_interface_ui : type[RecordingInterfaceTemplate]
            The recording interface class.

        Raises
        ------
        ValueError
            If the visual interface is already registered.
        """
        if name in self.visual_interfaces_map:
            raise ValueError(
                f'Visual interface "{name}" is already registered. Please choose a different name.'
            )

        self.visual_interfaces_map[name] = (setup_interface_ui, recording_interface_ui)

    def register_output_system(
        self, name: str, output_system: type[OutputSystemTemplate]
    ) -> None:
        """
        Register an output system in the registry.

        .. note:: The output system name must be unique.

        Parameters
        ----------
        name : str
            The name of the output system.
        output_system : callable
            The output system class.

        Raises
        ------
        ValueError
            If the output system is already registered.
        """
        if name in self.output_systems_map:
            raise ValueError(
                f'Output system "{name}" is already registered. Please choose a different name.'
            )

        self.output_systems_map[name] = output_system


# ------------------------------------------------------------------------------
if "CONFIG_REGISTRY" not in globals():
    CONFIG_REGISTRY = Registry()

    import myogestic.default_config  # noqa
    import myogestic.user_config  # noqa
