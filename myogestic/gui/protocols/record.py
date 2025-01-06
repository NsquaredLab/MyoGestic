from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QObject

from myogestic.gui.widgets.templates.visual_interface import VisualInterfaceTemplate

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
    biosignal_buffer : list[(int, np.ndarray)]
        A list of tuples containing the timestamp and EMG data samples.
    kinematics_buffer : list[(int, np.ndarray)]
        A list of tuples containing the timestamp and kinematics data samples.
    has_finished_emg : bool
        A flag indicating whether the EMG recording has finished.
    has_finished_kinematics : bool
        A flag indicating whether the kinematics recording has finished.
    start_time : float
        The start time of the recording.
    emg_recording_time : int
        The total number of EMG samples to be recorded.
    """

    def __init__(self, parent: MyoGestic | None = ...) -> None:
        super().__init__(parent)
        self.main_window = parent

        self.selected_visual_interface: Optional[VisualInterfaceTemplate] = None

