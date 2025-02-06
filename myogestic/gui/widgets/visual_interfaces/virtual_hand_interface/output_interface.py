from typing import Any

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.output_system import OutputSystemTemplate
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface.setup_interface import (
    VirtualHandInterface_SetupInterface,
)

PREDICTION2INTERFACE_MAP = {
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


class VirtualHandInterface_OutputSystem(OutputSystemTemplate):
    """Output system for the Virtual Hand Interface.

    Parameters
    ----------
    main_window : MainWindow
        The main window object.
    prediction_is_classification : bool
        Whether the prediction is a classification or regression.
    """

    def __init__(self, main_window, prediction_is_classification: bool) -> None:
        super().__init__(main_window, prediction_is_classification)

        if self._main_window.selected_visual_interface is None:
            self._main_window.logger.print(
                "No visual interface selected.", level=LoggerLevel.ERROR
            )
            raise ValueError("No visual interface selected.")

        if not isinstance(
            self._main_window.selected_visual_interface.setup_interface_ui,
            VirtualHandInterface_SetupInterface,
        ):
            raise ValueError(
                "The virtual interface must be the Virtual Hand Interface."
                f"Got {type(self._main_window.selected_visual_interface)}."
            )

        self._outgoing_message_signal = (
            self._main_window.selected_visual_interface.outgoing_message_signal
        )

    def _process_prediction__classification(self, prediction: Any) -> bytes:
        """Process the prediction for classification."""
        return PREDICTION2INTERFACE_MAP[prediction].encode("utf-8")

    def _process_prediction__regression(self, prediction: Any) -> bytes:
        """Process the prediction for regression."""
        return str(prediction).encode("utf-8")

    def send_prediction(self, prediction: Any) -> None:
        """Send the prediction to the visual interface."""
        self._outgoing_message_signal.emit(self.process_prediction(prediction))

    def close_event(self, event):
        """Close the output system."""
        pass
