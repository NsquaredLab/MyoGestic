import pickle
from datetime import datetime
from abc import abstractmethod
from typing import Optional, Type

import numpy as np
from PySide6.QtCore import QObject, Signal, QByteArray, SignalInstance
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox, QMainWindow

from myogestic.gui.widgets.templates.meta_qobject import MetaQObjectABC
from myogestic.utils.constants import RECORDING_DIR_PATH


class SetupInterfaceTemplate(QObject, metaclass=MetaQObjectABC):
    """
    Base class for the setup interface of a visual interface.

    This class contains the logic and the UI elements of the setup interface of a visual interface.

    Attributes
    ----------
    _main_window : Optional[QObject]
        The _main_window widget of the visual interface.
    name : str
        The name of the visual interface.
    ui : object
        The UI layout of the setup interface.
    outgoing_message_signal : PySide6.SignalInstance
        The outgoing message signal of the visual interface.
    incoming_message_signal : PySide6.SignalInstance
        The incoming message signal of the visual interface.
    """

    outgoing_message_signal = Signal(QByteArray)
    incoming_message_signal = Signal(np.ndarray)

    def __init__(self, main_window, name: str = "SetupUI", ui: object = None):
        super().__init__()

        from myogestic.gui.myogestic import MyoGestic

        self._main_window: MyoGestic = main_window
        self.name = name

        if not ui:
            raise ValueError("The UI object must be provided.")
        self.ui = ui
        self.ui.setupUi(self._main_window)

        from myogestic.gui.protocols.record import RecordProtocol
        from myogestic.gui.protocols.training import TrainingProtocol
        from myogestic.gui.protocols.online import OnlineProtocol

        self._record_protocol: RecordProtocol = self._main_window.protocols[0]
        self._training_protocol: TrainingProtocol = self._main_window.protocols[1]
        self._online_protocol: OnlineProtocol = self._main_window.protocols[2]

    @abstractmethod
    def initialize_ui_logic(self) -> None:
        """Initialize the logic of the UI elements."""
        pass

    @abstractmethod
    def start_interface(self) -> None:
        """Start the visual interface.

        This method should be called when the visual interface is started.
        .. tip:: It is generally a good idea to also start the connection to it here.

        """
        pass

    @abstractmethod
    def stop_interface(self) -> None:
        """Stop the visual interface.

        This method should be called when the visual interface is stopped.
        .. tip:: It is generally a good idea to also stop the connection to it here.

        """
        pass

    @abstractmethod
    def interface_was_killed(self) -> None:
        """Kill the visual interface.

        This method should be called when the visual interface is killed.
        .. tip:: It is generally a good idea to also kill the connection to it here.

        """
        pass

    @abstractmethod
    def close_event(self, event: QCloseEvent) -> None:
        """Close the interface and stop necessary processes."""
        pass

    def enable_ui(self):
        """Enable the UI elements.

        .. important:: This method assumes that the UI elements are in a `groupBox` widget.
        """
        self.ui.groupBox.setEnabled(True)

    def disable_ui(self):
        """Disable the UI elements.

        .. important:: This method assumes that the UI elements are in a `groupBox` widget.
        """
        self.ui.groupBox.setEnabled(False)

    def _log_error(self, message: str) -> None:
        """Log an error message."""
        if self.parent:
            QMessageBox.critical(self.parent, "Error", message)

    @abstractmethod
    def connect_custom_signals(self):
        """Connect custom signals to slots."""
        pass

    @abstractmethod
    def disconnect_custom_signals(self):
        """Disconnect custom signals from slots."""
        pass

    def get_custom_save_data(self) -> dict:
        """Get custom data to save.

        Returns
        -------
        dict
            The custom data to save. If no custom data is available, an empty dictionary must be returned.
        """
        return {}

    @abstractmethod
    def clear_custom_signal_buffers(self):
        """Clear the buffers of the custom signals."""
        pass


class RecordingInterfaceTemplate(QObject, metaclass=MetaQObjectABC):
    """
    Base class for the recording interface of a visual interface.

    This class contains the logic and the UI elements of the recording interface of a visual interface.

    Attributes
    ----------
    _main_window : Optional[QObject]
        The _main_window widget of the visual interface.
    name : str
        The name of the visual interface.
    ui : object
        The UI layout of the recording interface.
    incoming_message_signal : PySide6.QtCore.SignalInstance
        The incoming message signal of the visual interface.
    ground_truth__nr_of_recording_values : int
        The number of recording values the visual interface sends to MyoGestic.
    ground_truth__task_map : dict[str, int]
        The task map. The keys are the task names and the values are the task indices.
    """

    def __init__(
        self,
        main_window,
        name: str = "RecordingUI",
        ui: object | None = None,
        incoming_message_signal: SignalInstance | None = None,
        ground_truth__nr_of_recording_values: int = -1,
        ground_truth__task_map: dict[str, int] | None = None,
    ):
        super().__init__()

        from myogestic.gui.myogestic import MyoGestic

        self._main_window: MyoGestic = main_window
        self.name = name

        if not ui:
            raise ValueError("The UI object must be provided.")
        self.ui = ui
        self.ui.setupUi(self._main_window)

        self._record_emg_progress__bar = self._main_window.ui.recordEMGProgressBar
        self._record_emg_progress__bar.setValue(0)

        if ground_truth__nr_of_recording_values == -1:
            raise ValueError("The number of recording values must be provided.")
        self.ground_truth__nr_of_recording_values = ground_truth__nr_of_recording_values

        if not ground_truth__task_map:
            raise ValueError("The task map must be provided.")
        self.ground_truth__task_map = ground_truth__task_map

        # check if groundTruthProgressBar is in the UI
        if hasattr(self.ui, "groundTruthProgressBar"):
            self.ground_truth_recording_time = 0
            self.record_ground_truth_progress_bar = self.ui.groundTruthProgressBar
            self.record_ground_truth_progress_bar.setValue(0)
        else:
            raise ValueError(
                "A UI element named 'groundTruthProgressBar' must be provided in the ui file!"
            )

        if not incoming_message_signal:
            raise ValueError("The incoming message signal must be provided.")
        self.incoming_message_signal = incoming_message_signal

    def save_recording(
        self,
        biosignal: np.ndarray,
        biosignal_timings: np.ndarray,
        ground_truth: np.ndarray,
        ground_truth_timings: np.ndarray,
        record_duration: int | float,
        use_as_classification: bool,
        recording_label: str,
        task: str,
        ground_truth_sampling_frequency: int | float,
        **kwargs,
    ) -> None:
        """Save the recording.

        Parameters
        ----------
        biosignal : numpy.ndarray
            The recorded biosignal data.
        biosignal_timings : numpy.ndarray
            The recorded biosignal timings.
        ground_truth : numpy.ndarray
            The recorded ground truth data.
        ground_truth_timings : numpy.ndarray
            The recorded ground truth timings.
        record_duration : int | float
            The duration of the recording in seconds.
        use_as_classification : bool
            Whether to use the recording as classification data.
        recording_label : str
            The label of the recording.
        task : str
            The task of the recording.
        ground_truth_sampling_frequency : int | float
            The sampling frequency of the ground truth data.
        kwargs : dict
            Additional custom data to save.
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
            "visual_interface": self._main_window.selected_visual_interface.name,
        }

        save_pickle_dict.update(kwargs)

        file_name = f"{save_pickle_dict['visual_interface']}_Recording_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{task.lower()}_{recording_label.lower()}.pkl"

        with (RECORDING_DIR_PATH / file_name).open("wb") as f:
            pickle.dump(save_pickle_dict, f)

    def save_recording_cursor(
        self,
        biosignal: np.ndarray,
        biosignal_timings: np.ndarray,
        ground_truth: np.ndarray,
        ground_truth_timings: np.ndarray,
        record_duration: int | float,
        use_as_classification: bool,
        recording_label: str,
        task: str,
        movement: str,
        task_label_map: dict[str, int],
        ground_truth_sampling_frequency: int | float,
        **kwargs,
    ) -> None:
        """Save the recording for the cursor.

        Parameters
        ----------
        biosignal : numpy.ndarray
            The recorded biosignal data.
        biosignal_timings : numpy.ndarray
            The recorded biosignal timings.
        ground_truth : numpy.ndarray
            The recorded ground truth data.
        ground_truth_timings : numpy.ndarray
            The recorded ground truth timings.
        record_duration : int | float
            The duration of the recording in seconds.
        use_as_classification : bool
            Whether to use the recording as classification data.
        recording_label : str
            The label of the recording.
        task : str
            The task of the recording (cursor direction).
        movement : str
            The movement associated with the cursor task label.
        task_label_map : dict[str, int]
            String task to numerical table mapping.
        ground_truth_sampling_frequency : int | float
            The sampling frequency of the ground truth data.
        kwargs : dict
            Additional custom data to save.
        """

        save_pickle_dict = {
            "biosignal": biosignal,
            "biosignal_timings": biosignal_timings,
            "ground_truth": ground_truth,
            "ground_truth_timings": ground_truth_timings,
            "recording_label": recording_label,
            "task": task,
            "movement": movement,
            "task_label_map": task_label_map,
            "ground_truth_sampling_frequency": ground_truth_sampling_frequency,
            "device_information": self._main_window.device__widget.get_device_information(),
            "bad_channels": self._main_window.current_bad_channels__list,
            "recording_time": record_duration,
            "use_as_classification": use_as_classification,
            "visual_interface": self._main_window.selected_visual_interface.name,
        }

        save_pickle_dict.update(kwargs)

        file_name = f"{save_pickle_dict['visual_interface']}_Recording_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{task.lower()}_{recording_label.lower()}.pkl"

        with (RECORDING_DIR_PATH / file_name).open("wb") as f:
            pickle.dump(save_pickle_dict, f)

    @abstractmethod
    def initialize_ui_logic(self) -> None:
        """Initialize the logic of the UI elements."""
        pass

    @abstractmethod
    def enable(self) -> None:
        """Enable all UI elements."""
        pass

    @abstractmethod
    def disable(self) -> None:
        """Disable all UI elements."""
        pass

    @abstractmethod
    def close_event(self, event: QCloseEvent) -> None:
        """Close the interface and stop necessary processes."""
        pass

    @staticmethod
    def _set_progress_bar(progress_bar, value: int, total: int) -> None:
        """Set the value of a progress bar."""
        progress_bar.setValue(min(value / total * 100, 100))


class VisualInterface(QObject):
    """
    Base class for visual interfaces in the MyoGestic application.

    This class is the base class for visual interfaces in the MyoGestic application.

    Parameters
    ----------
    main_window : QMainWindow
        The main window of the visual interface.
    name : str
        The name of the visual interface. Default is "VisualInterface".

        .. important:: The name is used to identify the visual interface in the application. It should be unique.

    setup_interface_ui : Type[SetupInterfaceTemplate]
        The setup interface of the visual interface.
    recording_interface_ui : Type[RecordingInterfaceTemplate]
        The recording interface of the visual interface.

    Attributes
    ----------
    _main_window : QObject
        The main_window widget of the visual interface.
    setup_interface_ui : SetupInterfaceTemplate
        The setup interface of the visual interface.
    recording_interface_ui : RecordingInterfaceTemplate
        The recording interface of the visual interface.
    incoming_message_signal : PySide6.SignalInstance
        The incoming message signal of the visual interface.
    outgoing_message_signal : PySide6.SignalInstance
        The outgoing message signal of the visual interface.

    """

    def __init__(
        self,
        main_window: QMainWindow,
        name: str = "VisualInterface",
        setup_interface_ui: Type[SetupInterfaceTemplate] = None,
        recording_interface_ui: Type[RecordingInterfaceTemplate] = None,
    ) -> None:
        super().__init__()
        self._main_window = main_window
        self.name = name

        if not setup_interface_ui:
            raise ValueError("The setup interface must be provided.")
        self.setup_interface_ui : SetupInterfaceTemplate = setup_interface_ui(main_window, name)

        try:
            self.incoming_message_signal = (
                self.setup_interface_ui.incoming_message_signal
            )
            self.outgoing_message_signal = (
                self.setup_interface_ui.outgoing_message_signal
            )
        except AttributeError:
            raise ValueError(
                "The setup interface must have incoming and outgoing message signals."
            )

        if not recording_interface_ui:
            raise ValueError("The recording interface must be provided.")
        self.recording_interface_ui : RecordingInterfaceTemplate = recording_interface_ui(
            main_window,
            name,
            incoming_message_signal=self.incoming_message_signal,
        )

    def enable_ui(self) -> None:
        """Enable all UI elements."""
        if self.setup_interface_ui:
            self.setup_interface_ui.enable_ui()
        if self.recording_interface_ui:
            self.recording_interface_ui.enable()

    def disable_ui(self) -> None:
        """Disable all UI elements."""
        if self.setup_interface_ui:
            self.setup_interface_ui.disable_ui()
        if self.recording_interface_ui:
            self.recording_interface_ui.disable()

    def close_event(self, event: QCloseEvent) -> None:
        """Close the interface and stop necessary processes."""
        if self.setup_interface_ui:
            self.setup_interface_ui.close_event(event)
        if self.recording_interface_ui:
            self.recording_interface_ui.close_event(event)

    def _log_error(self, message: str) -> None:
        """Log an error message."""
        if self.parent:
            QMessageBox.critical(self.parent, "Error", message)
