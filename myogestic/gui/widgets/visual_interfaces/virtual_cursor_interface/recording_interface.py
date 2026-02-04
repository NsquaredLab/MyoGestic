import time

import numpy as np
from PySide6.QtCore import SignalInstance
from PySide6.QtGui import QCloseEvent

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.visual_interface import RecordingInterfaceTemplate
from myogestic.gui.widgets.visual_interfaces.virtual_cursor_interface.ui import (
    Ui_RecordingVirtualCursorInterface,
)
from myogestic.utils.constants import RECORDING_DIR_PATH


class VirtualCursorInterface_RecordingInterface(RecordingInterfaceTemplate):
    """Recording interface for the Virtual Cursor Interface.

    Handles per-VI settings (task, movement, kinematics checkbox) while
    the shared RecordProtocol manages Record button, Duration, and
    unified review.
    """

    ground_truth__task_map: dict[str, int] = {
        "rest": 0,
        "up": 1,
        "down": 2,
        "right": 3,
        "left": 4,
    }
    ground_truth__nr_of_recording_values: int = 2

    def __init__(
        self,
        main_window,
        name: str = "VirtualCursorInterface",
        incoming_message_signal: SignalInstance = None,
    ) -> None:
        super().__init__(
            main_window,
            name,
            ui=Ui_RecordingVirtualCursorInterface(),
            incoming_message_signal=incoming_message_signal,
            ground_truth__nr_of_recording_values=self.ground_truth__nr_of_recording_values,
            ground_truth__task_map=self.ground_truth__task_map,
        )

        RECORDING_DIR_PATH.mkdir(parents=True, exist_ok=True)

        self._current_task: str = ""
        self._current_movement: str = ""
        self._kinematics__buffer = []

        self._recording_protocol = self._main_window.protocols[0]

        self._has_finished_kinematics: bool = False
        self._start_time: float = 0

        self.initialize_ui_logic()

    def initialize_ui_logic(self) -> None:
        """Initializes the logic for the UI elements."""
        ui: Ui_RecordingVirtualCursorInterface = self.ui

        self._main_window.ui.recordVerticalLayout.addWidget(ui.recordRecordingGroupBox)
        self._main_window.ui.recordVerticalLayout.addWidget(ui.recordReviewRecordingStackedWidget)

        self.record_group_box = ui.recordRecordingGroupBox
        self.record_task_combo_box = ui.recordTaskComboBox
        self.record_movement_combo_box = ui.recordMovementComboBox
        self.record_duration_spin_box = ui.recordDurationSpinBox
        self.record_toggle_push_button = ui.recordRecordPushButton

        self.review_recording_stacked_widget = ui.recordReviewRecordingStackedWidget
        self.review_recording_task_label = ui.reviewRecordingTaskLabel
        self.review_recording_label_line_edit = ui.reviewRecordingLabelLineEdit

        self.review_recording_accept_push_button = ui.reviewRecordingAcceptPushButton
        self.review_recording_reject_push_button = ui.reviewRecordingRejectPushButton

        self.use_kinematics_check_box = ui.recordUseCursorKinematicsCheckBox

        # Store kinematics sampling frequency
        self.kinematics_samp_freq_spin_box = ui.kinematicsSampFreqSpinBox
        self.kinematics_samp_freq = int(self.kinematics_samp_freq_spin_box.value())
        self.kinematics_samp_freq_spin_box.valueChanged.connect(self.update_kinematics_samp_freq)

        # Set GroupBox title to VI name
        self.record_group_box.setTitle(self.name)

        # Hide per-VI controls now managed by shared RecordProtocol
        self.record_toggle_push_button.hide()
        self.record_duration_spin_box.hide()
        ui.label_7.hide()  # Duration label
        self.review_recording_stacked_widget.hide()

        # Shorten checkbox text (GroupBox title already identifies the VI)
        self.use_kinematics_check_box.setText("Use Kinematics")

        # Hide per-VI task selector (now managed by shared RecordProtocol)
        self.record_task_combo_box.hide()
        ui.label.hide()  # Task cursor direction label

        # Add tooltips for remaining visible controls
        self.record_movement_combo_box.setToolTip("Select the specific movement pattern")
        self.use_kinematics_check_box.setToolTip(
            "Record cursor position data from the Virtual Cursor Interface"
        )
        self.kinematics_samp_freq_spin_box.setToolTip(
            "Sampling frequency for cursor position data (Hz)"
        )

        self.record_ground_truth_progress_bar.setValue(0)

    def start_recording_preparation(self) -> bool:
        """Prepares the recording process by checking if the device is streaming."""
        if not self._main_window.device__widget._get_current_widget()._device._is_streaming:
            self._main_window.logger.print(
                "Biosignal device not streaming!", level=LoggerLevel.ERROR
            )
            return False

        self.kinematics_recording_time = int(
            self._recording_protocol._shared_duration_spin.value()
            * self.kinematics_samp_freq
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

    def update_kinematics_samp_freq(self) -> None:
        """Updates the kinematics sampling frequency of the cursor."""
        self.kinematics_samp_freq = int(self.kinematics_samp_freq_spin_box.value())
        self._main_window.logger.print(
            "Check that kinematics samp freq matches one set in cursor interface.",
            level=LoggerLevel.WARNING,
        )

    def check_recording_completion(self) -> None:
        """Checks if this VI's recording is complete and notifies the protocol."""
        if (
            self._recording_protocol.is_biosignal_recording_complete
            and self._has_finished_kinematics
        ):
            self._recording_protocol.vi_recording_completed(self.name)

    def get_ground_truth_data(self) -> dict:
        """Return cursor kinematics data if checkbox checked, else empty."""
        if self.use_kinematics_check_box.isChecked() and self._kinematics__buffer:
            return {
                "ground_truth": np.vstack(
                    [data[:, :2] for _, data in self._kinematics__buffer]
                ).T,
                "ground_truth_timings": np.array(
                    [t for t, _ in self._kinematics__buffer]
                ),
                "ground_truth_sampling_frequency": self.kinematics_samp_freq,
                "task": self._current_task,
                "movement": self._current_movement,
                "task_label_map": self.ground_truth__task_map,
                "use_as_classification": False,
            }
        return {
            "ground_truth": np.array([]),
            "ground_truth_timings": np.array([]),
            "ground_truth_sampling_frequency": self.kinematics_samp_freq,
            "task": self._current_task,
            "movement": getattr(self, "_current_movement", ""),
            "task_label_map": self.ground_truth__task_map,
            "use_as_classification": True,
        }

    def close_event(self, _: QCloseEvent) -> None:
        """Closes the recording interface."""
        self._kinematics__buffer.clear()
        self.record_ground_truth_progress_bar.setValue(0)

    def enable(self):
        """Enable the UI elements."""
        self.ui.recordRecordingGroupBox.setEnabled(True)

    def disable(self):
        """Disable the UI elements."""
        self.ui.recordRecordingGroupBox.setEnabled(False)
