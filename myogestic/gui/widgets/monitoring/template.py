from PySide6.QtCore import Slot
from typing import Any

import numpy as np
from PySide6.QtWidgets import QMainWindow


class _MonitoringWidgetBaseClass(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model_information: dict[str, Any] = None

    def run_monitoring(self, data: np.ndarray):
        raise NotImplementedError()

    def _setup_functionality(self) -> None:
        raise NotImplementedError()

    @Slot(dict)
    def update_model_information(self, model_information: dict[str, Any]) -> None:
        self.model_information = model_information
