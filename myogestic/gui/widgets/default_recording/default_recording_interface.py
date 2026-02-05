"""
Default Recording Interface for MyoGestic.

This interface is shown when no visual interface is open, allowing users to
record EMG data with standard VHI-style movements.
"""
from __future__ import annotations

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

    Provides a task selector only. The shared RecordProtocol controls
    manage the Record button, Duration spinner, and unified review.
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

        # Set GroupBox title
        self.record_group_box.setTitle("Default Recording")

        # Hide per-VI controls now managed by shared RecordProtocol
        self.record_toggle_push_button.hide()
        self.record_duration_spin_box.hide()
        ui.label_7.hide()  # Duration label
        self.review_recording_stacked_widget.hide()

        # Hide per-VI task selector (now managed by shared RecordProtocol)
        self.record_task_combo_box.hide()
        ui.label.hide()  # Task label

        # Hide ground truth progress bar - not needed when no VI is selected
        # (EMG progress bar at top is sufficient for classification-only recording)
        self.record_ground_truth_progress_bar.hide()

        # Hide the entire GroupBox since all its contents are hidden
        # (shared RecordProtocol controls handle everything)
        self.record_group_box.hide()

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

    def get_ground_truth_data(self) -> dict:
        """Return empty ground truth (classification-only, no kinematics)."""
        return {
            "ground_truth": np.array([]),
            "ground_truth_timings": np.array([]),
            "ground_truth_sampling_frequency": 0,
            "task": self._current_task,
            "use_as_classification": True,
        }

    def show(self) -> None:
        """Show the default recording interface widgets."""
        self.ui.recordRecordingGroupBox.show()

    def hide(self) -> None:
        """Hide the default recording interface widgets."""
        self.ui.recordRecordingGroupBox.hide()
