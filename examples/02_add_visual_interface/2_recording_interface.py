"""
=========================================
Part 2: Recording Interface
=========================================

The recording interface is the second component of a visual interface in
MyoGestic.  It manages per-VI recording settings and ground truth data
collection.

Shared Task Selector
---------------------
Tasks are **no longer managed per-VI**.  A shared task selector in the
:class:`~myogestic.gui.protocols.RecordProtocol` manages task selection for all active VIs.  The per-VI
task combo box is hidden during :meth:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.initialize_ui_logic`, and the
:attr:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate._current_task` attribute is set by the RecordProtocol before each
recording.

VIs in the same category share a task map:

- **Hand** VIs (VHI, KHI) use ``HAND_TASK_MAP`` (10 gestures).
- **Cursor** VIs (VCI) use ``CURSOR_TASK_MAP`` (5 directions).

To register your VI in a task category, add an entry to
``VI_TASK_CATEGORY`` in ``myogestic/gui/protocols/record.py``:

.. code-block:: python

    VI_TASK_CATEGORY["MYI"] = ("Hand", HAND_TASK_MAP)

Ground Truth Data
------------------
Each recording interface must define:

- :attr:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.ground_truth__task_map` -- Maps task names to integer labels.  This
  should match the task map for your VI's category.
- :attr:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.ground_truth__nr_of_recording_values` -- Number of DOF values
  recorded per sample (independent of the number of tasks).  For the VHI
  this is 9 (thumb + 4 fingers + 3 wrist + 1 grasp).

The :meth:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.get_ground_truth_data` method returns a dict with the collected
ground truth after recording.  During multi-VI recordings, the
:class:`~myogestic.gui.protocols.RecordProtocol` collects data from each active VI's
:meth:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.get_ground_truth_data` and saves them in a combined pickle.

Step 1: Create the Recording UI
---------------------------------
Your recording UI **must** include a ``QProgressBar`` named
``groundTruthProgressBar``.  Other common widgets:

- ``recordRecordingGroupBox`` -- Per-VI settings group box.
- ``recordUseKinematicsCheckBox`` -- Toggle kinematics recording.

.. note::
   Copy an existing UI file from
   ``myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/ui/``
   and adapt it.

Step 2: Understand the Base Class
----------------------------------
.. currentmodule:: myogestic.gui.widgets.templates.visual_interface
.. autosummary:: RecordingInterfaceTemplate
    :toctree: generated/visual_interface

Key constructor parameters:

- :attr:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.incoming_message_signal` -- Signal carrying kinematics data from the
  setup interface's UDP receiver.
- :attr:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.ground_truth__nr_of_recording_values` -- Number of DOF values per
  sample.
- :attr:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.ground_truth__task_map` -- Task name to label mapping.

You **must** implement:

- :meth:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.initialize_ui_logic` -- Wire up widgets, hide per-VI controls.
- :meth:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.enable` / :meth:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.disable` -- Enable/disable the per-VI group box.
- :meth:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.close_event` -- Clean up buffers.

You **should** implement:

- :meth:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.start_recording_preparation` -- Validate state, clear
  buffers, calculate expected samples.
- :meth:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.update_ground_truth_buffer` -- Append incoming kinematics
  data and update the progress bar.
- :meth:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.check_recording_completion` -- Notify the protocol when done.
- :meth:`~myogestic.gui.widgets.templates.RecordingInterfaceTemplate.get_ground_truth_data` -- Return collected ground truth.

Step 3: Implement a Recording Interface
-----------------------------------------
Below is a minimal example, followed by references to the VHI
implementation.

"""

# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.1: Minimal Recording Interface
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# This skeleton shows the required structure.  In practice, you would
# add kinematics buffering, progress tracking, and UI wiring.

import time
import numpy as np
from PySide6.QtCore import SignalInstance
from PySide6.QtGui import QCloseEvent

from myogestic.gui.widgets.templates.visual_interface import RecordingInterfaceTemplate

KINEMATICS_SAMPLING_FREQUENCY = 60


class MyInterface_RecordingInterface(RecordingInterfaceTemplate):
    """Minimal recording interface example."""

    ground_truth__task_map: dict[str, int] = {
        "rest": 0,
        "action_a": 1,
        "action_b": 2,
    }
    ground_truth__nr_of_recording_values: int = 5  # Number of DOF per sample

    def __init__(
        self,
        main_window,
        name: str = "MyInterface",
        incoming_message_signal: SignalInstance = None,
    ) -> None:
        # In practice, pass your generated UI:
        # from .ui import Ui_RecordingMyInterface
        # super().__init__(main_window, name, ui=Ui_RecordingMyInterface(), ...)
        pass  # Replace with real init

    def initialize_ui_logic(self) -> None:
        """Wire up UI and hide per-VI controls managed by RecordProtocol."""
        # Add per-VI GroupBox to the record layout
        # self._main_window.ui.recordVerticalLayout.addWidget(...)
        #
        # Hide per-VI task selector (shared selector handles this):
        # self.record_task_combo_box.hide()
        pass

    def start_recording_preparation(self) -> bool:
        """Validate state and prepare for recording."""
        return True

    def update_ground_truth_buffer(self, data: np.ndarray) -> None:
        """Append kinematics data and update progress bar."""
        pass

    def check_recording_completion(self) -> None:
        """Check if recording is complete and notify protocol."""
        pass

    def get_ground_truth_data(self) -> dict:
        """Return ground truth collected during this recording."""
        return {
            "ground_truth": np.array([]),
            "ground_truth_timings": np.array([]),
            "ground_truth_sampling_frequency": KINEMATICS_SAMPLING_FREQUENCY,
            "task": getattr(self, "_current_task", ""),
            "use_as_classification": True,
        }

    def enable(self) -> None:
        """Enable the per-VI UI elements."""
        pass

    def disable(self) -> None:
        """Disable the per-VI UI elements."""
        pass

    def close_event(self, _: QCloseEvent) -> None:
        """Clean up buffers on close."""
        pass


# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.2: VHI Reference -- Initialization
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# The VHI recording interface records 9 DOF of hand kinematics at 60 Hz
# and maps 10 gestures.
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#    :language: python
#    :linenos:
#    :lines: 1-64
#    :caption: Imports and Constructor

# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.3: VHI Reference -- UI Setup
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Note how per-VI controls are hidden to defer to the shared selector:
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#    :language: python
#    :lineno-match:
#    :pyobject: VirtualHandInterface_RecordingInterface.initialize_ui_logic
#    :caption: initialize_ui_logic -- Hide per-VI task combo, wire up widgets

# %%
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Step 3.4: VHI Reference -- Recording and Ground Truth
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#    :language: python
#    :lineno-match:
#    :pyobject: VirtualHandInterface_RecordingInterface.update_ground_truth_buffer
#    :caption: update_ground_truth_buffer -- Append kinematics samples
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#    :language: python
#    :lineno-match:
#    :pyobject: VirtualHandInterface_RecordingInterface.check_recording_completion
#    :caption: check_recording_completion -- Notify RecordProtocol when done
#
# .. literalinclude:: /../../myogestic/gui/widgets/visual_interfaces/virtual_hand_interface/recording_interface.py
#    :language: python
#    :lineno-match:
#    :pyobject: VirtualHandInterface_RecordingInterface.get_ground_truth_data
#    :caption: get_ground_truth_data -- Return kinematics or empty (classification)
