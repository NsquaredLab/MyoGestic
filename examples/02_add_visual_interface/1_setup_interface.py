"""
====================================
Part 1: Setup Interface
====================================

This example demonstrates how to integrate a **setup interface** for a visual interface in MyoGestic.

.. note::
    Visual interfaces in MyoGestic must include three modular components:

        1. **Setup Interface**: Configures the parameters and initializes the system (e.g. hardware, data pipeline).
        2. **Recording Interface**: Manages runtime interactions and data visualization.
        3. **Output Interface**: Defines how results are presented (e.g., virtual hands, plots).

.. important::
   The visual interface is generally intended to be a standalone program that can communicate (both receiving and sending) through information exchange protocols (e.g., UDP).
   This way the visual interface is a standalone process that will not be hindered by MyoGestic's runtime.

This example focuses on implementing and adding the **setup interface** for the **Virtual Hand Interface** using the `VirtualHandInterface_SetupInterface` class from `setup_interface.py`.
We explain how it is constructed and registered into MyoGestic via `CONFIG_REGISTRY` in `config.py`.

Steps:
-----
1. Define a custom `SetupInterface` class.
2. Register this class in MyoGestic's configuration registry.
3. Validate and test your interface within the framework.

"""

# %%
# -------------------------------------------------
# Step 1: Define the Setup Interface Class
# -------------------------------------------------
# **Description:**
# This step implements the `VirtualHandInterface_SetupInterface` class, which initializes the
# Virtual Hand Interface, manages its state, and ensures communication with MyoGestic's runtime.

from PySide6.QtCore import QTimer, Signal, QProcess
from myogestic.utils.config import CONFIG_REGISTRY
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface.ui import (
    Ui_SetupVirtualHandInterface,
)
from myogestic.gui.widgets.templates.visual_interface import SetupInterfaceTemplate
import numpy as np
import time


class VirtualHandInterface_SetupInterface(SetupInterfaceTemplate):
    """
    Setup Interface for the Virtual Hand Interface.

    This class configures parameters, initializes the system, and manages communication
    between MyoGestic and the Virtual Hand Interface.

    Parameters
    ----------
    main_window : QMainWindow
        The main application window of MyoGestic where this interface resides.
    name : str, optional
        Unique name assigned to the interface. Defaults to "VirtualHandInterface".
    ui : Ui_SetupVirtualHandInterface
        Associated UI layout for the setup interface.
    """

    # Custom Signals
    predicted_hand_signal = Signal(np.ndarray)  # Signal to send predicted hand data.

    def __init__(self, main_window, name="VirtualHandInterface"):
        super().__init__(main_window, name, ui=Ui_SetupVirtualHandInterface())

        # Runtime management tools
        self._setup_timers()  # Configure timers for querying the interface.
        self._unity_process = QProcess()  # Backend process management.
        self._recording_buffer = []

        # Connection and status attributes
        self._is_connected: bool = False  # Tracks the connection state.
        self._last_message_time = time.time()  # Last received communication timestamp.

        # Initialize the setup interface's UI
        self.initialize_ui_logic()

    def _setup_timers(self):
        """
        Configure and initialize timers for periodic interface communication.
        """
        self.status_request_timer = QTimer(self)
        self.status_request_timer.setInterval(
            2000
        )  # Set interval to 2 seconds for status updates.

    def initialize_ui_logic(self):
        """
        Link widgets and initialize event listeners.
        """
        self.toggle_virtual_hand_interface_push_button = (
            self.ui.toggleVirtualHandInterfacePushButton
        )
        self.toggle_virtual_hand_interface_push_button.clicked.connect(
            self.toggle_virtual_hand_interface
        )

    def start_interface(self):
        """
        Start the interface and initialize its runtime components.
        """
        print("Starting Virtual Hand Interface")
        self.status_request_timer.start()  # Begin periodic status requests.

    def stop_interface(self):
        """
        Stop the interface and release its runtime resources.
        """
        print("Stopping Virtual Hand Interface")
        self.status_request_timer.stop()  # Stop querying the interface.

    def toggle_virtual_hand_interface(self):
        """
        Toggle the connection to the Virtual Hand Interface.
        """
        if self.toggle_virtual_hand_interface_push_button.isChecked():
            self.start_interface()  # Start when the button is toggled on.
        else:
            self.stop_interface()  # Stop when the button is toggled off.


# %%
# -------------------------------------------------
# Step 2: Register the Setup Interface in Config
# -------------------------------------------------
# **Description:**
# This step integrates the `VirtualHandInterface_SetupInterface` class into the MyoGestic configuration.
# Once registered, the interface becomes available for use in the framework.

CONFIG_REGISTRY.register_visual_interface(
    name="VirtualHandInterface",  # Unique identifier for the visual interface.
    setup_interface_ui=VirtualHandInterface_SetupInterface,  # Associated setup class.
    recording_interface_ui=None,  # Placeholder (can be extended with a recording interface).
)

# %%
# ---------------------------------
# Summary of the Registration
# ---------------------------------
# - The `VirtualHandInterface_SetupInterface` is responsible for connection setup,
#   configuration, and system lifecycle management.
# - Registration ensures this interface becomes part of MyoGestic's framework and
#   can be accessed or extended in other modules.

# %%
# Next Steps
# ----------
# 1. Implement complementary components (like Recording and Output interfaces) to
#    extend the functionality of the Virtual Hand Interface within MyoGestic.
# 2. Load the interface in the framework and validate its behavior.
