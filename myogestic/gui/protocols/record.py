from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject
from PySide6.QtGui import QCloseEvent

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.visual_interface import VisualInterface

if TYPE_CHECKING:
    from myogestic.gui.myogestic import MyoGestic


PROGRESS_BAR_MAX = 100


class RecordProtocol(QObject):
    """Protocol for recording EMG and kinematics data.

    This class provides methods for recording EMG and kinematics data during specified tasks.
    It enables users to specify the recording duration, task type, and label, and handles the data recording process.

    Parameters
    ----------
    parent : MyoGestic, optional
        The parent application that manages the recording protocol.

    Attributes
    ----------
    main_window : MyoGestic
        Reference to the main application window.
    selected_visual_interface : Optional[VisualInterfaceTemplate]
        The visual interface used for the recording.
    sampling_frequency : Optional[int]
        Sampling frequency of the biosignal device.
    total_samples_to_record : int
        Total number of samples to be recorded.
    biosignal_buffer : list[Tuple[float, np.ndarray]]
        Buffer for storing timestamped EMG data samples.
    is_biosignal_recording_complete : bool
        Indicates if the EMG recording process has completed.
    start_time : float
        Start time of the recording session.
    """

    def __init__(self, parent: MyoGestic | None = None) -> None:
        super().__init__(parent)
        self.main_window = parent
        self.sampling_frequency: Optional[int] = None
        self.selected_visual_interface: Optional[VisualInterface] = None
        self.total_samples_to_record: int = 0
        self.biosignal_buffer: list[Tuple[float, np.ndarray]] = []
        self.is_biosignal_recording_complete: bool = False
        self.start_time: float = 0.0

    def start_recording_preparation(self, duration: float) -> bool:
        """Prepare for EMG data recording.

        Parameters
        ----------
        duration : float
            Duration of the recording in seconds.

        Returns
        -------
        bool
            True if preparation succeeds, False otherwise.
        """
        device_widget = self.main_window.device_widget
        device = device_widget._get_current_widget()._device
        if not device._is_streaming:
            self.main_window.logger.print(
                "Biosignal device not streaming!", level=LoggerLevel.ERROR
            )
            return False

        self.sampling_frequency = device_widget.get_device_information()[
            "sampling_frequency"
        ]
        self.total_samples_to_record = int(duration * self.sampling_frequency)
        self.biosignal_buffer.clear()
        self.is_biosignal_recording_complete = False
        self.start_time = time.time()

        device_widget.biosignal_data_arrived.connect(self.update_biosignal_buffer)
        return True

    def update_biosignal_buffer(self, data: np.ndarray) -> None:
        """Update the buffer with incoming EMG data.

        Parameters
        ----------
        data : np.ndarray
            New EMG data sample.
        """
        self.biosignal_buffer.append((time.time(), data))
        total_collected_samples = sum(
            sample.shape[1] for _, sample in self.biosignal_buffer
        )
        progress = int(
            (total_collected_samples / self.total_samples_to_record) * PROGRESS_BAR_MAX
        )
        self.main_window.ui.recordEMGProgressBar.setValue(progress)

        if total_collected_samples >= self.total_samples_to_record:
            self._complete_recording_process()

    def _complete_recording_process(self) -> None:
        """Finalize the recording process."""
        elapsed_time = round(time.time() - self.start_time, 2)
        self.main_window.logger.print(
            f"EMG recording finished in {elapsed_time} seconds."
        )
        self.is_biosignal_recording_complete = True
        self.main_window.device_widget.biosignal_data_arrived.disconnect(
            self.update_biosignal_buffer
        )
        if self.selected_visual_interface:
            self.selected_visual_interface.recording_interface_ui.check_recording_completion()

    def retrieve_recorded_data(self) -> Tuple[np.ndarray, np.ndarray]:
        """Retrieve recorded EMG data and timestamps.

        Returns
        -------
        Tuple[np.ndarray, np.ndarray]
            A tuple of EMG data and corresponding timestamps.
        """
        emg, timings = [], []

        for timestamp, sample in self.biosignal_buffer:
            emg.append(sample)
            timings.append(timestamp)

        return np.stack(emg, axis=-1)[..., : self.total_samples_to_record], np.array(
            timings
        )

    def _reset_recording_ui(self) -> None:
        """Reset the recording UI and clear the buffer."""
        self.main_window.ui.recordEMGProgressBar.setValue(0)
        self.biosignal_buffer.clear()

    def closeEvent(self, _: QCloseEvent) -> None:
        """Handle the close event for the recording protocol."""
        self._reset_recording_ui()
        self.is_biosignal_recording_complete = False
        self.main_window.logger.print("Recording protocol closed.")
