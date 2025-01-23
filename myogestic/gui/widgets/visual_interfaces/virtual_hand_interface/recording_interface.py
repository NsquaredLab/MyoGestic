import pickle
import time
from datetime import datetime

import numpy as np
from PySide6.QtCore import SignalInstance
from PySide6.QtGui import QCloseEvent

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.visual_interface import RecordingInterfaceTemplate
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface import (
    Ui_RecordingVirtualHandInterface,
)
from myogestic.utils.constants import RECORDING_DIR_PATH

KINEMATICS_SAMPLING_FREQUENCY = 60


class VirtualHandInterface_RecordingInterface(RecordingInterfaceTemplate):
    def __init__(
        self,
        parent,
        name: str = "VirtualHandInterface",
        incoming_message_signal: SignalInstance = None,
    ) -> None:
        super().__init__(
            parent,
            name,
            ui=Ui_RecordingVirtualHandInterface(),
            incoming_message_signal=incoming_message_signal,
        )

        RECORDING_DIR_PATH.mkdir(parents=True, exist_ok=True)

        self.current_task = None
        self.kinematics_buffer = []

        self.recording_protocol = self.main_window.protocol.available_protocols[0]

        self.has_finished_kinematics = False
        self.start_time = None

        self.initialize_ui_logic()

    def initialize_ui_logic(self) -> None:
        ui: Ui_RecordingVirtualHandInterface = self.ui

        self.main_window.ui.recordVerticalLayout.addWidget(ui.recordRecordingGroupBox)
        self.main_window.ui.recordVerticalLayout.addWidget(
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
        if checked:
            if not self.start_recording_preparation():
                self.record_toggle_push_button.setChecked(False)
                return

            if not self.recording_protocol.start_recording_preparation(
                self.record_duration_spin_box.value()
            ):
                self.record_toggle_push_button.setChecked(False)
                return

            self.start_time = time.time()

            self.record_toggle_push_button.setText("Recording...")
            self.record_group_box.setEnabled(False)
            self.current_task = self.record_task_combo_box.currentText()

            if self.use_kinematics_check_box.isChecked():
                self.incoming_message_signal.connect(self.update_ground_truth_buffer)

            self.has_finished_kinematics = not self.use_kinematics_check_box.isChecked()

    def start_recording_preparation(self) -> bool:
        # if (
        #     self.use_kinematics_check_box.isChecked()
        #     and not self.main_window.virtual_hand_interface.is_connected
        # ):
        #     self.main_window.logger.print(
        #         "Virtual Hand Interface not connected!", level=LoggerLevel.ERROR
        #     )
        #     return False

        if (
            not self.main_window.device_widget._get_current_widget()._device._is_streaming
        ):
            self.main_window.logger.print(
                "Biosignal device not streaming!", level=LoggerLevel.ERROR
            )
            return False

        self.kinematics_recording_time = int(
            self.record_duration_spin_box.value() * KINEMATICS_SAMPLING_FREQUENCY
        )
        self.kinematics_buffer = []
        return True

    def update_ground_truth_buffer(self, data: np.ndarray) -> None:
        if not self.use_kinematics_check_box.isChecked():
            return

        self.kinematics_buffer.append((time.time(), data))
        current_samples = len(self.kinematics_buffer)
        self._set_progress_bar(
            self.record_ground_truth_progress_bar,
            current_samples,
            self.kinematics_recording_time,
        )

        if current_samples >= self.kinematics_recording_time:
            self.main_window.logger.print(
                f"Kinematics recording finished at: {round(time.time() - self.start_time)} seconds"
            )
            self.has_finished_kinematics = True
            self.incoming_message_signal.disconnect(self.update_ground_truth_buffer)
            self.check_recording_completion()

    def check_recording_completion(self) -> None:
        if (
            self.recording_protocol.is_biosignal_recording_complete
            and self.has_finished_kinematics
        ):
            self.finish_recording()

    def finish_recording(self) -> None:
        self.review_recording_stacked_widget.setCurrentIndex(1)
        self.record_toggle_push_button.setText("Finished Recording")
        self.review_recording_task_label.setText(self.current_task.capitalize())

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
        - sampling_frequency: The EMG sampling frequency.
        - kinematics_sampling_frequency: The kinematics sampling frequency.
        - recording_time: The recording duration in seconds.
        - use_kinematics: Boolean indicating whether kinematics data was recorded.
        """
        label = self.review_recording_label_line_edit.text() or "default"
        biosignal_signal, biosignal_timings = (
            self.recording_protocol.retrieve_recorded_data()
        )

        save_pickle_dict = {
            "emg": biosignal_signal,
            "kinematics": (
                np.vstack([data for _, data in self.kinematics_buffer]).T
                if self.use_kinematics_check_box.isChecked()
                else np.array([])
            ),
            "timings_emg": biosignal_timings,
            "timings_kinematics": (
                np.array([time_stamp for time_stamp, _ in self.kinematics_buffer])
                if self.use_kinematics_check_box.isChecked()
                else np.array([])
            ),
            "label": label,
            "task": self.current_task,
            "device": self.main_window.device_name,
            "bad_channels": self.main_window.current_bad_channels,
            "sampling_frequency": self.main_window.sampling_frequency,
            "kinematics_sampling_frequency": KINEMATICS_SAMPLING_FREQUENCY,
            "recording_time": self.record_duration_spin_box.value(),
            "use_kinematics": self.use_kinematics_check_box.isChecked(),
        }

        file_name = f"MindMove_Recording_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{self.current_task.lower()}_{label.lower()}.pkl"
        with (RECORDING_DIR_PATH / file_name).open("wb") as f:
            pickle.dump(save_pickle_dict, f)

        self.reset_ui()
        self.main_window.logger.print(
            f"Recording of task {self.current_task.lower()} with label {label} accepted!"
        )

    def reject_recording(self) -> None:
        self.reset_ui()
        self.main_window.logger.print("Recording rejected.")

    def reset_ui(self) -> None:
        self.review_recording_stacked_widget.setCurrentIndex(0)
        self.record_toggle_push_button.setText("Start Recording")
        self.record_toggle_push_button.setChecked(False)
        self.record_group_box.setEnabled(True)

        self.recording_protocol._reset_recording_ui()

        self.record_ground_truth_progress_bar.setValue(0)
        self.kinematics_buffer.clear()

    def closeEvent(self, _: QCloseEvent) -> None:
        self.record_toggle_push_button.setChecked(False)
        self.reset_ui()
        self.recording_protocol.closeEvent(_)
        self.main_window.logger.print("Recording interface closed.")

    def enable(self):
        """Enable the UI elements."""
        self.ui.recordRecordingGroupBox.setEnabled(True)
        self.ui.recordReviewRecordingStackedWidget.setEnabled(True)

    def disable(self):
        """Disable the UI elements."""
        self.ui.recordRecordingGroupBox.setEnabled(False)
        self.ui.recordReviewRecordingStackedWidget.setEnabled(False)
