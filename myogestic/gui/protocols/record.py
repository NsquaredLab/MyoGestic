from __future__ import annotations

import os
import pickle
import time
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject
from myogestic.gui.widgets.logger import LoggerLevel

if TYPE_CHECKING:
    from myogestic.gui.myogestic import MyoGestic


class RecordProtocol(QObject):
    """Protocol for recording EMG and kinematics data.

    This protocol allows the user to record EMG and kinematics data for a specified duration.
    The user can select the task to be recorded and provide a label for the recording.

    The protocol includes the following features:
        - Recording EMG data from the biosignal device.
        - Recording kinematics data from the virtual hand interface.
        - Setting the recording duration in seconds.
        - Selecting the task to be recorded.
        - Providing a label for the recording.
        - Saving the recorded data to a file.

    Parameters
    ----------
    parent : MyoGestic, optional
        The parent object that manages the protocol, by default None.

    Attributes
    ----------
    main_window : MyoGestic
        The main window object that manages the protocol.
    current_task : str
        The current task selected for recording.
    kinematics_sampling_frequency : int
        The sampling frequency for kinematics data.
    recording_time : int
        The duration of the recording in seconds.
    emg_buffer : list[(int, np.ndarray)]
        A list of tuples containing the timestamp and EMG data samples.
    kinematics_buffer : list[(int, np.ndarray)]
        A list of tuples containing the timestamp and kinematics data samples.
    has_finished_emg : bool
        A flag indicating whether the EMG recording has finished.
    has_finished_kinematics : bool
        A flag indicating whether the kinematics recording has finished.
    start_time : float
        The start time of the recording.
    recording_dir_path : str
        The directory path for saving the recordings.
    emg_recording_time : int
        The total number of EMG samples to be recorded.
    """

    def __init__(self, parent: MyoGestic | None = ...) -> None:
        super().__init__(parent)

        self.main_window = parent

        # Initialize Protocol UI
        self._setup_protocol_ui()

        # Initialize Protocol
        self.current_task: str = None
        self.kinematics_sampling_frequency: int = 60
        self.recording_time: int = self.record_duration_spin_box.value()

        self.emg_buffer: list[(int, np.ndarray)] = []
        self.kinematics_buffer: list[(int, np.ndarray)] = []

        self.has_finished_emg: bool = False
        self.has_finished_kinematics: bool = False

        self.start_time: float = None

        # File management:
        self.recording_dir_path: str = os.path.join(
            self.main_window.base_path, "recordings"
        )

        if not os.path.exists(self.recording_dir_path):
            os.makedirs(self.recording_dir_path)

    def emg_update(self, data: np.ndarray) -> None:
        """
        Updates the EMG (electromyography) data buffer with new data and checks if the recording is complete.

        Parameters
        ----------
        data : np.ndarray
            The new EMG data to be added to the buffer.

        Notes
        -----
        This method performs the following steps:

        1. Extracts the EMG signal from the provided data using the `extract_emg_data` method of the `device_widget`.
        2. Appends the current timestamp and the extracted EMG signal to the `emg_buffer`.
        3. Calculates the total number of current samples in the buffer.
        4. Updates the EMG progress bar with the current number of samples.
        5. Checks if the number of current samples has reached or exceeded the required recording time.

           - If the recording is complete, it logs a message indicating the completion time.
           - Sets the `has_finished_emg` flag to True.
           - Disconnects the `emg_update` method from the `ready_read_signal` of the `device_widget`.
           - Calls the `finished_recording` method to handle post-recording actions.
        """

        self.emg_buffer.append((time.time(), data))

        current_samples = len(self.emg_buffer) * self.emg_buffer[0][1].shape[1]
        self._set_emg_progress_bar(current_samples)

        if current_samples >= self.emg_recording_time:
            self.main_window.logger.print(
                f"EMG recording finished at: {round(time.time() - self.start_time)}"
            )
            self.has_finished_emg = True
            self.main_window.device_widget.biosignal_data_arrived.disconnect(
                self.emg_update
            )
            self.finished_recording()

    def kinematics_update(self, data: np.ndarray) -> None:
        """
        Updates the kinematics data buffer with new data and checks if the recording is complete.

        Parameters
        ----------
        data : np.ndarray
            The new kinematics data to be added to the buffer.

        Notes
        -----
        This method performs the following steps:

        1. Checks if the kinematics recording is enabled using the `use_kinematics_check_box`.
        2. Appends the current timestamp and the kinematics data to the `kinematics_buffer`.
        3. Calculates the total number of current samples in the buffer.
        4. Updates the kinematics progress bar with the current number of samples.
        5. Checks if the number of current samples has reached or exceeded the required recording time.

           - If the recording is complete, it logs a message indicating the completion time.
           - Sets the `has_finished_kinematics` flag to True.
           - Disconnects the `kinematics_update` method from the `input_message_signal` of the `virtual_hand_interface`.
           - Calls the `finished_recording` method to handle post-recording actions.
        """
        if self.use_kinematics_check_box.isChecked():
            self.kinematics_buffer.append((time.time(), data))

            current_samples = len(self.kinematics_buffer)
            self._set_kinematics_progress_bar(current_samples)

            if current_samples >= self.kinematics_recording_time:
                self.main_window.logger.print(
                    f"Kinematics recording finished at: {round(time.time() - self.start_time)}"
                )
                self.has_finished_kinematics = True
                self.main_window.virtual_hand_interface.input_message_signal.disconnect(
                    self.kinematics_update
                )
                self.finished_recording()

    def _start_recording(self, checked: bool) -> None:
        """
        Starts or stops the recording process based on the checked state of the record toggle push button.

        Parameters
        ----------
        checked
            The checked state of the record toggle push button.

        Returns
        -------
        None
        """

        if checked:
            # Check for Kinematics
            if self.use_kinematics_check_box.isChecked():
                if not self.main_window.virtual_hand_interface.is_connected:
                    self.main_window.logger.print(
                        "Virtual Hand Interface not connected!", level=LoggerLevel.ERROR
                    )
                    self.record_toggle_push_button.setChecked(False)
                    return

                self.main_window.virtual_hand_interface.input_message_signal.connect(
                    self.kinematics_update
                )

                self.kinematics_buffer = []
                self.kinematics_recording_time: int = int(
                    self.recording_time * self.kinematics_sampling_frequency
                )

                self.has_finished_kinematics = False

            if (
                not self.main_window.device_widget._get_current_widget().device._is_streaming
            ):
                self.main_window.logger.print(
                    "Biosignal device not streaming!", level=LoggerLevel.ERROR
                )
                self.record_toggle_push_button.setChecked(False)
                return

            self.main_window.device_widget.biosignal_data_arrived.connect(
                self.emg_update
            )

            self.start_time = time.time()

            # Reset buffers
            self.emg_buffer = []

            # Set duration time
            self.recording_time: int = self.record_duration_spin_box.value()
            self.emg_recording_time: int = int(
                self.recording_time * self.main_window.sampling_frequency
            )

            self.record_toggle_push_button.setText("Recording...")
            self.record_group_box.setEnabled(False)
            self.current_task: str = self.record_task_combo_box.currentText()

            self.has_finished_emg = False

    def _set_emg_progress_bar(self, value: int) -> None:
        """
        Sets the value of the EMG progress bar based on the current number of samples.

        Parameters
        ----------
        value : int
            The current number of samples in the EMG buffer.

        Returns
        -------
        None
        """
        self.record_emg_progress_bar.setValue(value / self.emg_recording_time * 100)

    def _set_kinematics_progress_bar(self, value: int) -> None:
        """
        Sets the value of the kinematics progress bar based on the current number of samples.

        Parameters
        ----------
        value : int
            The current number of samples in the kinematics buffer.

        Returns
        -------
        None
        """

        self.record_kinematics_progress_bar.setValue(
            value / self.kinematics_recording_time * 100
        )

    def finished_recording(self) -> None:
        """
        Handles the post-recording actions after the EMG and kinematics recordings are complete.

        Returns
        -------
        None
        """

        if self.use_kinematics_check_box.isChecked():
            if not self.has_finished_kinematics:
                return

        if not self.has_finished_emg:
            return

        self.review_recording_stacked_widget.setCurrentIndex(1)
        self.record_toggle_push_button.setText("Finished Recording")
        self.review_recording_task_label.setText(self.current_task.capitalize())

        self.has_finished_emg = False

        if self.use_kinematics_check_box.isChecked():
            self.has_finished_kinematics = False

    def _accept_recording(self) -> None:
        """
        Accepts the recording and saves the recorded data to a file.

        Returns
        -------
        None
        """

        self.review_recording_stacked_widget.setCurrentIndex(0)
        self.record_toggle_push_button.setText("Start Recording")
        self.record_toggle_push_button.setChecked(False)
        self.record_group_box.setEnabled(True)

        # Save Recordings
        label = self.review_recording_label_line_edit.text()
        if not label:
            label = "default"

        emg_signal = np.hstack([data for _, data in self.emg_buffer])[
            :, : self.emg_recording_time
        ]

        save_pickle_dict = {
            "emg": emg_signal,
            "kinematics": (
                np.vstack([data for _, data in self.kinematics_buffer]).T
                if self.use_kinematics_check_box.isChecked()
                else np.array([])
            ),
            "timings_emg": np.array([time_stamp for time_stamp, _ in self.emg_buffer]),
            "timings_kinematics": np.array(
                [time_stamp for time_stamp, _ in self.kinematics_buffer]
                if self.use_kinematics_check_box.isChecked()
                else np.array([])
            ),
            "label": label,
            "task": self.current_task,
            "device": self.main_window.device_name,
            "bad_channels": self.main_window.current_bad_channels,
            "sampling_frequency": self.main_window.sampling_frequency,
            "kinematics_sampling_frequency": self.kinematics_sampling_frequency,
            "recording_time": self.recording_time,
            "use_kinematics": self.use_kinematics_check_box.isChecked(),
        }

        now = datetime.now()
        formatted_now = now.strftime("%Y%m%d_%H%M%S%f")
        file_name = f"MindMove_Recording_{formatted_now}_{self.current_task.lower()}_{label.lower()}.pkl"

        with open(os.path.join(self.recording_dir_path, file_name), "wb") as f:
            pickle.dump(save_pickle_dict, f)

        # Reset progress bars
        self.record_emg_progress_bar.setValue(0)
        self.record_kinematics_progress_bar.setValue(0)

        # Reset buffers
        self.emg_buffer = []
        self.kinematics_buffer = []

        self.main_window.logger.print(
            f"Recording of task {self.current_task.lower()} with label {label} accepted!"
        )

    def _reject_recording(self) -> None:
        """
        Rejects the recording and resets the recording UI.

        Returns
        -------
        None
        """

        self.review_recording_stacked_widget.setCurrentIndex(0)
        self.record_toggle_push_button.setText("Start Recording")
        self.record_toggle_push_button.setChecked(False)
        self.record_group_box.setEnabled(True)

        # Reset progress bars
        self.record_emg_progress_bar.setValue(0)
        self.record_kinematics_progress_bar.setValue(0)

    def _setup_protocol_ui(self) -> None:
        """
        Sets up the user interface elements for the record protocol.

        Returns
        -------
        None
        """

        # Record UI
        self.record_group_box = self.main_window.ui.recordRecordingGroupBox
        self.record_task_combo_box = self.main_window.ui.recordTaskComboBox
        self.record_duration_spin_box = self.main_window.ui.recordDurationSpinBox
        self.record_toggle_push_button = self.main_window.ui.recordRecordPushButton
        self.record_toggle_push_button.toggled.connect(self._start_recording)
        self.record_emg_progress_bar = self.main_window.ui.recordEMGProgressBar
        self.record_emg_progress_bar.setValue(0)
        self.record_kinematics_progress_bar = (
            self.main_window.ui.recordKinematicsProgressBar
        )
        self.record_kinematics_progress_bar.setValue(0)

        # Review Recording UI
        self.review_recording_stacked_widget = (
            self.main_window.ui.recordReviewRecordingStackedWidget
        )
        self.review_recording_stacked_widget.setCurrentIndex(0)

        self.review_recording_task_label = self.main_window.ui.reviewRecordingTaskLabel
        self.review_recording_label_line_edit = (
            self.main_window.ui.reviewRecordingLabelLineEdit
        )

        self.review_recording_accept_push_button = (
            self.main_window.ui.reviewRecordingAcceptPushButton
        )
        self.review_recording_accept_push_button.clicked.connect(self._accept_recording)

        self.review_recording_reject_push_button = (
            self.main_window.ui.reviewRecordingRejectPushButton
        )
        self.review_recording_reject_push_button.clicked.connect(self._reject_recording)

        self.use_kinematics_check_box = self.main_window.ui.recordUseKinematicsCheckBox
