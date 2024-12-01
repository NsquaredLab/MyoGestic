import numpy as np


class _MonitoringWidgetBaseClass:
    def run(self, data: np.ndarray):
        raise NotImplementedError()

    def _setup_functionality(self) -> None:
        raise NotImplementedError()
