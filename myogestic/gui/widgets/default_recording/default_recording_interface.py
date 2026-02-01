"""
Default Recording Interface for MyoGestic.

This interface is shown when no visual interface is open, allowing users to
record EMG data with standard VHI-style movements.
"""
from __future__ import annotations

import pickle
import time
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject

from myogestic.gui.widgets.default_recording.ui import Ui_DefaultRecordingInterface
from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.utils.constants import RECORDING_DIR_PATH

if TYPE_CHECKING:
    from myogestic.gui.myogestic import MyoGestic


class DefaultRecordingInterface(QObject):
    """
    Default recording interface shown when no visual interface is open.

    This provides a standard recording UI with 10 VHI-style movements,
    allowing users to record EMG data for basic classification tasks.

    Parameters
    ----------
    main_window : MyoGestic
        The main window of the application.
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
    ground_truth__nr_of_recording_values: int = 10

    def __init__(self, main_window: MyoGestic) -> None:
        super().__init__(main_window)
        self._main_window = main_window
        self.ui = Ui_DefaultRecordingInterface()

        # Create a widget to hold the UI
        from PySide6.QtWidgets import QWidget
        self._widget = QWidget()
        self.ui.setupUi(self._widget)

        RECORDING_DIR_PATH.mkdir(parents=True, exist_ok=True)

        self._current_task: str = ""
        self._recording_protocol = None  # Will be set after protocols are initialized
        self._start_time: float = 0

        self._is_initialized = False

    def initialize(self) -> None:
        """Initialize the UI logic after main window is fully set up."""
        if self._is_initialized:
            return

        self._recording_protocol = self._main_window.protocols[0]
        self._setup_ui()
        self._is_initialized = True

    def _setup_ui(self) -> None:
        """Set up the UI widgets and connections."""
        ui = self.ui

        # Add widgets to the recording layout
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

        # Progress bar from the UI
        self.record_ground_truth_progress_bar = ui.groundTruthProgressBar

        # Add tooltips
        self.record_task_combo_box.setToolTip("Select the gesture/movement to record")
        self.record_duration_spin_box.setToolTip("Recording duration in seconds")
        self.record_toggle_push_button.setToolTip(
            "Start recording EMG data for the selected task (no visual feedback)"
        )
        self.review_recording_accept_push_button.setToolTip("Save this recording to disk")
        self.review_recording_reject_push_button.setToolTip(
            "Discard this recording and try again"
        )
        self.review_recording_label_line_edit.setToolTip(
            "Optional label to identify this recording"
        )

        # Connect signals
        self.record_toggle_push_button.toggled.connect(self._start_recording)
        self.review_recording_accept_push_button.clicked.connect(self._accept_recording)
        self.review_recording_reject_push_button.clicked.connect(self._reject_recording)

        self.record_ground_truth_progress_bar.setValue(0)
        self.review_recording_stacked_widget.setCurrentIndex(0)

    def _start_recording(self, checked: bool) -> None:
        """Start the recording process."""
        if checked:
            if not self._start_recording_preparation():
                self.record_toggle_push_button.setChecked(False)
                return

            if not self._recording_protocol.start_recording_preparation_default(
                self.record_duration_spin_box.value(), self
            ):
                self.record_toggle_push_button.setChecked(False)
                return

            self._start_time = time.time()
            self.record_toggle_push_button.setText("Recording...")
            self.record_group_box.setEnabled(False)
            self._current_task = self.record_task_combo_box.currentText()

            # Show warning that no visual interface is open
            self._main_window.logger.print(
                "Recording without visual interface - no visual feedback will be provided.",
                level=LoggerLevel.WARNING,
            )

    def _start_recording_preparation(self) -> bool:
        """Prepare for recording by checking if device is streaming."""
        if (
            not self._main_window.device__widget._get_current_widget()._device._is_streaming
        ):
            self._main_window.logger.print(
                "Biosignal device not streaming!", level=LoggerLevel.ERROR
            )
            return False
        return True

    def check_recording_completion(self) -> None:
        """Check if recording is complete and finish if so."""
        if self._recording_protocol.is_biosignal_recording_complete:
            self._finish_recording()

    def _finish_recording(self) -> None:
        """Finish the recording process and switch to review interface."""
        self.review_recording_stacked_widget.setCurrentIndex(1)
        self.record_toggle_push_button.setText("Finished Recording")
        self.review_recording_task_label.setText(self._current_task.capitalize())

    def _accept_recording(self) -> None:
        """Accept and save the current recording."""
        label = self.review_recording_label_line_edit.text() or "default"
        (
            biosignal_data,
            biosignal_timings,
        ) = self._recording_protocol.retrieve_recorded_data()

        self._save_recording(
            biosignal=biosignal_data,
            biosignal_timings=biosignal_timings,
            ground_truth=np.array([]),
            ground_truth_timings=np.array([]),
            recording_label=label,
            task=self._current_task,
            ground_truth_sampling_frequency=0,
            use_as_classification=True,
            record_duration=self.record_duration_spin_box.value(),
        )

        self._reset_ui()
        self._main_window.logger.print(
            f"Recording of task {self._current_task.lower()} with label {label} accepted!"
        )

    def _save_recording(
        self,
        biosignal: np.ndarray,
        biosignal_timings: np.ndarray,
        ground_truth: np.ndarray,
        ground_truth_timings: np.ndarray,
        recording_label: str,
        task: str,
        ground_truth_sampling_frequency: int,
        use_as_classification: bool,
        record_duration: float,
    ) -> None:
        """Save the recording data to a pickle file.

        Uses the same format as RecordingInterfaceTemplate.save_recording
        for consistency with the rest of the application.
        """
        save_pickle_dict = {
            "biosignal": biosignal,
            "biosignal_timings": biosignal_timings,
            "ground_truth": ground_truth,
            "ground_truth_timings": ground_truth_timings,
            "recording_label": recording_label,
            "task": task,
            "ground_truth_sampling_frequency": ground_truth_sampling_frequency,
            "device_information": self._main_window.device__widget.get_device_information(),
            "bad_channels": self._main_window.current_bad_channels__list,
            "recording_time": record_duration,
            "use_as_classification": use_as_classification,
            "visual_interface": "Default",  # No VI, use "Default" identifier
            "task_map": self.ground_truth__task_map,
            "ground_truth__nr_of_recording_values": self.ground_truth__nr_of_recording_values,
        }

        file_name = f"Default_Recording_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{task.lower()}_{recording_label.lower()}.pkl"

        RECORDING_DIR_PATH.mkdir(parents=True, exist_ok=True)
        with (RECORDING_DIR_PATH / file_name).open("wb") as f:
            pickle.dump(save_pickle_dict, f)

        self._main_window.logger.print(f"Recording saved as: {file_name}")

    def _reject_recording(self) -> None:
        """Reject the current recording and reset the UI."""
        self._reset_ui()
        self._main_window.logger.print("Recording rejected.")

    def _reset_ui(self) -> None:
        """Reset the recording interface UI elements."""
        self.review_recording_stacked_widget.setCurrentIndex(0)
        self.record_toggle_push_button.setText("Start Recording")
        self.record_toggle_push_button.setChecked(False)
        self.record_group_box.setEnabled(True)

        self._recording_protocol._reset_recording_ui()
        self.record_ground_truth_progress_bar.setValue(0)

    def show(self) -> None:
        """Show the default recording interface widgets."""
        self.ui.recordRecordingGroupBox.show()
        self.ui.recordReviewRecordingStackedWidget.show()

    def hide(self) -> None:
        """Hide the default recording interface widgets."""
        self.ui.recordRecordingGroupBox.hide()
        self.ui.recordReviewRecordingStackedWidget.hide()
