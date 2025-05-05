from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

from PySide6.QtCore import QObject

from myogestic.models.core.dataset import MyoGesticDataset
from myogestic.models.core.model import MyoGesticModel
from myogestic.utils.config import CONFIG_REGISTRY

if TYPE_CHECKING:
    import numpy as np
    from myogestic.gui.widgets.logger import CustomLogger


class MyoGesticModelInterface(QObject):
    def __init__(
        self,
        device_information: dict[str, Any],
        logger: CustomLogger,
        parent
    ) -> None:
        super().__init__(parent)

        from myogestic.gui.myogestic import MyoGestic
        self._main_window: MyoGestic = parent

        self.logger = logger

        self.model: MyoGesticModel = MyoGesticModel(logger=self.logger, parent=self._main_window)
        self.dataset: MyoGesticDataset = MyoGesticDataset(
            device_information=device_information, logger=self.logger, parent=self._main_window
        )
        self.input_dataset: dict = {}
        self.model_is_loaded: bool = False

    def create_dataset(
        self, dataset: Dict, selected_features: list[str], file_name: str, recording_interface_from_recordings:str
    ) -> Dict[str, Dict[str, Any]]:
        self.input_dataset = self.dataset.create_dataset(
            dataset, selected_features, file_name, recording_interface_from_recordings
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
        self,
        input: np.ndarray,
        bad_channels: list[int] = (),
        selected_real_time_filter: str = "",
    ) -> tuple[Any, list[Any] | None, str | None]:
        if not self.model_is_loaded:
            raise ValueError("Model is not loaded!")

        preprocessed_input = self.dataset.preprocess_data(
            input,
            bad_channels=bad_channels,
            selected_features=self.model.model_information["selected_features"],
        )

        if preprocessed_input is None:
            return -1, None, None

        return self.model.predict(
            preprocessed_input, self.predict_function, selected_real_time_filter
        )

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
