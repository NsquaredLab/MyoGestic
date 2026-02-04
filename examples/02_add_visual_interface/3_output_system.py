"""
==============================================
Part 3: Output System
==============================================

The output system is the third component of a visual interface.  It
processes model predictions (classification or regression) and sends them
to the external VI application.

Multi-VI Architecture
----------------------
MyoGestic supports multiple active visual interfaces simultaneously.
When a model is loaded in the Online tab, the :class:`~myogestic.gui.protocols.OnlineProtocol` creates
one output system per active VI:

.. code-block:: python

    active_vis = self._main_window.active_visual_interfaces  # dict[str, VI]
    self._output_systems = {
        vi_name: CONFIG_REGISTRY.output_systems_map[vi_name](
            self._main_window, model.is_classifier
        )
        for vi_name in active_vis
        if vi_name in CONFIG_REGISTRY.output_systems_map
    }

Each prediction is then sent to **all** active output systems:

.. code-block:: python

    for output_system in self._output_systems.values():
        output_system.send_prediction(prediction)

Accessing Your VI
------------------
From within an output system, access the target VI via the
``active_visual_interfaces`` dict:

.. code-block:: python

    vi = self._main_window.active_visual_interfaces.get("VHI")
    self._outgoing_signal = vi.outgoing_message_signal

Required Methods
-----------------
See :ref:`output_system_template` for the full base class API.  You must
implement:

- :meth:`~myogestic.gui.widgets.templates.OutputSystemTemplate._process_prediction__classification`
- :meth:`~myogestic.gui.widgets.templates.OutputSystemTemplate._process_prediction__regression`
- :meth:`~myogestic.gui.widgets.templates.OutputSystemTemplate.send_prediction`
- :meth:`~myogestic.gui.widgets.templates.OutputSystemTemplate.close_event`

Classification Prediction Map
------------------------------
For classifiers, you typically map integer labels to output strings.
The VHI maps 10 gestures (labels 0-9, plus -1 for rejected samples)
to 9-element float vectors representing finger joint positions:

.. code-block:: python

    PREDICTION2INTERFACE_MAP = {
        -1: "Rejected Sample",
         0: "[0, 0, 0, 0, 0, 0, 0, 0, 0]",       # rest
         1: "[0, 0, 1, 0, 0, 0, 0, 0, 0]",         # index
         2: "[1, 0, 0, 0, 0, 0, 0, 0, 0]",         # thumb
         ...
         9: "[0, 0, 1, 0, 0, 0, 0, 1, 0]",         # pointing
    }

"""


# %%
# ----------------------------------------
# Step 1: Define Your Output System
# ----------------------------------------
from typing import Any
from myogestic.gui.widgets.templates.output_system import OutputSystemTemplate
from myogestic.gui.widgets.logger import LoggerLevel

# Prediction label to output string mapping (for classifiers)
PREDICTION_MAP = {
    -1: "Rejected",
    0: "[0, 0, 0]",  # rest
    1: "[1, 0, 0]",  # action_a
    2: "[0, 1, 0]",  # action_b
}


class MyInterface_OutputSystem(OutputSystemTemplate):
    """Output system for a custom visual interface.

    Validates that the target VI is active, then routes predictions
    to it via the outgoing signal.
    """

    def __init__(self, main_window, prediction_is_classification: bool) -> None:
        super().__init__(main_window, prediction_is_classification)

        # Validate that our target VI is active
        vi = self._main_window.active_visual_interfaces.get("MYI")
        if vi is None:
            raise ValueError("MYI (My Interface) is not active.")

        # Grab the outgoing signal for sending predictions
        self._outgoing_signal = vi.outgoing_message_signal

    def _process_prediction__classification(self, prediction: Any) -> bytes:
        """Map a classification label to an output string."""
        return PREDICTION_MAP.get(prediction, "Unknown").encode("utf-8")

    def _process_prediction__regression(self, prediction: Any) -> bytes:
        """Convert regression values to a string representation."""
        return str([float(x) for x in prediction]).encode("utf-8")

    def send_prediction(self, prediction: Any) -> None:
        """Send the processed prediction to the VI via UDP."""
        processed = self.process_prediction(prediction)
        self._outgoing_signal.emit(processed)

    def close_event(self, event) -> None:
        """Clean up resources."""
        pass


# %%
# -------------------------------------------------
# Step 2: Register the Output System
# -------------------------------------------------
from myogestic.utils.config import CONFIG_REGISTRY

CONFIG_REGISTRY.register_output_system(
    name="MYI", output_system=MyInterface_OutputSystem
)


# %%
# -------------------------------------------
# Reference: VHI Output System
# -------------------------------------------
# The VHI output system validates that ``"VHI"`` is among the active
# visual interfaces, maps 10 classification labels to hand poses, and
# sends predictions via UDP.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/output_interface.py
#    :language: python
#    :lineno-match:
#    :caption: VHI Output System -- full implementation
