from abc import abstractmethod
from typing import Optional, Type

import numpy as np
from PySide6.QtCore import QObject, Signal, QByteArray, SignalInstance
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox, QMainWindow

from myogestic.gui.widgets.templates.meta_qobject import MetaQObjectABC


class SetupUITemplate(QObject, metaclass=MetaQObjectABC):
    """
    Base class for the setup interface of a visual interface.

    This class contains the logic and the UI elements of the setup interface of a visual interface.

    Attributes
    ----------
    main_window : Optional[QObject]
        The main_window widget of the visual interface.
    """

    __outgoing_message_signal = Signal(QByteArray)
    __incoming_message_signal = Signal(np.ndarray)

    def __init__(
        self,
        main_window: QMainWindow = None,
        name: str = "SetupUI",
        ui: object = None,
    ):
        super().__init__()
        self.main_window = main_window
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


class RecordingUITemplate(QObject, metaclass=MetaQObjectABC):
    """
    Base class for the recording interface of a visual interface.

    This class contains the logic and the UI elements of the recording interface of a visual interface.
    """

    def __init__(
        self,
        main_window: Optional[QMainWindow] = None,
        name: str = "RecordingUI",
        ui: object = None,
        incoming_message_signal: SignalInstance = None,
    ):
        super().__init__()
        self.main_window = main_window
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
        self.__incoming_message_signal = incoming_message_signal

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
        progress_bar.setValue(min(value / total * 100, 100))


class VisualInterfaceTemplate(QObject, metaclass=MetaQObjectABC):
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
        setup_interface_ui: Type[SetupUITemplate] = None,
        recording_interface_ui: Type[RecordingUITemplate] = None,
    ) -> None:
        super().__init__()
        self.main_window = main_window
        self.name = name
        self.setup_interface_ui = setup_interface_ui(main_window, name)

        try:
            self.incoming_message_signal = (
                self.setup_interface_ui.__incoming_message_signal
            )
            self.outgoing_message_signal = (
                self.setup_interface_ui.__outgoing_message_signal
            )
        except AttributeError:
            raise ValueError(
                "The setup interface must have incoming and outgoing message signals."
            )

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
