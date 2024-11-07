from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

from PySide6.QtCore import QObject

from myogestic.models.config import CONFIG_REGISTRY
from myogestic.models.core.dataset import MyoGesticDataset
from myogestic.models.core.model import MyoGesticModel

if TYPE_CHECKING:
    import numpy as np
    from myogestic.gui.widgets.logger import CustomLogger


class MyoGesticModelInterface(QObject):
    def __init__(
        self,
        device_information: dict[str, Any],
        logger: CustomLogger,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self.logger = logger

        self.model: MyoGesticModel = MyoGesticModel(logger=self.logger)
        self.dataset: MyoGesticDataset = MyoGesticDataset(
            device_information=device_information, logger=self.logger
        )
        self.input_dataset: dict = {}
        self.model_is_loaded: bool = False

    def create_dataset(
        self, dataset: Dict, selected_features: list[str], file_name: str
    ) -> Dict[str, Dict[str, Any]]:
        self.input_dataset = self.dataset.create_dataset(
            dataset, selected_features, file_name
        )
        return self.input_dataset

    def train_model(
        self,
        dataset: Dict[str, Dict[str, Any]],
        model_name: str,
        model_parameters: dict[str, Any],
        save: callable,
        load: callable,
        train: callable,
        selected_features: list[str],
    ) -> None:
        self.model.train(
            dataset, model_name, model_parameters, save, load, train, selected_features
        )

    def predict(
        self, input: np.ndarray, bad_channels: list[int] = ()
    ) -> tuple[str, str, int, np.ndarray | None]:
        if not self.model_is_loaded:
            raise ValueError("Model is not loaded!")

        preprocessed_input = self.dataset.preprocess_data(
            input,
            bad_channels=bad_channels,
            selected_features=self.model.model_information["selected_features"],
        )
        if preprocessed_input is None:
            return "Bad channels detected", "", -1, None
        return self.model.predict(preprocessed_input, self.predict_function)

    def save_model(self, model_path: str) -> dict[str, str | None]:
        self.input_dataset = None
        return self.model.save(model_path)

    def load_model(self, model_path: str) -> dict:
        model_information = self.model.load(model_path)
        self.dataset.set_online_parameters(model_information)

        self.predict_function = CONFIG_REGISTRY.models_functions_map[
            model_information["model_name"]
        ]["predict"]

        # Set the models as loaded
        self.model_is_loaded = True

        return model_information

    def set_conformal_predictor(self, params: dict) -> None:
        self.model.set_conformal_predictor(params)
