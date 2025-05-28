from __future__ import annotations

import pickle
from typing import Any, TYPE_CHECKING, Union

import numpy as np

from myogestic.utils.config import CONFIG_REGISTRY

if TYPE_CHECKING:
    from myogestic.gui.widgets.logger import CustomLogger

from PySide6.QtCore import QObject, Signal
from myogestic.user_config import GROUND_TRUTH_INDICES_TO_KEEP
from myogestic.default_config import CONFIG_REGISTRY


class MyoGesticModel(QObject):
    predicted_emg_signal = Signal(np.ndarray)

    def __init__(self, logger: CustomLogger, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.past_predictions: list = []

        self.model_params = None
        self.model_name = None
        self.is_classifier = False
        self.logger = logger

        self.train_function = None
        self.load_function = None
        self.save_function = None

        self.model = None
        self.model_information = None

        self.conformal_predictor = None
        self.prediction_solver = None

    def train(
        self,
        dataset: dict,
        model_name: str,
        model_parameters: dict[str, Any],
        save_function: callable,
        load_function: callable,
        train_function: callable,
        selected_features: list[str],
    ) -> None:
        self.model_name = model_name
        self.model_params = model_parameters

        model_class, self.is_classifier = CONFIG_REGISTRY.models_map[self.model_name]

        self.model_information = dataset
        self.model_information["selected_features"] = selected_features

        self.model: object = model_class(**self.model_params)  # noqa

        self.save_function = save_function
        self.load_function = load_function
        self.train_function = train_function

        self.model = self.train_function(self.model, dataset, self.is_classifier, self.logger)

    def predict(
        self, input: np.ndarray, prediction_function, selected_real_time_filter: str
    ) -> tuple[Any, list[Any] | None, str | None]:
        self.predicted_emg_signal.emit(input)
        prediction = prediction_function(self.model, input, self.is_classifier)

        if self.is_classifier:
            return (prediction, None, None) if prediction != -1 else (-1, None, None)

        prediction_before_filter = (
            np.zeros(
                self.parent().selected_visual_interface.recording_interface_ui.ground_truth__nr_of_recording_values
            )
            if GROUND_TRUTH_INDICES_TO_KEEP != "all"
            else prediction
        )
        if GROUND_TRUTH_INDICES_TO_KEEP != "all":
            # Check which virtual interface is active
            for index, value in enumerate(GROUND_TRUTH_INDICES_TO_KEEP[self.model_information["visual_interface"]]):
                prediction_before_filter[value] = prediction[index]

        prediction_before_filter = (
            list(np.clip(prediction_before_filter, 0, 1))
            if self.model_information["visual_interface"] == "VHI"
            else list(np.clip(prediction_before_filter, -1, 1))
        )
        self.past_predictions.append(prediction_before_filter)
        if (
            len(self.past_predictions)
            > (
                self.model_information["device_information"]["sampling_frequency"]
                // self.model_information["device_information"]["samples_per_frame"]
            )
            * 5
        ):
            self.past_predictions.pop(0)
            prediction_after_filter = CONFIG_REGISTRY.real_time_filters_map[selected_real_time_filter](
                self.past_predictions
            )
            prediction_after_filter = list(prediction_after_filter[-1])
        else:
            prediction_after_filter = [np.nan] * len(prediction_before_filter)

        return (
            prediction_before_filter,
            prediction_after_filter,
            selected_real_time_filter,
        )

    def save(self, model_path: str) -> dict[str, Union[str, Any]]:
        self.model_information["model_params"] = self.model_params
        self.model_information["model_path"] = self.save_function(model_path, self.model)
        self.model_information["model_name"] = self.model_name

        return self.model_information

    def load(self, model_path: str) -> dict[str, Union[str, Any]]:
        with open(model_path, "rb") as f:
            self.model_information = pickle.load(f)

        self.load_function = CONFIG_REGISTRY.models_functions_map[self.model_information["model_name"]]["load"]

        model_class, self.is_classifier = CONFIG_REGISTRY.models_map[self.model_information["model_name"]]

        self.model = self.load_function(
            self.model_information["model_path"],
            model_class(**self.model_information["model_params"]),  # noqa
        )

        return self.model_information
