from abc import abstractmethod
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtGui import QCloseEvent

from myogestic.gui.widgets.templates.meta_qobject import MetaQObjectABC


class OutputSystemTemplate(QObject, metaclass=MetaQObjectABC):
    def __init__(
        self, main_window=None, prediction_is_classification: bool = None
    ) -> None:
        super().__init__()

        if main_window is None:
            raise ValueError("The _main_window must be provided.")
        if prediction_is_classification is None:
            raise ValueError("The _prediction_is_classification must be provided.")

        self._main_window = main_window
        self._prediction_is_classification = prediction_is_classification

        self.process_prediction = (
            self._process_prediction__classification
            if self._prediction_is_classification
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
