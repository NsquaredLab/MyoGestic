from typing import Any

from myogestic.gui.widgets.output import VirtualHandInterface
from myogestic.gui.widgets.templates.output_system import OutputSystemTemplate

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


class VirtualHandInterfaceOutputSystem(OutputSystemTemplate):
    def __init__(self, main_window, prediction_is_classification: bool) -> None:
        super().__init__(main_window, prediction_is_classification)

        if type(main_window.selected_visual_interface) != VirtualHandInterface:
            raise ValueError(
                "The selected_visual_interface must be an instance of VirtualHandInterface."
                f"Got {type(main_window.selected_visual_interface)}."
            )

        self.outgoing_message_signal = (
            main_window.selected_visual_interface.outgoing_message_signal
        )

    def _process_prediction__classification(self, prediction: Any) -> Any:
        return PREDICTION2INTERFACE_MAP[prediction].encode("utf-8")

    def _process_prediction__regression(self, prediction: Any) -> Any:
        return str(prediction).encode("utf-8")

    def send_prediction(self, prediction: Any) -> None:
        self.outgoing_message_signal.emit(self.process_prediction(prediction))
