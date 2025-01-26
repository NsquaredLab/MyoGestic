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
    main_window : Optional[QObject]
        The main_window widget of the visual interface.
    """

    outgoing_message_signal = Signal(QByteArray)
    incoming_message_signal = Signal(np.ndarray)

    def __init__(self, main_window, name: str = "SetupUI", ui: object = None):
        super().__init__()

        from myogestic.gui.myogestic import MyoGestic

        self.main_window: MyoGestic = main_window
        self.name = name

        if not ui:
            raise ValueError("The UI object must be provided.")
        self.ui = ui
        self.ui.setupUi(self.main_window)

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
    def closeEvent(self, event: QCloseEvent) -> None:
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
    """

    def __init__(
        self,
        main_window,
        name: str = "RecordingUI",
        ui: object = None,
        incoming_message_signal: SignalInstance = None,
    ):
        super().__init__()

        from myogestic.gui.myogestic import MyoGestic

        self.main_window: MyoGestic = main_window
        self.name = name

        if not ui:
            raise ValueError("The UI object must be provided.")
        self.ui = ui
        self.ui.setupUi(self.main_window)

        self.record_emg_progress_bar = self.main_window.ui.recordEMGProgressBar
        self.record_emg_progress_bar.setValue(0)

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
        biosignal : np.ndarray
            The recorded biosignal data.
        biosignal_timings : np.ndarray
            The recorded biosignal timings.
        ground_truth : np.ndarray
            The recorded ground truth data.
        ground_truth_timings : np.ndarray
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
            "device_information": self.main_window.device__widget.get_device_information(),
            "bad_channels": self.main_window.current_bad_channels__list,
            "recording_time": record_duration,
            "use_as_classification": use_as_classification,
            "visual_interface": self.main_window.selected_visual_interface.name,
        }

        save_pickle_dict.update(kwargs)

        file_name = f"{save_pickle_dict["visual_interface"]}_Recording_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{task.lower()}_{recording_label.lower()}.pkl"

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
    def closeEvent(self, event: QCloseEvent) -> None:
        """Close the interface and stop necessary processes."""
        pass

    @staticmethod
    def _set_progress_bar(progress_bar, value: int, total: int) -> None:
        progress_bar.setValue(min(value / total * 100, 100))


class VisualInterface(QObject):
    """
    Base class for visual interfaces in the MyoGestic application.

    This class is the base class for visual interfaces in the MyoGestic application.

    Attributes
    ----------
    main_window : Optional[QObject]
        The main_window widget of the visual interface.
    """

    def __init__(
        self,
        main_window: Optional[QMainWindow] = None,
        name: str = "VisualInterface",
        setup_interface_ui: Type[SetupInterfaceTemplate] = None,
        recording_interface_ui: Type[RecordingInterfaceTemplate] = None,
    ) -> None:
        super().__init__()
        self.main_window = main_window
        self.name = name

        if not setup_interface_ui:
            raise ValueError("The setup interface must be provided.")
        self.setup_interface_ui = setup_interface_ui(main_window, name)

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
        self.recording_interface_ui = recording_interface_ui(
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

    def closeEvent(self, event: QCloseEvent) -> None:
        """Close the interface and stop necessary processes."""
        if self.setup_interface_ui:
            self.setup_interface_ui.closeEvent(event)
        if self.recording_interface_ui:
            self.recording_interface_ui.closeEvent(event)

    def _log_error(self, message: str) -> None:
        """Log an error message."""
        if self.parent:
            QMessageBox.critical(self.parent, "Error", message)
