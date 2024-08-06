from __future__ import annotations
from typing import TYPE_CHECKING, Any, Dict, Union

from PySide6.QtCore import QObject

# MindMove imports
from myogestic.models.core.model import MyogesticModel
from myogestic.models.core.dataset import MyogesticDataset

if TYPE_CHECKING:
    import numpy as np
    from myogestic.gui.widgets.logger import CustomLogger


class MyogesticModelInterface(QObject):
    def __init__(
        self,
        device_information: dict[str, Any],
        logger: CustomLogger,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self.logger = logger

        self.model: MyogesticModel = MyogesticModel(logger=self.logger)
        self.dataset: MyogesticDataset = MyogesticDataset(
            device_information=device_information, logger=self.logger
        )
        self.input_dataset: dict = None
        self.model_is_loaded: bool = False

    def create_dataset(
        self, dataset: Dict, selected_features: list[str]
    ) -> Dict[str, Dict[str, Any]]:
        self.input_dataset = self.dataset.create_dataset(dataset, selected_features)
        return self.input_dataset

    def train_model(
        self,
        dataset: Dict[str, Dict[str, Any]],
        model_name: str,
        model_parameters: dict[str, Any],
        save_function: callable,
        load_function: callable,
        train_function: callable,
        selected_features: list[str],
    ) -> None:
        self.model.train(
            dataset,
            model_name,
            model_parameters,
            save_function,
            load_function,
            train_function,
            selected_features,
        )

    def predict(
        self,
        input: np.ndarray,
        bad_channels: list[int] = [],
    ) -> tuple[str, str, int, np.ndarray]:
        if not self.model_is_loaded:
            raise ValueError("Model is not loaded!")

        preprocessed_input = self.dataset.preprocess_data(
            input,
            bad_channels=bad_channels,
            selected_features=self.model.model_information["selected_features"],
        )
        if preprocessed_input is None:
            return "Bad channels detected", "", -1, None
        return self.model.predict(preprocessed_input)

    def save_model(self, model_path: str) -> dict[str, Union[str, Any]]:
        self.input_dataset = None
        return self.model.save(model_path)

    def load_model(self, model_path: str) -> dict:
        model_information = self.model.load(model_path)
        self.dataset.set_online_parameters(model_information)

        # Set the models as loaded
        self.model_is_loaded = True

        return model_information

    def set_conformal_predictor(self, params: dict) -> None:
        self.model.set_conformal_predictor(params)
