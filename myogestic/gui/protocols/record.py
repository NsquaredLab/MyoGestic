from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional, Tuple, Union

import numpy as np
from PySide6.QtCore import QObject
from PySide6.QtGui import QCloseEvent

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.visual_interface import VisualInterface

if TYPE_CHECKING:
    from myogestic.gui.myogestic import MyoGestic
    from myogestic.gui.widgets.default_recording import DefaultRecordingInterface


PROGRESS_BAR_MAX = 100


class RecordProtocol(QObject):
    """Protocol for recording EMG and kinematics data.

    This class provides methods for recording EMG and kinematics data during specified tasks.
    It enables users to specify the recording duration, task type, and label, and handles the data recording process.

    Parameters
    ----------
    main_window : MyoGestic
        The parent application that manages the recording protocol.

    Attributes
    ----------
    _selected_visual_interface : Optional[VisualInterfaceTemplate]
        The visual interface used for the recording.
    _sampling_frequency : Optional[int]
        Sampling frequency of the biosignal device.
    _total_samples_to_record : int
        Total number of samples to be recorded.
    _biosignal__buffer : list[Tuple[float, np.ndarray]]
        Buffer for storing timestamped EMG data samples.
    is_biosignal_recording_complete : bool
        Indicates if the EMG recording process has completed.
    recording_start_time : float
        Start time of the recording session.
    """

    def __init__(self, main_window: MyoGestic) -> None:
        super().__init__(main_window)
        self._main_window = main_window

        self._sampling_frequency: Optional[int] = None
        self._selected_visual_interface: Optional[VisualInterface] = None
        self._default_recording_interface: Optional[DefaultRecordingInterface] = None

        self._recording_duration: float = 0.0
        self._biosignal__buffer: list[Tuple[float, np.ndarray]] = []

        self.is_biosignal_recording_complete: bool = False

        self.recording_start_time: float = 0.0

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
        if self._selected_visual_interface is None:
            self._main_window.logger.print(
                "No visual interface selected! Please open a visual interface first.",
                level=LoggerLevel.ERROR
            )
            return False

        # Clear default recording interface reference when using VI
        self._default_recording_interface = None

        device_widget = self._main_window.device__widget

        if not device_widget._get_current_widget()._device._is_streaming:  # noqa
            self._main_window.logger.print("Biosignal device is not streaming!", level=LoggerLevel.ERROR)
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

        This is used when no visual interface is open.

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
            self._main_window.logger.print("Biosignal device is not streaming!", level=LoggerLevel.ERROR)
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
        """Finalize the recording process."""
        self._main_window.logger.print(
            f"EMG recording finished in {round(time.time() - self.recording_start_time, 2)} seconds."
        )

        self.is_biosignal_recording_complete = True
        self._main_window.device__widget.data_arrived.disconnect(self.update_biosignal_buffer)

        # Handle completion callback for either VI recording or default recording
        if self._default_recording_interface is not None:
            self._default_recording_interface.check_recording_completion()
        elif self._selected_visual_interface:
            self._selected_visual_interface.recording_interface_ui.check_recording_completion()

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
