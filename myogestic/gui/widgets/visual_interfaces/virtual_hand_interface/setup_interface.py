import ast
import platform
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QByteArray, QMetaObject, QProcess, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtNetwork import QHostAddress, QUdpSocket
from PySide6.QtWidgets import QCheckBox, QPushButton, QWidget

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.visual_interface import SetupInterfaceTemplate
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface.ui import (
    Ui_SetupVirtualHandInterface
)
from myogestic.utils.constants import MYOGESTIC_UDP_PORT

# Stylesheets
NOT_CONNECTED_STYLESHEET = "background-color: red; border-radius: 5px;"
CONNECTED_STYLESHEET = "background-color: green; border-radius: 5px;"

# Constants
STREAMING_FREQUENCY = 32
TIME_BETWEEN_MESSAGES = 1 / STREAMING_FREQUENCY

SOCKET_IP = "127.0.0.1"
STATUS_REQUEST = "status"
STATUS_RESPONSE = "active"


# Ports
# on this port the VHI listens for incoming messages from MyoGestic
VHI__UDP_PORT = 1236

# on this port the VHI sends the currently displayed predicted hand after having applied linear interpolation
VHI_PREDICTION__UDP_PORT = 1234


class VirtualHandInterface_SetupInterface(SetupInterfaceTemplate):
    """
    Setup interface for the Virtual Hand Interface.

    This class is responsible for setting up the Virtual Hand Interface.

    Attributes
    ----------
    predicted_hand__signal : Signal
        Signal that emits the predicted hand data.

    Parameters
    ----------
    main_window : QMainWindow
        The main window of the application.
    name : str
        The name of the interface. Default is "VirtualHandInterface".

        .. important:: The name of the interface must be unique.
    """

    predicted_hand__signal = Signal(np.ndarray)

    def __init__(self, main_window, name="VirtualHandInterface"):
        super().__init__(main_window, name, ui=Ui_SetupVirtualHandInterface())

        self._unity_process = QProcess()
        self._unity_process.setProgram(str(self._get_unity_executable()))
        self._unity_process.started.connect(
            lambda: self._main_window.toggle_selected_visual_interface(self.name)
        )
        self._unity_process.finished.connect(self.interface_was_killed)
        self._unity_process.finished.connect(
            lambda: self._main_window.toggle_selected_visual_interface(self.name)
        )

        self._setup_timers()

        self._last_message_time = time.time()
        self._is_connected: bool = False
        self._streaming__udp_socket: QUdpSocket | None = None

        # Custom Stuff
        self._predicted_hand__udp_socket: QUdpSocket | None = None
        self._predicted_hand_recording__buffer: list[(float, np.ndarray)] = []

        # Initialize Virtual Hand Interface UI
        self.initialize_ui_logic()

    @staticmethod
    def _get_unity_executable() -> Path:
        """Get the path to the Unity executable based on the platform."""
        base_dirs = [
            Path("dist") if not hasattr(sys, "_MEIPASS") else Path(sys._MEIPASS, "dist"),
            Path("myogestic", "dist") if not hasattr(sys, "_MEIPASS") else Path(sys._MEIPASS, "dist"),
        ]

        unity_executable_paths = {
            "Windows": "windows/Virtual Hand Interface.exe",
            "Darwin": "macOS/Virtual Hand Interface.app/Contents/MacOS/Virtual Hand Interface",
        "Linux": "linux/VirtualHandInterface.x86_64",
    }

        for base_dir in base_dirs:
            executable = base_dir / unity_executable_paths.get(platform.system(), "")
            if executable.exists():
                return executable

        raise FileNotFoundError(f"Unity executable not found for platform {platform.system()}.")

    def _setup_timers(self):
        """Setup the timers for the Virtual Hand Interface."""
        self._status_request__timer = QTimer(self)
        self._status_request__timer.setInterval(2000)
        self._status_request__timer.timeout.connect(self.write_status_message)

        self._status_request_timeout__timer = QTimer(self)
        self._status_request_timeout__timer.setSingleShot(True)
        self._status_request_timeout__timer.setInterval(1000)
        self._status_request_timeout__timer.timeout.connect(self._update_status)

    def initialize_ui_logic(self):
        """Initialize the UI logic for the Virtual Hand Interface."""
        self._main_window.ui.visualInterfacesVerticalLayout.addWidget(self.ui.groupBox)

        self._toggle_virtual_hand_interface__push_button: QPushButton = (
            self.ui.toggleVirtualHandInterfacePushButton
        )
        self._toggle_virtual_hand_interface__push_button.clicked.connect(
            self.toggle_virtual_hand_interface
        )
        self._virtual_hand_interface__status_widget: QWidget = (
            self.ui.virtualHandInterfaceStatusWidget
        )

        self._virtual_hand_interface__status_widget.setStyleSheet(
            NOT_CONNECTED_STYLESHEET
        )

        self._use_external_virtual_hand_interface__check_box: QCheckBox = (
            self.ui.useExternalVirtualHandInterfaceCheckBox
        )

    def start_interface(self):
        """Start the Virtual Hand Interface."""
        if not self._use_external_virtual_hand_interface__check_box.isChecked():
            self._unity_process.start()
            self._unity_process.waitForStarted()
        self._status_request__timer.start()
        self.toggle_streaming()

    def stop_interface(self):
        """Stop the Virtual Hand Interface."""
        if not self._use_external_virtual_hand_interface__check_box.isChecked():
            self._unity_process.kill()
            self._unity_process.waitForFinished()
        # In case the stop function would be called from outside the main thread we need to use invokeMethod
        QMetaObject.invokeMethod(self._status_request__timer, "stop", Qt.QueuedConnection)
        self.toggle_streaming()

    def interface_was_killed(self) -> None:
        """Handle the case when the Virtual Hand Interface was killed."""
        self._toggle_virtual_hand_interface__push_button.setChecked(False)
        self._toggle_virtual_hand_interface__push_button.setText("Open")
        self._use_external_virtual_hand_interface__check_box.setEnabled(True)
        self._virtual_hand_interface__status_widget.setStyleSheet(
            NOT_CONNECTED_STYLESHEET
        )
        self._is_connected = False

    def close_event(self, _: QCloseEvent) -> None:
        """Handle the close event of the Virtual Hand Interface."""
        try:
            if self._streaming__udp_socket:
                self._streaming__udp_socket.close()
            if self._unity_process.state() != QProcess.NotRunning:
                self._unity_process.kill()
                self._unity_process.waitForFinished()
        except Exception as e:
            self._main_window.logger.print(
                f"Error during cleanup: {e}", level=LoggerLevel.ERROR
            )

    def _update_status(self) -> None:
        """Update the status of the Virtual Hand Interface."""
        self._is_connected = False
        self._virtual_hand_interface__status_widget.setStyleSheet(
            NOT_CONNECTED_STYLESHEET
        )

    def toggle_virtual_hand_interface(self):
        """Toggle the Virtual Hand Interface."""
        if self._toggle_virtual_hand_interface__push_button.isChecked():
            print("Opening Virtual Hand Interface")
            self.start_interface()
            self._use_external_virtual_hand_interface__check_box.setEnabled(False)
            self._toggle_virtual_hand_interface__push_button.setText("Close")
        else:
            print("Closing Virtual Hand Interface")
            self.stop_interface()
            self._use_external_virtual_hand_interface__check_box.setEnabled(True)
            self._toggle_virtual_hand_interface__push_button.setText("Open")

    def toggle_streaming(self) -> None:
        """Toggle the streaming of the Virtual Hand Interface."""
        if self._toggle_virtual_hand_interface__push_button.isChecked():
            self._streaming__udp_socket = QUdpSocket(self)
            self._streaming__udp_socket.readyRead.connect(self.read_message)
            self.outgoing_message_signal.connect(self.write_message)
            self._streaming__udp_socket.bind(
                QHostAddress(SOCKET_IP), MYOGESTIC_UDP_PORT
            )

            self._predicted_hand__udp_socket = QUdpSocket(self)
            self._predicted_hand__udp_socket.bind(
                QHostAddress(SOCKET_IP), VHI_PREDICTION__UDP_PORT
            )
            self._predicted_hand__udp_socket.readyRead.connect(self.read_predicted_hand)

            self._last_message_time = time.time()
        else:
            try:
                self._streaming__udp_socket.close()
                self._predicted_hand__udp_socket.close()
            except AttributeError:
                pass
            self._streaming__udp_socket = None
            self._predicted_hand__udp_socket = None
            self._is_connected = False
            self._virtual_hand_interface__status_widget.setStyleSheet(
                NOT_CONNECTED_STYLESHEET
            )

    def read_predicted_hand(self) -> None:
        """Read the predicted hand data from the Virtual Hand Interface."""
        while self._predicted_hand__udp_socket.hasPendingDatagrams():
            datagram, _, _ = self._predicted_hand__udp_socket.readDatagram(
                self._predicted_hand__udp_socket.pendingDatagramSize()
            )

            data = datagram.data().decode("utf-8")
            if not data:
                return

            self.predicted_hand__signal.emit(np.array(ast.literal_eval(data)))

    def write_message(self, message: QByteArray) -> None:
        """Write a message to the Virtual Hand Interface."""
        if self._is_connected and (
            time.time() - self._last_message_time >= TIME_BETWEEN_MESSAGES
        ):
            self._last_message_time = time.time()
            output_bytes = self._streaming__udp_socket.writeDatagram(
                message, QHostAddress(SOCKET_IP), VHI__UDP_PORT
            )

            if output_bytes == -1:
                self._main_window.logger.print(
                    "Error in sending message to Virtual Hand Interface!",
                    level=LoggerLevel.ERROR,
                )

    def read_message(self) -> None:
        """Read a message from the Virtual Hand Interface."""
        if self._toggle_virtual_hand_interface__push_button.isChecked():
            while self._streaming__udp_socket.hasPendingDatagrams():
                datagram, _, _ = self._streaming__udp_socket.readDatagram(
                    self._streaming__udp_socket.pendingDatagramSize()
                )

                data = datagram.data().decode("utf-8")
                if not data:
                    return

                try:
                    if data == STATUS_RESPONSE:
                        self._is_connected = True
                        self._virtual_hand_interface__status_widget.setStyleSheet(
                            CONNECTED_STYLESHEET
                        )
                        self._status_request_timeout__timer.stop()
                        return

                    self.incoming_message_signal.emit(np.array(ast.literal_eval(data)))
                except (UnicodeDecodeError, SyntaxError):
                    pass

    def write_status_message(self) -> None:
        """Write a status message to the Virtual Hand Interface."""
        if self._toggle_virtual_hand_interface__push_button.isChecked():
            output_bytes = self._streaming__udp_socket.writeDatagram(
                STATUS_REQUEST.encode("utf-8"),
                QHostAddress(SOCKET_IP),
                VHI__UDP_PORT,
            )

            if output_bytes == -1:
                self._main_window.logger.print(
                    "Error in sending status message to Virtual Hand Interface!",
                    level=LoggerLevel.ERROR,
                )
                return

            self._status_request_timeout__timer.start()

    def connect_custom_signals(self) -> None:
        """Connect custom signals for the Virtual Hand Interface."""
        self.predicted_hand__signal.connect(self.online_predicted_hand_update)

    def disconnect_custom_signals(self) -> None:
        """Disconnect custom signals for the Virtual Hand Interface."""
        self.predicted_hand__signal.disconnect(self.online_predicted_hand_update)

    def get_custom_save_data(self) -> dict:
        """Get custom save data for the Virtual Hand Interface."""
        return {
            "predicted_hand": np.vstack(
                [data for _, data in self._predicted_hand_recording__buffer],
            ).T,
            "predicted_hand_timings": np.array(
                [time for time, _ in self._predicted_hand_recording__buffer],
            ),
        }

    def clear_custom_signal_buffers(self) -> None:
        """Clear custom signal buffers for the Virtual Hand Interface."""
        self._predicted_hand_recording__buffer = []

    def online_predicted_hand_update(self, data: np.ndarray) -> None:
        """Update the predicted hand data for the online protocol."""
        if self._online_protocol.online_record_toggle_push_button.isChecked():
            self._predicted_hand_recording__buffer.append(
                (time.time() - self._online_protocol.recording_start_time, data)
            )
