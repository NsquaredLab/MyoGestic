"""
=========================================
Part 2: Recording Interface
=========================================

This implementation demonstrates adding the **Recording Interface** for the Virtual Hand Interface.

Recording Interface Overview:
-----------------------------
This interface handles:
1. Start, Stop, and Task management for recording sessions.
2. Collection of EMG (biosignal) data and ground-truth kinematics data.
3. Progress tracking for buffered data during recording.
4. Saving data to persistent storage upon user approval.

Steps:
--------------
1. **Step 1:** Class Initialization and UI Setup
    - Initializes recording buffers and configures the UI layout.

2. **Step 2:** Starting & Stopping Recordings
    - Handles starting and stopping of recording sessions, including preparation and data buffering.

3. **Step 3:** Managing Recording Sessions
    - Validates setup, buffers kinematics data, and tracks recording progress.

4. **Step 4:** Completing the Recording
    - Manages task review (accept/reject recordings) and organizes persistent data-saving procedures.

5. **Step 5:** Resetting the Interface
    - Resets interface components to ensure consistency before the next recording session.
"""


# %%
# -------------------------------------------------
# Step 1: Class Initialization and UI Setup
# -------------------------------------------------
# This step initializes the recording interface’s buffers and task-related attributes.
# It also configures the UI elements required for this interface.
import time
import numpy as np
from PySide6.QtCore import SignalInstance
from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface.ui import (
    Ui_RecordingVirtualHandInterface,
)
from myogestic.gui.widgets.templates.visual_interface import RecordingInterfaceTemplate

KINEMATICS_SAMPLING_FREQUENCY = 60  # Sampling frequency for kinematics data.

class VirtualHandInterface_RecordingInterface(RecordingInterfaceTemplate):
    """
    Recording Interface for the Virtual Hand Interface.

    This class handles biosignal (EMG) and kinematics recording for tasks.
    It provides users with UI controls for recording sessions, task review, and data saving.

    Parameters
    ----------
    main_window : QMainWindow
        The parent main window for the application.
    name : str, optional
        Identifier for the recording interface, defaults to "VirtualHandInterface".
    incoming_message_signal : SignalInstance, optional
        A signal for receiving kinematics data updates.
    """

    def __init__(
        self,
        main_window,
        name="VirtualHandInterface",
        incoming_message_signal: SignalInstance = None,
    ):
        super().__init__(
            main_window,
            name,
            Ui_RecordingVirtualHandInterface(),
            incoming_message_signal=incoming_message_signal,
        )

        # Buffers for kinematics and recording status
        self._kinematics__buffer = []
        self._recording_protocol = main_window.protocols[0]
        self._start_time = 0
        self._has_finished_kinematics = False
        self._current_task = ""

        # Initialize the logic for UI components
        self.initialize_ui_logic()

    def initialize_ui_logic(self):
        """
        Set up UI controls with signals and arrange layout components.
        """
        ui = self.ui
        self._main_window.ui.recordVerticalLayout.addWidget(ui.recordRecordingGroupBox)
        self._main_window.ui.recordVerticalLayout.addWidget(
            ui.recordReviewRecordingStackedWidget
        )

        # UI components
        self.record_toggle_push_button = ui.recordRecordPushButton
        self.record_task_combo_box = ui.recordTaskComboBox
        self.record_duration_spin_box = ui.recordDurationSpinBox
        self.review_recording_stacked_widget = ui.recordReviewRecordingStackedWidget
        self.use_kinematics_check_box = ui.recordUseKinematicsCheckBox

        # Connect events to methods
        self.record_toggle_push_button.toggled.connect(self.start_recording)
        ui.reviewRecordingAcceptPushButton.clicked.connect(self.accept_recording)
        ui.reviewRecordingRejectPushButton.clicked.connect(self.reject_recording)

# %%
# -------------------------------------------------
# Step 2: Starting & Stopping Recordings
# -------------------------------------------------
# This step manages the logic for starting or stopping recording sessions,
# which includes preparing recording parameters and updating the UI.

def start_recording(self, checked: bool):
    """
    Start or stop a recording session.

    Parameters
    ----------
    checked : bool
        Indicates if the recording toggle button is active.
    """
    if checked:
        self._main_window.logger.print(
            f"Starting recording for task '{self.record_task_combo_box.currentText()}'."
        )
        self._start_recording_process()
    else:
        self._main_window.logger.print("Recording stopped by the user.")
        self.stop_recording()

def _start_recording_process(self):
    """
    Prepare for a recording session:
    - Validate the state of the device for streaming.
    - Configure parameters for data recording.
    """
    if not self._prepare_recording():
        self.record_toggle_push_button.setChecked(False)
        return

    # Start the configured recording protocol
    self._recording_protocol.start_recording_preparation(
        self.record_duration_spin_box.value()
    )
    self._start_time = time.time()
    self._current_task = self.record_task_combo_box.currentText()

    # Update UI state during recording
    self.record_toggle_push_button.setText("Recording...")
    self.ui.recordRecordingGroupBox.setEnabled(False)
    if self.use_kinematics_check_box.isChecked():
        self.incoming_message_signal.connect(self._buffer_kinematics_data)

    self._has_finished_kinematics = not self.use_kinematics_check_box.isChecked()

# %%
# -------------------------------------------------
# Step 3: Managing Recording Sessions
# -------------------------------------------------
# This step monitors kinematics and biosignal (EMG) recordings. It buffers incoming data,
# validates progress, and dynamically updates relevant UI elements like progress bars.

def _prepare_recording(self) -> bool:
    """
    Validates and prepares the recording setup.

    Returns
    -------
    bool
        True if preparation is successful, otherwise False.
    """
    device_widget = self._main_window.device__widget._get_current_widget()
    if not device_widget._device._is_streaming:
        self._main_window.logger.print(
            "Biosignal device not streaming!", level=LoggerLevel.ERROR
        )
        return False

    self._kinematics__buffer = []
    return True

def _buffer_kinematics_data(self, data: np.ndarray):
    """
    Buffer incoming kinematics data and update the progress bar.

    Parameters
    ----------
    data : np.ndarray
        Data received from the kinematics signal.
    """
    self._kinematics__buffer.append((time.time(), data))

    # Update progress bar
    current_samples = len(self._kinematics__buffer)
    self._set_progress_bar(
        self.ui.recordGroundTruthProgressBar,
        current_samples,
        int(self.record_duration_spin_box.value() * KINEMATICS_SAMPLING_FREQUENCY),
    )

    if current_samples >= int(
        self.record_duration_spin_box.value() * KINEMATICS_SAMPLING_FREQUENCY
    ):
        self._main_window.logger.print("Kinematics recording completed.")
        self._has_finished_kinematics = True
        self.incoming_message_signal.disconnect(self._buffer_kinematics_data)
        self._check_recording_completion()

def _check_recording_completion(self):
    """
    Check if both biosignal and kinematics recordings are complete.
    """
    if (
        self._recording_protocol.is_biosignal_recording_complete
        and self._has_finished_kinematics
    ):
        self.finish_recording()

# %%
# -------------------------------------------------
# Step 4: Completing the Recording
# -------------------------------------------------
# This step manages task review. Users can accept or reject recordings. Accepted recordings
# are saved to persistent storage with relevant metadata (e.g., task name, timings).

def finish_recording(self):
    """
    Transition the interface to the review state upon completion.
    """
    self.review_recording_stacked_widget.setCurrentIndex(
        1
    )  # Switch to review interface.
    self.ui.reviewRecordingTaskLabel.setText(self._current_task.capitalize())

def accept_recording(self):
    """
    Save the recording to persistent storage after user approval.
    """
    label = self.ui.reviewRecordingLabelLineEdit.text() or "default"
    biosignal_data, biosignal_timings = (
        self._recording_protocol.retrieve_recorded_data()
    )

    # Save kinematics and biosignal data along with session metadata
    self.save_recording(
        biosignal=biosignal_data,
        biosignal_timings=biosignal_timings,
        ground_truth=(
            np.vstack([d for _, d in self._kinematics__buffer]).T
            if self.use_kinematics_check_box.isChecked()
            else np.array([])
        ),
        ground_truth_timings=(
            np.array([t for t, _ in self._kinematics__buffer])
            if self.use_kinematics_check_box.isChecked()
            else np.array([])
        ),
        recording_label=label,
        task=self._current_task,
        ground_truth_sampling_frequency=KINEMATICS_SAMPLING_FREQUENCY,
        use_as_classification=not self.use_kinematics_check_box.isChecked(),
        record_duration=self.record_duration_spin_box.value(),
    )

    self._main_window.logger.print(f"Recording '{label}' accepted!")
    self.reset_ui()

def reject_recording(self):
    """
    Reject the recording and reset the UI for the next session.
    """
    self._main_window.logger.print("Recording rejected by the user.")
    self.reset_ui()

# %%
# -------------------------------------------------
# Step 5: Resetting the Interface
# -------------------------------------------------
# Reset all UI components, buffers, and flags to their default states to prepare
# the system for the next recording session.

def reset_ui(self):
    """
    Reset all UI elements and buffers to their default states.
    """
    self.ui.recordRecordingGroupBox.setEnabled(True)
    self.ui.reviewRecordingTaskLabel.clear()
    self.ui.reviewRecordingLabelLineEdit.clear()
    self.record_toggle_push_button.setText("Start Recording")
    self.record_toggle_push_button.setChecked(False)
    self._kinematics__buffer.clear()
