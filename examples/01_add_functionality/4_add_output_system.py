"""
==============================
Add a Custom Output System
==============================

This example demonstrates how to build and register a new output system in **MyoGestic**.

By creating a subclass of the
generic :ref:`output_system_template`, you can channel model predictions into any
destination you like—such as a virtual environment or hardware device.

.. admonition:: We Recommend Implementing any Additions in *user_config.py*

   The *user_config.py* module is specifically designed for end-users to register
   and configure their own custom components such as models, features,
   and filters. This keeps your modifications modular, reduces conflicts with
   core MyoGestic settings, and simplifies upgrades in the future.

   .. important::
      By registering your addition in ``user_config.py``, you ensure that your custom
      configuration stays separate from core MyoGestic functionality and remains
      compatible with future updates.


Example Overview
----------------
1. **Create** a custom output system class by inheriting from ``OutputSystemTemplate``.
2. **Implement** the required methods for processing and sending predictions.
3. **Register** the output system into ``CONFIG_REGISTRY``.
4. (Optional) **Test** your new output system by selecting it in your MyoGestic
   workflow.

Notes on Implementation
-----------------------
The class design follows the interface defined by :ref:`output_system_template`, requiring:

- A constructor that takes in the ``main_window`` (as all QObject do) and a boolean flag for classification vs. regression.
- Definitions for:

  - ``_process_prediction__classification(prediction: Any) -> Any``
  - ``_process_prediction__regression(prediction: Any) -> Any``
  - ``send_prediction(prediction: Any) -> None``
  - ``closeEvent(event) -> None``

Below, we provide a simplified demonstration that mirrors how you might adapt a
neural rehabilitation device interface or a virtual hand interface. For further
examples of fully featured implementations, see references in MyoGestic's existing
output systems.

"""

# %%
# --------------------------------------
# Step 1: Define Your Custom Output System
# --------------------------------------
from typing import Any
from myogestic.gui.widgets.templates.output_system import OutputSystemTemplate


class MyCustomOutputSystem(OutputSystemTemplate):
    """
    A simple example output system for demonstration purposes.

    This class shows how to inherit from OutputSystemTemplate and implement
    the required abstract methods. It can send predictions to any desired
    interface or hardware, provided you adapt the methods below.
    """

    def __init__(self, main_window, prediction_is_classification: bool) -> None:
        """
        Initialize the custom output system.

        Parameters
        ----------
        main_window : Any
            The main window object containing a logger or other references.
        prediction_is_classification : bool
            Set to True for classification tasks, False for regression.
        """
        super().__init__(main_window, prediction_is_classification)
        # (Optional) Initialize sockets, signals, or other resources here

    def _process_prediction__classification(self, prediction: Any) -> Any:
        """
        Convert a classification prediction into a format suitable
        for your output system or interface.
        """
        # Replace with your own logic or mappings
        return f"Classification: {prediction}".encode("utf-8")

    def _process_prediction__regression(self, prediction: Any) -> Any:
        """
        Convert a regression prediction into a format suitable
        for your output system or interface.
        """
        # Replace with your own logic or mappings
        return f"Regression: {prediction}".encode("utf-8")

    def send_prediction(self, prediction: Any) -> None:
        """
        Send the processed prediction to your output destination.
        """
        processed = self.process_prediction(prediction)
        # For demonstration, we simply print the processed data
        self._main_window.logger.print(
            f"Sending: {processed}",
        )

    def close_event(self, event) -> None:
        """
        Handle any cleanup needed when your system closes.
        """
        # Close sockets, timers, or other resources here
        pass


# %%
# -------------------------------------------------
# Step 2: Register the Output System in CONFIG_REGISTRY
# -------------------------------------------------
from myogestic.utils.config import CONFIG_REGISTRY

CONFIG_REGISTRY.register_output_system(
    name="MyCustomOutputSystem", output_system=MyCustomOutputSystem
)

# %%
# -------------------------------
# Example: Virtual Hand Interface
# -------------------------------
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/output_interface.py
#   :language: python
#   :lineno-match:

