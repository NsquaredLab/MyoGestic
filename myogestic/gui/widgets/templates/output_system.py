from abc import ABC, abstractmethod
from typing import Any

from PySide6.QtWidgets import QMainWindow


class OutputSystemTemplate(ABC):
    def __init__(
        self, main_window: QMainWindow = None, prediction_is_classification: bool = None
    ) -> None:
        if main_window is None:
            raise ValueError("The main_window must be provided.")
        if prediction_is_classification is None:
            raise ValueError("The prediction_is_classification must be provided.")

        self.main_window = main_window
        self.prediction_is_classification = prediction_is_classification

        self.process_prediction = (
            self._process_prediction__classification
            if self.prediction_is_classification
            else self._process_prediction__regression
        )

    @abstractmethod
    def _process_prediction__classification(self, prediction: Any) -> Any:
        pass

    @abstractmethod
    def _process_prediction__regression(self, prediction: Any) -> Any:
        pass

    @abstractmethod
    def send_prediction(self, prediction: Any) -> None:
        pass

    @abstractmethod
    def closeEvent(self, event: QCloseEvent):  # noqa
        pass
