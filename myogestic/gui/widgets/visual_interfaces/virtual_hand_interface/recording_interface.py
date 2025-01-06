import pickle
import time
from datetime import datetime

import numpy as np
from PySide6.QtCore import SignalInstance

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.visual_interface import RecordingUITemplate
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface import (
    Ui_RecordingVirtualHandInterface,
)
from myogestic.utils.constants import RECORDING_DIR_PATH


class VirtualHandInterfaceRecordingUI(RecordingUITemplate):
    def __init__(self, parent, name="VirtualHandInterface", incoming_message_signal: SignalInstance = None) -> None:
        super().__init__(
            parent, name, ui=Ui_RecordingVirtualHandInterface(), incoming_message_signal=incoming_message_signal
        )

        RECORDING_DIR_PATH.mkdir(parents=True, exist_ok=True)

        self.current_task = None
        self.kinematics_sampling_frequency = 60
        self.emg_buffer = []
        self.kinematics_buffer = []

        self.has_finished_emg = False
        self.has_finished_kinematics = False
        self.start_time = None

        self.initialize_ui_logic()

    def initialize_ui_logic(self) -> None:
        ui = self.ui

        self.main_window.ui.recordVerticalLayout.addWidget(ui.recordRecordingGroupBox)
        self.main_window.ui.recordVerticalLayout.addWidget(ui.recordReviewRecordingStackedWidget)

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

        self.record_toggle_push_button.toggled.connect(self._start_recording)
        self.review_recording_accept_push_button.clicked.connect(self._accept_recording)
        self.review_recording_reject_push_button.clicked.connect(self._reject_recording)

        self.record_ground_truth_progress_bar.setValue(0)
        self.review_recording_stacked_widget.setCurrentIndex(0)

    def _start_recording(self, checked: bool) -> None:
        if checked:
            if not self._prepare_recording():
                self.record_toggle_push_button.setChecked(False)
                return

            self.start_time = time.time()
            self.biosignal_buffer = []
            self.emg_recording_time = int(self.record_duration_spin_box.value() * self.main_window.sampling_frequency)

            self.record_toggle_push_button.setText("Recording...")
            self.record_group_box.setEnabled(False)
            self.current_task = self.record_task_combo_box.currentText()

            self.main_window.device_widget.biosignal_data_arrived.connect(self.emg_update)
            if self.use_kinematics_check_box.isChecked():
                self.incoming_message_signal.connect(self.ground_truth_buffer_update)

            self.has_finished_emg = False
            self.has_finished_kinematics = not self.use_kinematics_check_box.isChecked()

    def _prepare_recording(self) -> bool:
        if self.use_kinematics_check_box.isChecked() and not self.main_window.virtual_hand_interface.is_connected:
            self.main_window.logger.print("Virtual Hand Interface not connected!", level=LoggerLevel.ERROR)
            return False

        if not self.main_window.device_widget._get_current_widget().device._is_streaming:
            self.main_window.logger.print("Biosignal device not streaming!", level=LoggerLevel.ERROR)
            return False

        self.kinematics_recording_time = int(self.record_duration_spin_box.value() * self.kinematics_sampling_frequency)
        self.kinematics_buffer = []
        return True

    def emg_update(self, data: np.ndarray) -> None:
        self.emg_buffer.append((time.time(), data))
        current_samples = len(self.emg_buffer) * self.emg_buffer[0][1].shape[1]
        self._set_progress_bar(self.record_emg_progress_bar, current_samples, self.emg_recording_time)

        if current_samples >= self.emg_recording_time:
            self.main_window.logger.print(f"EMG recording finished at: {round(time.time() - self.start_time)} seconds")
            self.has_finished_emg = True
            self.main_window.device_widget.biosignal_data_arrived.disconnect(self.emg_update)
            self._check_recording_completion()

    def ground_truth_buffer_update(self, data: np.ndarray) -> None:
        if not self.use_kinematics_check_box.isChecked():
            return

        self.kinematics_buffer.append((time.time(), data))
        current_samples = len(self.kinematics_buffer)
        self._set_progress_bar(self.record_ground_truth_progress_bar, current_samples, self.kinematics_recording_time)

        if current_samples >= self.kinematics_recording_time:
            self.main_window.logger.print(
                f"Kinematics recording finished at: {round(time.time() - self.start_time)} seconds"
            )
            self.has_finished_kinematics = True
            self.incoming_message_signal.disconnect(self.ground_truth_buffer_update)
            self._check_recording_completion()


    def _check_recording_completion(self) -> None:
        if self.has_finished_emg and self.has_finished_kinematics:
            self.finished_recording()

    def finished_recording(self) -> None:
        self.review_recording_stacked_widget.setCurrentIndex(1)
        self.record_toggle_push_button.setText("Finished Recording")
        self.review_recording_task_label.setText(self.current_task.capitalize())

    def _accept_recording(self) -> None:
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
        - sampling_frequency: The EMG sampling frequency.
        - kinematics_sampling_frequency: The kinematics sampling frequency.
        - recording_time: The recording duration in seconds.
        - use_kinematics: Boolean indicating whether kinematics data was recorded.
        """
        label = self.review_recording_label_line_edit.text() or "default"
        emg_signal = np.hstack([data for _, data in self.biosignal_buffer])[:, : self.emg_recording_time]

        save_pickle_dict = {
            "emg": emg_signal,
            "kinematics": np.vstack([data for _, data in self.kinematics_buffer]).T
            if self.use_kinematics_check_box.isChecked()
            else np.array([]),
            "timings_emg": np.array([time_stamp for time_stamp, _ in self.biosignal_buffer]),
            "timings_kinematics": np.array([time_stamp for time_stamp, _ in self.kinematics_buffer])
            if self.use_kinematics_check_box.isChecked()
            else np.array([]),
            "label": label,
            "task": self.current_task,
            "device": self.main_window.device_name,
            "bad_channels": self.main_window.current_bad_channels,
            "sampling_frequency": self.main_window.sampling_frequency,
            "kinematics_sampling_frequency": self.kinematics_sampling_frequency,
            "recording_time": self.record_duration_spin_box.value(),
            "use_kinematics": self.use_kinematics_check_box.isChecked(),
        }

        file_name = f"MindMove_Recording_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{self.current_task.lower()}_{label.lower()}.pkl"
        with (RECORDING_DIR_PATH / file_name).open("wb") as f:
            pickle.dump(save_pickle_dict, f)

        self._reset_ui()
        self.main_window.logger.print(f"Recording of task {self.current_task.lower()} with label {label} accepted!")

    def _reject_recording(self) -> None:
        self._reset_ui()
        self.main_window.logger.print("Recording rejected.")

    def _reset_ui(self) -> None:
        self.review_recording_stacked_widget.setCurrentIndex(0)
        self.record_toggle_push_button.setText("Start Recording")
        self.record_toggle_push_button.setChecked(False)
        self.record_group_box.setEnabled(True)

        self.record_emg_progress_bar.setValue(0)
        self.record_ground_truth_progress_bar.setValue(0)

        self.emg_buffer.clear()
        self.kinematics_buffer.clear()

    def close_event(self) -> None:
        self.record_toggle_push_button.setChecked(False)
        self._reset_ui()
        self.main_window.device_widget.biosignal_data_arrived.disconnect(self.emg_update)
        self.incoming_message_signal.disconnect(self.ground_truth_buffer_update)
        self.main_window.logger.print("Recording interface closed.")

    def enable(self):
        """Enable the UI elements."""
        self.ui.recordRecordingGroupBox.setEnabled(True)
        self.ui.recordReviewRecordingStackedWidget.setEnabled(True)

    def disable(self):
        """Disable the UI elements."""
        self.ui.recordRecordingGroupBox.setEnabled(False)
        self.ui.recordReviewRecordingStackedWidget.setEnabled(False)
