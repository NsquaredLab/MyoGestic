"""
==============================================
Part 3: Output System
==============================================

This implementation demonstrates the creation of an **Output System** for the Virtual Hand Interface.
It processes predictions (classification or regression) and communicates them to the visual interface.

Steps:
--------------
1. **Step 1: Class Initialization and Validation**
    - Ensures the correct visual interface is selected and initializes helper objects.

2. **Step 2: Processing Predictions**
    - Converts classification and regression predictions into an appropriate format.

3. **Step 3: Sending Predictions**
    - Sends processed predictions to the visual interface via output signals.

4. **Step 4: Handling Close Events**
    - Cleans up resources and handles the exit process gracefully.

"""


# %%
# -------------------------------------------------
# Predefined Mapping for Classification Predictions
# -------------------------------------------------
# This dictionary maps classification labels to their respective predefined
# output strings for the Virtual Hand Interface.
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

# %%
# -------------------------------------------------
# Step 1: Class Initialization and Validation
# -------------------------------------------------
# This step ensures that the selected visual interface is the Virtual Hand Interface.
# It also establishes the connection for outgoing signals using the main window.

from typing import Any
from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.output_system import OutputSystemTemplate
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface.setup_interface import (
    VirtualHandInterface_SetupInterface,
)

class VirtualHandInterface_OutputSystem(OutputSystemTemplate):
    """
    Output system for the Virtual Hand Interface.

    This class processes predictions (classification or regression) and sends them
    to the Virtual Hand visual interface for visualization or further actions.

    Parameters
    ----------
    main_window : MainWindow
        Reference to the parent application window.
    prediction_is_classification : bool
        Determines if the prediction is classification (True) or regression (False).
    """

    def __init__(self, main_window, prediction_is_classification: bool) -> None:
        # Initialize the base class
        super().__init__(main_window, prediction_is_classification)

        # Verify that a visual interface is selected
        if self._main_window.selected_visual_interface is None:
            self._main_window.logger.print(
                "Error: No visual interface selected.", level=LoggerLevel.ERROR
            )
            raise ValueError("No visual interface selected.")

        # Validate that the selected interface is of the correct type
        if not isinstance(
            self._main_window.selected_visual_interface.setup_interface_ui,
            VirtualHandInterface_SetupInterface,
        ):
            raise ValueError(
                f"Error: Expected Virtual Hand Interface, but got {type(self._main_window.selected_visual_interface).__name__}."
            )

        # Set up the outgoing message signal for communication
        self._outgoing_message_signal = (
            self._main_window.selected_visual_interface.outgoing_message_signal
        )

# %%
# -------------------------------------------------
# Step 2: Processing Predictions
# -------------------------------------------------
# This step defines how predictions (either classification or regression) are processed
# into the appropriate format that can be used by the Virtual Hand Interface.

def _process_prediction__classification(self, prediction: Any) -> bytes:
    """
    Convert classification type predictions into the required Virtual Hand format.

    Parameters
    ----------
    prediction : int
        Classification label corresponding to a defined task.

    Returns
    -------
    bytes
        Encoded string representation of the classification output.
    """
    self._main_window.logger.print(
        f"Processing classification prediction: {prediction}"
    )
    return PREDICTION2INTERFACE_MAP.get(prediction, "Invalid Prediction").encode(
        "utf-8"
    )

def _process_prediction__regression(self, prediction: Any) -> bytes:
    """
    Convert regression type predictions into the required Virtual Hand format.

    Parameters
    ----------
    prediction : list[float]
        A list of float values representing regression outputs.

    Returns
    -------
    bytes
        Encoded string representation of the regression output.
    """
    self._main_window.logger.print(
        f"Processing regression prediction: {prediction}"
    )
    formatted_prediction = [prediction[0]] + [0] + prediction[1:] + [0, 0, 0]
    return str(formatted_prediction).encode("utf-8")

# %%
# -------------------------------------------------
# Step 3: Sending Predictions
# -------------------------------------------------
# This step sends the processed predictions (after formatting them into bytes)
# to the connected visual interface via the outgoing signal.

def send_prediction(self, prediction: Any) -> None:
    """
    Send the processed prediction to the visual interface.

    Parameters
    ----------
    prediction : Any
        The raw prediction output from the model.

    Notes
    -----
    Predictions are processed (classification or regression) and sent in an encoded byte format
    using the outgoing message signal.
    """
    processed_output = self.process_prediction(prediction)
    self._main_window.logger.print(
        f"Sending prediction: {processed_output.decode('utf-8')}"
    )
    self._outgoing_message_signal.emit(processed_output)

# %%
# -------------------------------------------------
# Step 4: Handling Close Events
# -------------------------------------------------
# This step handles the cleanup process when the Output System is closed.
# It logs the closure and ensures that resources are properly released.

def closeEvent(self, event) -> None:
    """
    Handle the closure of the output system.

    Parameters
    ----------
    event : QCloseEvent
        The close event triggered by the parent application.
    """
    self._main_window.logger.print("Closing Virtual Hand Output System.")
    pass
