from typing import Any

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.output_system import OutputSystemTemplate
from myogestic.gui.widgets.visual_interfaces.virtual_cursor_interface.setup_interface import (
    VirtualCursorInterface_SetupInterface,
)

# Mapping from cursor prediction to interface coordinates
CURSOR_PREDICTION2INTERFACE_MAP = {
    0: (0, 0),
    1: (0, 1),
    2: (0, -1),
    3: (1, 0),
    4: (-1, 0),
}


class VirtualCursorInterface_OutputSystem(OutputSystemTemplate):
    """Output system for the Virtual Cursor Interface.

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
            self._main_window.logger.print("No visual interface selected.", level=LoggerLevel.ERROR)
            raise ValueError("No visual interface selected.")

        if not isinstance(
            self._main_window.selected_visual_interface.setup_interface_ui,
            VirtualCursorInterface_SetupInterface,
        ):
            raise ValueError(
                "The virtual interface must be the Virtual Cursor Interface."
                f"Got {type(self._main_window.selected_visual_interface)}."
            )

        self._outgoing_message_signal = self._main_window.selected_visual_interface.outgoing_message_signal

    def _process_prediction__classification(self, prediction: Any) -> bytes:
        """Process the prediction for classification."""
        return str(CURSOR_PREDICTION2INTERFACE_MAP[prediction]).encode("utf-8")

    def _process_prediction__regression(self, prediction: Any) -> bytes:
        """Process the prediction for regression."""
        return str((prediction[0], prediction[1])).encode("utf-8")

    def send_prediction(self, prediction: Any) -> None:
        """Send the prediction to the visual interface."""
        self._outgoing_message_signal.emit(self.process_prediction(prediction))

    def close_event(self, event):
        """Close the output system."""
        pass
