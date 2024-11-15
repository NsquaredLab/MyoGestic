from __future__ import annotations

import pickle
from typing import Any, TYPE_CHECKING, Union, Optional

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.signal import savgol_filter
from torch.signal.windows import gaussian

from myogestic.models.config import CONFIG_REGISTRY

if TYPE_CHECKING:
    from myogestic.gui.widgets.logger import CustomLogger

from PySide6.QtCore import QObject


class MyoGesticModel(QObject):
    def __init__(self, logger: CustomLogger, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.past_predictions = []

        self.model_params = None
        self.model_name = None
        self.is_classifier = False
        self.logger = logger

        self.train_function = None
        self.load_function = None
        self.save_function = None

        self.model_prediction_to_interface_map = {
            -1: "Rejected Sample",
            0: "[0, 0, 0, 0, 0, 0, 0, 0, 0]",
            1: "[0, 0, 1, 0, 0, 0, 0, 0, 0]",
            2: "[1, 0, 0, 0, 0, 0, 0, 0, 0]",
            3: "[0, 0, 0, 1, 0, 0, 0, 0, 0]",
            4: "[0, 0, 0, 0, 1, 0, 0, 0, 0]",
            5: "[0, 0, 0, 0, 0, 1, 0, 0, 0]",
            6: "[0.67, 1, 1, 1, 1, 1, 0, 0, 0]",
            7: "[0.45, 1, 0.6, 0, 0, 0, 0, 0, 0]",
            8: "[0.55, 1, 0.65, 0.65, 0, 0, 0, 0, 0]",
        }
        self.model_prediction_to_mechatronic_interface_map = {
            -1: "Rejected Sample",
            0: "[0, 0, 0, 0, 0, 0, 0, 0, 0]",
            1: "[0, 0, 1, 0, 0, 0, 0, 0, 0]",
            2: "[1, 0, 0, 0, 0, 0, 0, 0, 0]",
            3: "[0, 0, 0, 1, 0, 0, 0, 0, 0]",
            4: "[0, 0, 0, 0, 1, 0, 0, 0, 0]",
            5: "[0, 0, 0, 0, 0, 1, 0, 0, 0]",
            6: "[1, 1, 1, 1, 1, 1, 0, 0, 0]",
            7: "[1, 1, 1, 0, 0, 0, 0, 0, 0]",
            8: "[1, 1, 1, 1, 0, 0, 0, 0, 0]",
        }
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

        self.model = self.train_function(
            self.model, dataset, self.is_classifier, self.logger
        )

    def predict(
        self, input: np.ndarray, prediction_function, selected_real_time_filter: str
    ) -> tuple[str, str, Any, Optional[np.ndarray]]:
        if self.is_classifier:
            prediction = prediction_function(self.model, input, self.is_classifier)

            if prediction == -1:
                return "", "", -1, None

            return (
                self.model_prediction_to_interface_map[prediction],
                self.model_prediction_to_mechatronic_interface_map[prediction],
                prediction,
                None,
            )

        prediction = prediction_function(self.model, input, self.is_classifier)

        self.past_predictions.append(prediction)
        if len(self.past_predictions) > 555:
            self.past_predictions.pop(0)

            # real-time savitzky-golay filter
            print(selected_real_time_filter)
            prediction = CONFIG_REGISTRY.real_time_filters_map[
                selected_real_time_filter
            ](self.past_predictions)
            # prediction =
            prediction = list(prediction[-1])

        prediction = [prediction[0]] + [0.0] + prediction[1:] + [0.0, 0.0, 0.0]

        prediction = list(np.clip(prediction, 0, 1))

        return str(prediction), "", prediction, None

    def save(self, model_path: str) -> dict[str, Union[str, Any]]:
        self.model_information["model_params"] = self.model_params
        self.model_information["model_path"] = self.save_function(
            model_path, self.model
        )
        self.model_information["model_name"] = self.model_name

        return self.model_information

    def load(self, model_path: str) -> dict[str, Union[str, Any]]:
        with open(model_path, "rb") as f:
            self.model_information = pickle.load(f)

        self.load_function = CONFIG_REGISTRY.models_functions_map[
            self.model_information["model_name"]
        ]["load"]

        model_class, self.is_classifier = CONFIG_REGISTRY.models_map[
            self.model_information["model_name"]
        ]

        self.model = self.load_function(
            self.model_information["model_path"],
            model_class(**self.model_information["model_params"]),  # noqa
        )

        return self.model_information
