"""
=========================================
Part 2: Recording Interface
=========================================

The recording interface is the second component of a visual interface in MyoGestic.

It is responsible for managing the ground-truth data collection.
Since the ground-truth data depends on the visual interface, the recording interface must define the data collection process.

Step 1: Create the setup UI
---------------------------
You will need an UI that will allow the user to start the recording, visualize the progress, and save the data.

.. note::
    To start copy the UI files in ``myogestic > gui > widgets > visual_interfaces > ui`` and adapt them with the functionality you need.

    You need to modify them with `QT-Designer <https://doc.qt.io/qtforpython-6/tools/pyside-designer.html>`_ and convert them using `UIC <https://doc.qt.io/qtforpython-6/tools/pyside-uic.html>`_ to a python file.


Step 2: Understand what is needed in the recording interface
------------------------------------------------------------
.. note::
    A recording interface is a class that inherits from

    .. currentmodule:: myogestic.gui.widgets.templates.visual_interface
    .. autosummary:: RecordingInterfaceTemplate
        :toctree: generated/visual_interface

Please read the documentation of the class and make a mental note of what you have to provide (e.g. signals, methods, attributes)
and what you have to implement (e.g. start_recording, stop_recording, accept_recording).

Step 3: Implement a recording interface (Example Virtual Hand Interface)
-------------------------------------------------------------------------
This example focuses on implementing and adding the **recording interface** for the **Virtual Hand Interface** using the `VirtualHandInterface_RecordingInterface` class from `recording_interface.py`.
We explain how it is constructed and registered into MyoGestic via `CONFIG_REGISTRY` in `config.py`.

Steps:

1. Class Initialization and UI Setup
2. Starting & Stopping Recordings
3. Managing Recording Sessions
4. Resetting the Interface
"""

# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.1: Class Initialization and UI Setup
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# This step initializes the recording interface’s buffers and task-related attributes.
# It also configures the UI elements required for this interface.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#    :language: python
#    :linenos:
#    :lines: 1-16
#    :caption: Imports
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#    :language: python
#    :lineno-match:
#    :lines: 17-71
#    :caption: Class Initialization
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#    :language: python
#    :lineno-match:
#    :pyobject: VirtualHandInterface_RecordingInterface.initialize_ui_logic
#    :caption: UI Setup


# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.2: Starting & Stopping Recordings
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# This step manages the logic for starting or stopping recording sessions,
# which includes preparing recording parameters and updating the UI.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_RecordingInterface.start_recording_preparation
#   :caption: Start Recording Preparation - This method prepares the recording session.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_RecordingInterface.start_recording
#   :caption: Start Recording - This method starts the recording session.
#

# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.3: Managing Recording Sessions
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# This step manages the recording session, which includes updating the UI and recording data.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_RecordingInterface.update_ground_truth_buffer
#   :caption: Update Ground Truth Buffer - This method updates the ground-truth buffer with the current data.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_RecordingInterface.check_recording_completion
#   :caption: Check Recording Completion - This method checks if the recording session is complete.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_RecordingInterface.finish_recording
#   :caption: Finish Recording - This method finalizes the recording session.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_RecordingInterface.accept_recording
#   :caption: Accept Recording - This method accepts the recorded data and saves it.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_RecordingInterface.reject_recording
#   :caption: Reject Recording - This method rejects the recorded data and discards it.

# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.4: Resetting the Interface
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# This step resets the recording interface to its initial state.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_RecordingInterface.reset_ui
#   :caption: Reset UI - This method resets the recording interface's UI elements.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_RecordingInterface.close_event
#   :caption: Close Event - This method handles the closing event of the recording interface.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_RecordingInterface.enable
#   :caption: Enable - This method enables the recording interface.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_RecordingInterface.disable
#   :caption: Disable - This method disables the recording interface.
