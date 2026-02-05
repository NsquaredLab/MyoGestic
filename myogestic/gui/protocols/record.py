from __future__ import annotations

import pickle
import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject
from PySide6.QtGui import QCloseEvent
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QWidget,
)

from myogestic.gui.widgets.highlighter import WidgetHighlighter
from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.visual_interface import VisualInterface
from myogestic.utils.constants import RECORDING_DIR_PATH

if TYPE_CHECKING:
    from myogestic.gui.myogestic import MyoGestic
    from myogestic.gui.widgets.default_recording import DefaultRecordingInterface


PROGRESS_BAR_MAX = 100

# ---------------------------------------------------------------------------
# Task map categories — VIs in the same category share the same task map.
# ---------------------------------------------------------------------------
HAND_TASK_MAP: dict[str, int] = {
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
CURSOR_TASK_MAP: dict[str, int] = {
    "rest": 0,
    "up": 1,
    "down": 2,
    "right": 3,
    "left": 4,
}
DEFAULT_TASK_MAP: dict[str, int] = HAND_TASK_MAP

# Map VI short names to (category_label, task_map)
VI_TASK_CATEGORY: dict[str, tuple[str, dict[str, int]]] = {
    "VHI": ("Hand", HAND_TASK_MAP),
    "KHI": ("Hand", HAND_TASK_MAP),
    "VCI": ("Cursor", CURSOR_TASK_MAP),
}


class RecordProtocol(QObject):
    """Protocol for recording EMG and kinematics data.

    Manages shared recording controls (Record button, Duration spinner)
    and a unified review dialog (accept/reject) for all active visual
    interfaces.  Each VI contributes per-VI settings (task selector,
    kinematics checkbox) while the shared controls orchestrate a single
    recording session across all of them.

    Parameters
    ----------
    main_window : MyoGestic
        The parent application that manages the recording protocol.
    """

    def __init__(self, main_window: MyoGestic) -> None:
        super().__init__(main_window)
        self._main_window = main_window
        self._highlighter = WidgetHighlighter(self)

        # Track recordings made this session for preloading in Training
        self._session_recording_paths: list[str] = []

        self._sampling_frequency: Optional[int] = None
        self._selected_visual_interface: Optional[VisualInterface] = None
        self._active_visual_interfaces: dict[str, VisualInterface] = {}
        self._default_recording_interface: Optional[DefaultRecordingInterface] = None

        self._recording_duration: float = 0.0
        self._biosignal__buffer: list[Tuple[float, np.ndarray]] = []

        self.is_biosignal_recording_complete: bool = False
        self.recording_start_time: float = 0.0

        # Track which VIs still need to finish their ground-truth recording
        self._pending_vi_completions: set[str] = set()

        # --- Shared UI widgets (created in _create_shared_controls) ---
        self._shared_controls_group: Optional[QGroupBox] = None
        self._shared_task_combo: Optional[QComboBox] = None
        self._shared_task_model: Optional[QStandardItemModel] = None
        self._shared_duration_spin: Optional[QSpinBox] = None
        self._shared_record_btn: Optional[QPushButton] = None

        self._review_stacked: Optional[QStackedWidget] = None
        self._review_task_label: Optional[QLabel] = None
        self._review_label_edit: Optional[QLineEdit] = None
        self._review_accept_btn: Optional[QPushButton] = None
        self._review_reject_btn: Optional[QPushButton] = None

        self._create_shared_controls()

    # ------------------------------------------------------------------
    # Shared UI creation
    # ------------------------------------------------------------------

    def _create_shared_controls(self) -> None:
        """Build the shared Recording Controls group and unified review widget."""
        layout = self._main_window.ui.recordVerticalLayout
        layout.setSpacing(2)

        # --- Recording Controls group ---
        self._shared_controls_group = QGroupBox("Recording Controls")
        grid = QGridLayout(self._shared_controls_group)

        task_label = QLabel("Task")
        self._shared_task_combo = QComboBox()
        self._shared_task_model = QStandardItemModel()
        self._shared_task_combo.setModel(self._shared_task_model)
        self._shared_task_combo.setToolTip("Select the task/gesture to record")

        duration_label = QLabel("Duration (s)")
        self._shared_duration_spin = QSpinBox()
        self._shared_duration_spin.setRange(1, 300)
        self._shared_duration_spin.setValue(10)
        self._shared_duration_spin.setToolTip("Recording duration in seconds")

        self._shared_record_btn = QPushButton("Start Recording")
        self._shared_record_btn.setCheckable(True)
        self._shared_record_btn.setToolTip("Start recording EMG data for all active interfaces")

        grid.addWidget(task_label, 0, 0)
        grid.addWidget(self._shared_task_combo, 0, 1)
        grid.addWidget(duration_label, 1, 0)
        grid.addWidget(self._shared_duration_spin, 1, 1)
        grid.addWidget(self._shared_record_btn, 2, 0, 1, 2)

        # Populate with default tasks initially
        self._rebuild_shared_task_selector()

        layout.insertWidget(0, self._shared_controls_group)

        # --- Unified review widget (QStackedWidget: page 0 = empty, page 1 = review) ---
        self._review_stacked = QStackedWidget()

        # Page 0: empty placeholder
        self._review_stacked.addWidget(QWidget())

        # Page 1: review controls
        review_page = QWidget()
        review_grid = QGridLayout(review_page)

        task_header = QLabel("Task(s):")
        self._review_task_label = QLabel("")
        label_header = QLabel("Recording Label:")
        self._review_label_edit = QLineEdit()
        self._review_label_edit.setPlaceholderText("default")
        self._review_label_edit.setToolTip("Optional label to identify this recording")

        self._review_accept_btn = QPushButton("Accept")
        self._review_accept_btn.setToolTip("Save this recording to disk")
        self._review_reject_btn = QPushButton("Reject")
        self._review_reject_btn.setToolTip("Discard this recording and try again")

        review_grid.addWidget(task_header, 0, 0)
        review_grid.addWidget(self._review_task_label, 0, 1)
        review_grid.addWidget(label_header, 1, 0)
        review_grid.addWidget(self._review_label_edit, 1, 1)
        review_grid.addWidget(self._review_accept_btn, 2, 0)
        review_grid.addWidget(self._review_reject_btn, 2, 1)

        self._review_stacked.addWidget(review_page)
        self._review_stacked.setCurrentIndex(0)

        # NOTE: _review_stacked is NOT added to layout here.
        # Call finalize_layout() after all VI recording interfaces are created
        # to ensure the review widget appears below all per-VI sections.

        # --- Connections ---
        self._shared_record_btn.toggled.connect(self._on_shared_record_toggled)
        self._review_accept_btn.clicked.connect(self._accept_recording)
        self._review_reject_btn.clicked.connect(self._reject_recording)

    def finalize_layout(self) -> None:
        """Add the unified review widget at the end of the recording layout.

        Must be called after all VI recording interfaces have been created
        and added their per-VI GroupBoxes to the layout.
        """
        layout = self._main_window.ui.recordVerticalLayout
        layout.addWidget(self._review_stacked)

    # ------------------------------------------------------------------
    # Shared task selector
    # ------------------------------------------------------------------

    def _rebuild_shared_task_selector(self) -> None:
        """Rebuild the shared task combo box based on active visual interfaces.

        Groups tasks by VI category (Hand, Cursor) and shows only the groups
        relevant to the currently active VIs.  When no VIs are active, shows
        the default task map.
        """
        prev_text = self._shared_task_combo.currentText()
        self._shared_task_model.clear()

        if not self._active_visual_interfaces:
            # No VIs active — show default tasks
            header = QStandardItem("── Default ──")
            header.setEnabled(False)
            self._shared_task_model.appendRow(header)
            for task_name in DEFAULT_TASK_MAP:
                self._shared_task_model.appendRow(QStandardItem(task_name.title()))
        else:
            # Group active VIs by category
            seen_categories: dict[str, list[str]] = {}  # category -> [vi_names]
            for vi_name in self._active_visual_interfaces:
                # Derive short name (e.g. "VirtualHandInterface" -> "VHI")
                short = self._vi_short_name(vi_name)
                cat_label, _ = VI_TASK_CATEGORY.get(short, ("Other", DEFAULT_TASK_MAP))
                seen_categories.setdefault(cat_label, []).append(short)

            for cat_label, vi_shorts in seen_categories.items():
                # Determine task map for this category
                _, task_map = VI_TASK_CATEGORY.get(vi_shorts[0], ("Other", DEFAULT_TASK_MAP))
                vi_list = " / ".join(vi_shorts)
                header = QStandardItem(f"── {cat_label} ({vi_list}) ──")
                header.setEnabled(False)
                self._shared_task_model.appendRow(header)
                for task_name in task_map:
                    self._shared_task_model.appendRow(QStandardItem(task_name.title()))

        # Restore previous selection if still valid
        idx = self._shared_task_combo.findText(prev_text)
        if idx >= 0:
            self._shared_task_combo.setCurrentIndex(idx)
        else:
            # Select first selectable item (skip disabled headers)
            for i in range(self._shared_task_model.rowCount()):
                item = self._shared_task_model.item(i)
                if item and item.isEnabled():
                    self._shared_task_combo.setCurrentIndex(i)
                    break

    @staticmethod
    def _vi_short_name(vi_name: str) -> str:
        """Convert a VI name like 'VirtualHandInterface' to its short form 'VHI'.

        Falls back to the first 3 uppercase chars if no mapping is found.
        """
        _SHORT_NAMES = {
            "VirtualHandInterface": "VHI",
            "KappaHandInterface": "KHI",
            "VirtualCursorInterface": "VCI",
        }
        return _SHORT_NAMES.get(vi_name, vi_name[:3].upper())

    # ------------------------------------------------------------------
    # Shared recording orchestration
    # ------------------------------------------------------------------

    def _on_shared_record_toggled(self, checked: bool) -> None:
        """Handle the shared Record button being toggled."""
        if not checked:
            return

        duration = self._shared_duration_spin.value()

        # If no VIs are active, delegate to DefaultRecordingInterface
        if not self._active_visual_interfaces:
            default_iface = self._main_window._default_recording_interface
            if not default_iface._start_recording_preparation():
                self._shared_record_btn.setChecked(False)
                return
            if not self.start_recording_preparation_default(duration, default_iface):
                self._shared_record_btn.setChecked(False)
                return

            default_iface._start_time = time.time()
            default_iface._current_task = self._shared_task_combo.currentText()
            default_iface.record_group_box.setEnabled(False)

            self._shared_record_btn.setText("Recording...")
            self._shared_controls_group.setEnabled(False)
            self._main_window.logger.print(
                "Recording without visual interface - no visual feedback will be provided.",
                level=LoggerLevel.WARNING,
            )
            return

        # --- Recording with active VIs ---
        self._pending_vi_completions.clear()

        # Prepare each active VI
        for vi_name, vi in self._active_visual_interfaces.items():
            rec_ui = vi.recording_interface_ui
            if not rec_ui.start_recording_preparation():
                self._shared_record_btn.setChecked(False)
                return

        # Start shared EMG recording
        if not self.start_recording_preparation(duration):
            self._shared_record_btn.setChecked(False)
            return

        # Now start each VI's recording process
        shared_task = self._shared_task_combo.currentText()
        for vi_name, vi in self._active_visual_interfaces.items():
            rec_ui = vi.recording_interface_ui
            rec_ui._start_time = time.time()
            rec_ui._current_task = shared_task
            rec_ui.record_group_box.setEnabled(False)

            # Connect kinematics if applicable
            has_kinematics_cb = hasattr(rec_ui, "use_kinematics_check_box")
            if has_kinematics_cb and rec_ui.use_kinematics_check_box.isChecked():
                rec_ui.incoming_message_signal.connect(rec_ui.update_ground_truth_buffer)
                self._pending_vi_completions.add(vi_name)
                rec_ui._has_finished_kinematics = False
            else:
                # No kinematics → mark as already done
                if hasattr(rec_ui, "_has_finished_kinematics"):
                    rec_ui._has_finished_kinematics = True

            # Store cursor movement if VCI
            if hasattr(rec_ui, "record_movement_combo_box"):
                rec_ui._current_movement = rec_ui.record_movement_combo_box.currentText()

        self._shared_record_btn.setText("Recording...")
        self._shared_controls_group.setEnabled(False)

    def vi_recording_completed(self, vi_name: str) -> None:
        """Called by a VI when its ground-truth recording is done.

        Parameters
        ----------
        vi_name : str
            Name of the VI that completed.
        """
        self._pending_vi_completions.discard(vi_name)
        if not self._pending_vi_completions and self.is_biosignal_recording_complete:
            self._all_recordings_complete()

    def _all_recordings_complete(self) -> None:
        """All VIs and EMG recording are done — show unified review."""
        shared_task = self._shared_task_combo.currentText()
        if self._active_visual_interfaces:
            vi_names = ", ".join(self._active_visual_interfaces.keys())
            task_text = f"{shared_task} ({vi_names})"
        else:
            task_text = f"{shared_task} (Default)"

        self._review_task_label.setText(task_text)
        self._review_stacked.setCurrentIndex(1)
        self._shared_record_btn.setText("Finished Recording")

    def _accept_recording(self) -> None:
        """Collect ground truth from all active VIs and save combined recording."""
        label = self._review_label_edit.text() or "default"
        biosignal_data, biosignal_timings = self.retrieve_recorded_data()

        saved_path = None
        if self._active_visual_interfaces:
            saved_path = self._save_combined_recording(biosignal_data, biosignal_timings, label)
        elif self._default_recording_interface is not None:
            saved_path = self._save_default_recording(biosignal_data, biosignal_timings, label)

        # Track recording path for preloading in Training
        if saved_path:
            self._session_recording_paths.append(saved_path)

        self._reset_all_recording_ui()
        self._main_window.logger.print(f"Recording with label '{label}' accepted!")

        # Guide user to Training protocol after at least 2 recordings
        if len(self._session_recording_paths) >= 2:
            self._highlighter.highlight(self._main_window.ui.protocolTrainingRadioButton)

    def _reject_recording(self) -> None:
        """Discard recording and reset everything."""
        self._reset_all_recording_ui()
        self._main_window.logger.print("Recording rejected.")

    def _save_combined_recording(
        self,
        biosignal: np.ndarray,
        biosignal_timings: np.ndarray,
        recording_label: str,
    ) -> None:
        """Save a unified pickle with ground truth from all active VIs."""
        duration = self._shared_duration_spin.value()
        shared_task = self._shared_task_combo.currentText()

        # Collect per-VI ground truth
        ground_truths: dict[str, dict] = {}
        first_vi_data = None
        for vi_name, vi in self._active_visual_interfaces.items():
            gt_data = vi.recording_interface_ui.get_ground_truth_data()
            ground_truths[vi_name] = gt_data
            if first_vi_data is None:
                first_vi_data = gt_data

        # Backward-compatible top-level keys from first VI
        if first_vi_data is None:
            first_vi_data = {
                "ground_truth": np.array([]),
                "ground_truth_timings": np.array([]),
                "ground_truth_sampling_frequency": 0,
                "task": shared_task,
                "use_as_classification": True,
            }

        vi_name_list = list(self._active_visual_interfaces.keys())

        save_dict = {
            # Shared data
            "biosignal": biosignal,
            "biosignal_timings": biosignal_timings,
            "device_information": self._main_window.device__widget.get_device_information(),
            "bad_channels": self._main_window.current_bad_channels__list,
            "recording_time": duration,
            "recording_label": recording_label,
            # Per-VI ground truths
            "ground_truths": ground_truths,
            # Backward-compat: top-level from first VI
            "ground_truth": first_vi_data["ground_truth"],
            "ground_truth_timings": first_vi_data.get("ground_truth_timings", np.array([])),
            "ground_truth_sampling_frequency": first_vi_data.get("ground_truth_sampling_frequency", 0),
            "task": shared_task,
            "use_as_classification": first_vi_data.get("use_as_classification", True),
            # New format: list of VI names
            "visual_interface": vi_name_list,
            # Backward-compat: comma-separated string
            "visual_interface_str": ", ".join(vi_name_list),
        }

        # Add cursor-specific fields from first VI if present
        if "movement" in first_vi_data:
            save_dict["movement"] = first_vi_data["movement"]
        if "task_label_map" in first_vi_data:
            save_dict["task_label_map"] = first_vi_data["task_label_map"]

        vi_names = "_".join(vi_name_list)
        task_str = shared_task.lower()
        file_name = (
            f"{vi_names}_Recording_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_"
            f"{task_str}_{recording_label.lower()}.pkl"
        )

        RECORDING_DIR_PATH.mkdir(parents=True, exist_ok=True)
        full_path = RECORDING_DIR_PATH / file_name
        with full_path.open("wb") as f:
            pickle.dump(save_dict, f)

        self._main_window.logger.print(f"Recording saved as: {file_name}")
        return str(full_path)

    def _save_default_recording(
        self,
        biosignal: np.ndarray,
        biosignal_timings: np.ndarray,
        recording_label: str,
    ) -> None:
        """Save recording when using the default (no-VI) interface."""
        default_iface = self._default_recording_interface
        duration = self._shared_duration_spin.value()
        shared_task = self._shared_task_combo.currentText()

        save_dict = {
            "biosignal": biosignal,
            "biosignal_timings": biosignal_timings,
            "ground_truth": np.array([]),
            "ground_truth_timings": np.array([]),
            "recording_label": recording_label,
            "task": shared_task,
            "ground_truth_sampling_frequency": 0,
            "device_information": self._main_window.device__widget.get_device_information(),
            "bad_channels": self._main_window.current_bad_channels__list,
            "recording_time": duration,
            "use_as_classification": True,
            "visual_interface": ["Default"],
            "visual_interface_str": "Default",
            "task_map": default_iface.ground_truth__task_map,
            "ground_truth__nr_of_recording_values": default_iface.ground_truth__nr_of_recording_values,
        }

        task_str = shared_task.lower()
        file_name = (
            f"Default_Recording_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_"
            f"{task_str}_{recording_label.lower()}.pkl"
        )

        RECORDING_DIR_PATH.mkdir(parents=True, exist_ok=True)
        full_path = RECORDING_DIR_PATH / file_name
        with full_path.open("wb") as f:
            pickle.dump(save_dict, f)

        self._main_window.logger.print(f"Recording saved as: {file_name}")
        return str(full_path)

    def _reset_all_recording_ui(self) -> None:
        """Reset shared controls and all per-VI UIs."""
        # Shared controls
        self._shared_record_btn.setText("Start Recording")
        self._shared_record_btn.setChecked(False)
        self._shared_controls_group.setEnabled(True)
        self._review_stacked.setCurrentIndex(0)
        self._review_label_edit.clear()

        # EMG progress bar and buffer
        self._reset_recording_ui()

        # Reset each active VI's recording UI
        for vi in self._active_visual_interfaces.values():
            rec_ui = vi.recording_interface_ui
            rec_ui.record_group_box.setEnabled(True)
            rec_ui.record_ground_truth_progress_bar.setValue(0)
            if hasattr(rec_ui, "_kinematics__buffer"):
                rec_ui._kinematics__buffer.clear()

        # Reset default recording interface if used
        if self._default_recording_interface is not None:
            default_iface = self._main_window._default_recording_interface
            default_iface.record_group_box.setEnabled(True)
            default_iface.record_ground_truth_progress_bar.setValue(0)

        self._pending_vi_completions.clear()

    # ------------------------------------------------------------------
    # EMG recording (biosignal buffer management)
    # ------------------------------------------------------------------

    def start_recording_preparation(self, duration: float) -> bool:
        """Prepare for EMG data recording with visual interface.

        Parameters
        ----------
        duration : float
            Duration of the recording in seconds.

        Returns
        -------
        bool
            True if preparation succeeds, False otherwise.
        """
        if not self._active_visual_interfaces:
            self._main_window.logger.print(
                "No visual interface selected! Please open a visual interface first.",
                level=LoggerLevel.ERROR,
            )
            return False

        # Clear default recording interface reference when using VI
        self._default_recording_interface = None

        device_widget = self._main_window.device__widget

        if not device_widget._get_current_widget()._device._is_streaming:  # noqa
            self._main_window.logger.print(
                "Biosignal device is not streaming!", level=LoggerLevel.ERROR
            )
            return False

        self._sampling_frequency = device_widget.get_device_information()["sampling_frequency"]
        self._recording_duration = duration
        self._biosignal__buffer.clear()
        self.is_biosignal_recording_complete = False
        self.recording_start_time = time.time()

        device_widget.data_arrived.connect(self.update_biosignal_buffer)
        return True

    def start_recording_preparation_default(
        self, duration: float, default_interface: DefaultRecordingInterface
    ) -> bool:
        """Prepare for EMG data recording with the default recording interface.

        Parameters
        ----------
        duration : float
            Duration of the recording in seconds.
        default_interface : DefaultRecordingInterface
            The default recording interface instance.

        Returns
        -------
        bool
            True if preparation succeeds, False otherwise.
        """
        device_widget = self._main_window.device__widget

        if not device_widget._get_current_widget()._device._is_streaming:  # noqa
            self._main_window.logger.print(
                "Biosignal device is not streaming!", level=LoggerLevel.ERROR
            )
            return False

        # Store reference to default interface for completion callback
        self._default_recording_interface = default_interface

        self._sampling_frequency = device_widget.get_device_information()["sampling_frequency"]
        self._recording_duration = duration
        self._biosignal__buffer.clear()
        self.is_biosignal_recording_complete = False
        self.recording_start_time = time.time()

        device_widget.data_arrived.connect(self.update_biosignal_buffer)
        return True

    def update_biosignal_buffer(self, data: np.ndarray) -> None:
        """Update the buffer with incoming EMG data.

        Parameters
        ----------
        data : np.ndarray
            New EMG data sample.
        """
        self._biosignal__buffer.append((time.time(), data))

        # Progress based on elapsed time, not sample count
        elapsed = time.time() - self.recording_start_time
        progress = min(int((elapsed / self._recording_duration) * PROGRESS_BAR_MAX), PROGRESS_BAR_MAX)
        self._main_window.ui.recordEMGProgressBar.setValue(progress)

        if elapsed >= self._recording_duration:
            self._complete_recording_process()

    def _complete_recording_process(self) -> None:
        """Finalize the EMG recording process."""
        self._main_window.logger.print(
            f"EMG recording finished in {round(time.time() - self.recording_start_time, 2)} seconds."
        )

        self.is_biosignal_recording_complete = True
        self._main_window.device__widget.data_arrived.disconnect(self.update_biosignal_buffer)

        # Handle completion callback for default recording
        if self._default_recording_interface is not None:
            # Default interface has no kinematics — go straight to review
            self._all_recordings_complete()
            return

        # For VI recording, check completion on ALL active VIs
        for vi in self._active_visual_interfaces.values():
            vi.recording_interface_ui.check_recording_completion()

        # If no VIs had pending kinematics, we're done
        if not self._pending_vi_completions:
            self._all_recordings_complete()

    def retrieve_recorded_data(self) -> Tuple[np.ndarray, np.ndarray]:
        """Retrieve recorded EMG data and timestamps.

        Returns
        -------
        Tuple[np.ndarray, np.ndarray]
            A tuple of EMG data and corresponding timestamps.
        """
        emg, timings = [], []

        for timestamp, sample in self._biosignal__buffer:
            emg.append(sample)
            timings.append(timestamp)

        return np.stack(emg, axis=-1), np.array(timings)

    def _reset_recording_ui(self) -> None:
        """Reset the recording UI and clear the buffer."""
        self._main_window.ui.recordEMGProgressBar.setValue(0)
        self._biosignal__buffer.clear()

    def close_event(self, _: QCloseEvent) -> None:
        """Handle the close event for the recording protocol."""
        self._reset_recording_ui()
        self.is_biosignal_recording_complete = False
        self._main_window.logger.print("Recording protocol closed.")
