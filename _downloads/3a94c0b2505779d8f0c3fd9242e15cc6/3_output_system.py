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
# Step 1: Class Initialization
# -------------------------------------------------
# This step ensures that the selected visual interface is the Virtual Hand Interface.
# It also establishes the connection for outgoing signals using the main window.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/output_interface.py
#   :language: python
#   :lineno-match:
#   :lines: 1-55
#   :caption: Output System Initialization

# %%
# -------------------------------------------------
# Step 2: Processing Predictions
# -------------------------------------------------
# This step defines how predictions (either classification or regression) are processed
# into the appropriate format that can be used by the Virtual Hand Interface.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/output_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_OutputSystem._process_prediction__classification
#   :caption: Processing Classification Predictions - Convert classification predictions into the required format to send them to the visual interface.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/output_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_OutputSystem._process_prediction__regression
#   :caption: Processing Regression Predictions - Convert regression predictions into the required format to send them to the visual interface.

# %%
# -------------------------------------------------
# Step 3: Sending Predictions
# -------------------------------------------------
# This step sends the processed predictions (after formatting them into bytes)
# to the connected visual interface via the outgoing signal.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/output_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_OutputSystem.send_prediction
#   :caption: Sending Predictions - Send the processed prediction to the visual interface.

# %%
# -------------------------------------------------
# Step 4: Handling Close Events
# -------------------------------------------------
# This step handles the cleanup process when the Output System is closed.
# It logs the closure and ensures that resources are properly released.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/output_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_OutputSystem.close_event
#   :caption: Handling Close Events - Clean up resources and handle the exit process gracefully. If needed, this method can be extended to include additional cleanup steps.
