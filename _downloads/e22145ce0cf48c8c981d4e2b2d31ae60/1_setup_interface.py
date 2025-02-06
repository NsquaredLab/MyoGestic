"""
====================================
Part 1: Setup Interface
====================================

The setup interface is the first component of a visual interface in MyoGestic.

It is responsible for configuring the parameters, initializing the system, and managing the communication between MyoGestic and the visual interface.

Step 1: Create the setup UI
---------------------------
You will need an UI that will allow the user to start and stop the interface. This UI can be as simple as a button or as complex as you need.

.. note::
    To start copy the UI files in ``myogestic > gui > widgets > visual_interfaces > ui`` and adapt them with the functionality you need.

    You need to modify them with `QT-Designer <https://doc.qt.io/qtforpython-6/tools/pyside-designer.html>`_ and convert them using `UIC <https://doc.qt.io/qtforpython-6/tools/pyside-uic.html>`_ to a python file.

Step 2: Understand what is needed in the setup interface
--------------------------------------------------------
.. note::
    A setup interface is a class that inherits from

    .. currentmodule:: myogestic.gui.widgets.templates.visual_interface
    .. autosummary:: SetupInterfaceTemplate
        :toctree: generated/visual_interface

Please read the documentation of the class and make a mental note of what you have to provide (e.g. signals, methods, attributes)
and what you have to implement (e.g. start_interface, stop_interface, toggle_interface).

Step 3: Implement a setup interface (Example Virtual Hand Interface)
---------------------------------------------------------------------
This example focuses on implementing and adding the **setup interface** for the **Virtual Hand Interface** using the `VirtualHandInterface_SetupInterface` class from `setup_interface.py`.
We explain how it is constructed and registered into MyoGestic via `CONFIG_REGISTRY` in `config.py`.

Steps:
1. Define a custom `SetupInterface` class.
2. Manage the interface's state and initialization.
3. Handle communication with MyoGestic's runtime.
4. Handle custom data signals and data processing.
5. Register this class in MyoGestic's configuration registry.

"""

# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.1: Define the Setup Interface Class
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# This step implements the `VirtualHandInterface_SetupInterface` class, which initializes the
# Virtual Hand Interface, manages its state, and ensures communication with MyoGestic's runtime.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#  :language: python
#  :linenos:
#  :lines: 1-40
#  :caption: Imports
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#  :language: python
#  :linenos:
#  :lineno-match:
#  :lines: 41-89
#  :caption: Class Definition
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#    :language: python
#    :lineno-match:
#    :pyobject: VirtualHandInterface_SetupInterface._get_unity_executable
#    :caption: Helper Functions
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#    :language: python
#    :lineno-match:
#    :pyobject: VirtualHandInterface_SetupInterface._setup_timers
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.initialize_ui_logic
#   :caption: UI Setup

# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.2: Manage the Interface's State and Initialization
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# This step manages the state of the Virtual Hand Interface and initializes the interface's parameters.
# It also ensures that the interface is correctly set up and ready for use.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.start_interface
#   :caption: Start Interface - This method starts the interface.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.stop_interface
#   :caption: Stop Interface - This method stops the interface.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.interface_was_killed
#   :caption: Interface Was Killed - This method checks if the interface was killed (e.g. by the user closing the window).
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface._update_status
#   :caption: Update Status - This method updates the interface's status. If the interface is not running, it will be set to "Stopped".
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.toggle_virtual_hand_interface
#   :caption: Toggle Virtual Hand Interface - This method toggles the Virtual Hand Interface. If the interface is running, it will be stopped. If it is stopped, it will be started.

# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.3: Handle Communication with MyoGestic
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# This step manages the communication between the Virtual Hand Interface and MyoGestic's runtime.
# It ensures that the interface is correctly set up and ready for use.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.toggle_streaming
#   :caption: Toggle Streaming - This method toggles the streaming of data from MyoGestic to the Virtual Hand Interface.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.read_predicted_hand
#   :caption: Read Predicted Hand - This method reads the predicted hand from MyoGestic.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.read_message
#   :caption: Read/Write Message - This methods read and write messages from/to MyoGestic.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.write_message
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.write_status_message

# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.4: Handle Custom Data Signals
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# This step manages custom data signals and data processing for the Virtual Hand Interface.
# It ensures that the interface is correctly set up and ready for use.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.connect_custom_signals
#   :caption: Connect/Disconnect Custom Signals - This method connects/disconnects custom signals.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.process_custom_signals
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.online_predicted_hand_update
#   :caption: Online Predicted Hand Update - This method updates the predicted hand buffer with the current data.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.clear_custom_signal_buffers
#   :caption: Clear Custom Signal Buffers - This method clears the custom signal buffers.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/setup_interface.py
#   :language: python
#   :lineno-match:
#   :pyobject: VirtualHandInterface_SetupInterface.get_custom_save_data
#   :caption: Get Custom Save Data - This method will be called when saving the interface's data. This should return a dictionary with the data that needs to be saved.

# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.5: Register the Setup Interface in Config
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# This step integrates the `VirtualHandInterface_SetupInterface` class into the MyoGestic configuration.
# Once registered, the interface becomes available for use in the framework.
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface import VirtualHandInterface_SetupInterface
from myogestic.utils.config import CONFIG_REGISTRY


CONFIG_REGISTRY.register_visual_interface(
    name="VirtualHandInterface",  # Unique identifier for the visual interface.
    setup_interface_ui=VirtualHandInterface_SetupInterface,  # Associated setup class.
    recording_interface_ui=None,  # Placeholder (can be extended with a recording interface).
)
