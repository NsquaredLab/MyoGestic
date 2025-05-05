import time

import numpy as np
from PySide6.QtCore import SignalInstance
from PySide6.QtGui import QCloseEvent

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.visual_interface import RecordingInterfaceTemplate
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface.ui import (
    Ui_RecordingVirtualHandInterface,
)
from myogestic.utils.constants import RECORDING_DIR_PATH

KINEMATICS_SAMPLING_FREQUENCY = 60


class VirtualHandInterface_RecordingInterface(RecordingInterfaceTemplate):
    """
    Class for the recording interface of the Virtual Hand Interface.

    This class is responsible for handling the recording of EMG and kinematics data.

    Parameters
    ----------
    main_window : MainWindow
        The main window of the application.
    name : str
        The name of the interface, by default "VirtualHandInterface".

        .. important:: This name is used to identify the interface in the main window. It should be unique.
    incoming_message_signal : SignalInstance
        The signal instance used to receive incoming messages from the device.
    """

    ground_truth__task_map: dict[str, int] = {
        "rest": 0,
        "index": 1,
        "thumb": 2,
        "middle": 3,
        "ring": 4,
        "pinky": 5,
        "power grasp": 6,
        "pinch": 7,
        "tripod pinch": 8,
        "pointing": 9,
    }
    ground_truth__nr_of_recording_values: int = 9

    def __init__(
        self,
        main_window,
        name: str = "VirtualHandInterface",
        incoming_message_signal: SignalInstance = None,
    ) -> None:
        super().__init__(
            main_window,
            name,
            ui=Ui_RecordingVirtualHandInterface(),
            incoming_message_signal=incoming_message_signal,
            ground_truth__nr_of_recording_values=self.ground_truth__nr_of_recording_values,
            ground_truth__task_map=self.ground_truth__task_map
        )

        RECORDING_DIR_PATH.mkdir(parents=True, exist_ok=True)

        self._current_task: str = ""
        self._kinematics__buffer = []

        self._recording_protocol = self._main_window.protocols[0]

        self._has_finished_kinematics: bool = False
        self._start_time: float = 0

        self.initialize_ui_logic()

    def initialize_ui_logic(self) -> None:
        """Initializes the logic for the UI elements."""
        ui: Ui_RecordingVirtualHandInterface = self.ui

        self._main_window.ui.recordVerticalLayout.addWidget(ui.recordRecordingGroupBox)
        self._main_window.ui.recordVerticalLayout.addWidget(
            ui.recordReviewRecordingStackedWidget
        )

        self.record_group_box = ui.recordRecordingGroupBox
        self.record_task_combo_box = ui.recordTaskComboBox
        self.record_duration_spin_box = ui.recordDurationSpinBox
        self.record_toggle_push_button = ui.recordRecordPushButton

        self.review_recording_stacked_widget = ui.recordReviewRecordingStackedWidget
        self.review_recording_task_label = ui.reviewRecordingTaskLabel
        self.review_recording_label_line_edit = ui.reviewRecordingLabelLineEdit

        self.review_recording_accept_push_button = ui.reviewRecordingAcceptPushButton
        self.review_recording_reject_push_button = ui.reviewRecordingRejectPushButton

        self.use_kinematics_check_box = ui.recordUseKinematicsCheckBox

        self.record_toggle_push_button.toggled.connect(self.start_recording)
        self.review_recording_accept_push_button.clicked.connect(self.accept_recording)
        self.review_recording_reject_push_button.clicked.connect(self.reject_recording)

        self.record_ground_truth_progress_bar.setValue(0)
        self.review_recording_stacked_widget.setCurrentIndex(0)

    def start_recording(self, checked: bool) -> None:
        """Starts the recording process."""
        if checked:
            if not self.start_recording_preparation():
                self.record_toggle_push_button.setChecked(False)
                return

            if not self._recording_protocol.start_recording_preparation(
                self.record_duration_spin_box.value()
            ):
                self.record_toggle_push_button.setChecked(False)
                return

            self._start_time = time.time()

            self.record_toggle_push_button.setText("Recording...")
            self.record_group_box.setEnabled(False)
            self._current_task = self.record_task_combo_box.currentText()

            if self.use_kinematics_check_box.isChecked():
                self.incoming_message_signal.connect(self.update_ground_truth_buffer)

            self._has_finished_kinematics = (
                not self.use_kinematics_check_box.isChecked()
            )

    def start_recording_preparation(self) -> bool:
        """Prepares the recording process by checking if the device is streaming."""
        if (
            not self._main_window.device__widget._get_current_widget()._device._is_streaming
        ):
            self._main_window.logger.print(
                "Biosignal device not streaming!", level=LoggerLevel.ERROR
            )
            return False

        self.kinematics_recording_time = int(
            self.record_duration_spin_box.value() * KINEMATICS_SAMPLING_FREQUENCY
        )
        self._kinematics__buffer = []
        return True

    def update_ground_truth_buffer(self, data: np.ndarray) -> None:
        """Updates the buffer with the incoming kinematics data."""
        if not self.use_kinematics_check_box.isChecked():
            return

        self._kinematics__buffer.append((time.time(), data))
        current_samples = len(self._kinematics__buffer)
        self._set_progress_bar(
            self.record_ground_truth_progress_bar,
            current_samples,
            self.kinematics_recording_time,
        )

        if current_samples >= self.kinematics_recording_time:
            self._main_window.logger.print(
                f"Kinematics recording finished at: {round(time.time() - self._start_time)} seconds"
            )
            self._has_finished_kinematics = True
            self.incoming_message_signal.disconnect(self.update_ground_truth_buffer)
            self.check_recording_completion()

    def check_recording_completion(self) -> None:
        """Checks if the recording process is complete and finishes it if so."""
        if (
            self._recording_protocol.is_biosignal_recording_complete
            and self._has_finished_kinematics
        ):
            self.finish_recording()

    def finish_recording(self) -> None:
        """Finishes the recording process and switches to the review recording interface."""
        self.review_recording_stacked_widget.setCurrentIndex(1)
        self.record_toggle_push_button.setText("Finished Recording")
        self.review_recording_task_label.setText(self._current_task.capitalize())

    def accept_recording(self) -> None:
        """
        Accepts the current recording and saves the data to a pickle file.

        The saved data is a dictionary containing:

        - emg: A 2D NumPy array of EMG signals with time samples as rows and channels as columns.
        - kinematics: A 2D NumPy array of kinematics data (empty if not used).
        - timings_emg: A 1D NumPy array of timestamps for EMG samples.
        - timings_kinematics: A 1D NumPy array of timestamps for kinematics samples (empty if not used).
        - label: The user-provided label for the recording.
        - task: The task being recorded.
        - device: The name of the device used for recording.
        - bad_channels: A list of channels marked as "bad."
        - _sampling_frequency: The EMG sampling frequency.
        - kinematics_sampling_frequency: The kinematics sampling frequency.
        - recording_time: The recording duration in seconds.
        - use_kinematics: Boolean indicating whether kinematics data was recorded.
        """
        label = self.review_recording_label_line_edit.text() or "default"
        (
            biosignal_data,
            biosignal_timings,
        ) = self._recording_protocol.retrieve_recorded_data()

        self.save_recording(
            biosignal=biosignal_data,
            biosignal_timings=biosignal_timings,
            ground_truth=(
                np.vstack([data for _, data in self._kinematics__buffer]).T
                if self.use_kinematics_check_box.isChecked()
                else np.array([])
            ),
            ground_truth_timings=(
                np.array([time_stamp for time_stamp, _ in self._kinematics__buffer])
                if self.use_kinematics_check_box.isChecked()
                else np.array([])
            ),
            recording_label=label,
            task=self._current_task,
            ground_truth_sampling_frequency=KINEMATICS_SAMPLING_FREQUENCY,
            use_as_classification=not self.use_kinematics_check_box.isChecked(),
            record_duration=self.record_duration_spin_box.value(),
        )

        self.reset_ui()
        self._main_window.logger.print(
            f"Recording of task {self._current_task.lower()} with label {label} accepted!"
        )

    def reject_recording(self) -> None:
        """Rejects the current recording and resets the recording interface."""
        self.reset_ui()
        self._main_window.logger.print("Recording rejected.")

    def reset_ui(self) -> None:
        """Resets the recording interface UI elements."""
        self.review_recording_stacked_widget.setCurrentIndex(0)
        self.record_toggle_push_button.setText("Start Recording")
        self.record_toggle_push_button.setChecked(False)
        self.record_group_box.setEnabled(True)

        self._recording_protocol._reset_recording_ui()

        self.record_ground_truth_progress_bar.setValue(0)
        self._kinematics__buffer.clear()

    def close_event(self, _: QCloseEvent) -> None:
        """Closes the recording interface."""
        self.record_toggle_push_button.setChecked(False)
        self.reset_ui()
        self._recording_protocol.close_event(_)
        self._main_window.logger.print("Recording interface closed.")

    def enable(self):
        """Enable the UI elements."""
        self.ui.recordRecordingGroupBox.setEnabled(True)
        self.ui.recordReviewRecordingStackedWidget.setEnabled(True)

    def disable(self):
        """Disable the UI elements."""
        self.ui.recordRecordingGroupBox.setEnabled(False)
        self.ui.recordReviewRecordingStackedWidget.setEnabled(False)
