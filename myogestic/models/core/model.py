from __future__ import annotations

import pickle
from typing import Any, TYPE_CHECKING, Union

import numpy as np
from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.models.config import FUNCTIONS_MAP, MODELS_MAP

if TYPE_CHECKING:
    from myogestic.gui.widgets.logger import CustomLogger

from PySide6.QtCore import QObject


class MyoGesticModel(QObject):
    def __init__(self, logger: CustomLogger, parent: QObject | None = None) -> None:
        super().__init__(parent)

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

        model_class, self.is_classifier = MODELS_MAP[self.model_name]

        training_x: np.ndarray = dataset["emg"]
        if self.is_classifier:
            training_y: np.ndarray = dataset["classes"]
        else:
            training_y: np.ndarray = dataset["kinematics"][:, [0, 2, 3, 4, 5]]

        self.model_information = dataset
        self.model_information["selected_features"] = selected_features

        self.model: object = model_class(**self.model_params)  # noqa

        self.save_function = save_function
        self.load_function = load_function
        self.train_function = train_function

        self.model = self.train_function(
            self.model, training_x, training_y, self.logger
        )

    def predict(self, input: np.ndarray) -> tuple[str, str, int, np.ndarray]:
        if self.is_classifier:
            prediction_proba = None
            if self.conformal_predictor is not None:
                try:
                    prediction_proba = self.model.predict_proba(input)[0]
                    prediction_set = self.conformal_predictor.predict(
                        np.array(prediction_proba)
                    )
                    prediction = self.prediction_solver.solve(prediction_set)

                    if prediction != -1:
                        prediction = self.model.classes_[prediction]

                except Exception as error:
                    self.logger.print(
                        f"Warning - prediction not conformalized - Error: {error}",
                        LoggerLevel.ERROR,
                    )
                    prediction = -1
            else:
                try:
                    prediction = self.model.predict(input)[0, 0]
                except Exception:
                    prediction = self.model.predict(input)[0]

            if prediction == -1:
                return "", "", -1, prediction_proba
            else:
                return (
                    self.model_prediction_to_interface_map[prediction],
                    self.model_prediction_to_mechatronic_interface_map[prediction],
                    prediction,
                    prediction_proba,
                )

        else:
            prediction = list(self.model.predict(input)[0])

            prediction = [prediction[0]] + [0] + prediction[1:] + [0, 0, 0]

            return (
                str(prediction),
                "",
                prediction,
                None,
            )

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

        self.load_function = FUNCTIONS_MAP[self.model_information["model_name"]][
            "load_function"
        ]

        model_class, self.is_classifier = MODELS_MAP[
            self.model_information["model_name"]
        ]

        self.model = self.load_function(
            self.model_information["model_path"],
            model_class(**self.model_information["model_params"]),  # noqa
        )

        return self.model_information
