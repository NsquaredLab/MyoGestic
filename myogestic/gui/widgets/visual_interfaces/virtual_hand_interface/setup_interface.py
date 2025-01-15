import ast
import platform
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer, QProcess, QByteArray, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtNetwork import QUdpSocket, QHostAddress
from PySide6.QtWidgets import QCheckBox, QPushButton, QWidget

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.visual_interface import SetupUITemplate
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface import (
    Ui_SetupVirtualHandInterface,
)
from myogestic.utils.constants import MYOGESTIC_UDP_PORT

# Stylesheets
RED_BACKGROUND = "background-color: red; border-radius: 5px;"
GREEN_BACKGROUND = "background-color: green; border-radius: 5px;"

# Constants
STREAMING_FREQUENCY = 32
SOCKET_IP = "127.0.0.1"

# Ports

# on this port the VHI listens for incoming messages from MyoGestic
VHI__UDP_PORT = 1236

# on this port the VHI sends the currently displayed predicted hand after having applied linear interpolation
VHI_PREDICTION__UDP_PORT = 1234


class VirtualHandInterfaceSetupUI(SetupUITemplate):

    _predicted_hand_signal = Signal(np.ndarray)

    def __init__(self, parent, name="VirtualHandInterface"):
        super().__init__(parent, name, ui=Ui_SetupVirtualHandInterface())

        # Initialize Virtual Hand Interface
        self.status_request: str = "status"
        self.status_response: str = "active"

        self._setup_timers()

        self.unity_process = QProcess()
        self.unity_process.finished.connect(self.interface_was_killed)

        # Toggle the selected visual interface when the Unity process is started or finished
        self.unity_process.finished.connect(
            lambda: self.main_window._toggle_selected_visual_interface(self.name)
        )
        self.unity_process.started.connect(
            lambda: self.main_window._toggle_selected_visual_interface(self.name)
        )

        self.record_protocol = self.main_window.protocol.available_protocols[0]

        # Get OS of the user
        self.unity_process.setProgram(str(self._get_unity_executable()))

        self.time_difference_between_messages = float(1 / STREAMING_FREQUENCY)
        self.last_message_time = time.time()
        self.is_connected: bool = False

        self.streaming_udp_socket: QUdpSocket | None = None
        self.predicted_hand_udp_socket: QUdpSocket | None = None

        # Initialize Virtual Hand Interface UI
        self.initialize_ui_logic()

    @staticmethod
    def _get_unity_executable() -> Path:
        base_dir = (
            Path("dist") if not hasattr(sys, "_MEIPASS") else Path(sys._MEIPASS, "dist")
        )
        unity_executable_paths = {
            "Windows": base_dir / "windows" / "Virtual Hand Interface.exe",
            "Darwin": base_dir
            / "macOS"
            / "Virtual Hand Interface.app"
            / "Contents"
            / "MacOS"
            / "Virtual Hand Interface",
            "Linux": base_dir / "linux" / "VirtualHandInterface.x86_64",
        }

        executable = unity_executable_paths.get(platform.system())
        if executable and executable.exists():
            return executable
        raise FileNotFoundError(
            f"Unity executable not found for platform {platform.system()}."
        )

    def _setup_timers(self):
        self.status_request_timer = QTimer(self)
        self.status_request_timer.setInterval(2000)
        self.status_request_timer.timeout.connect(self.write_status_message)

        self.status_request_timeout_timer = QTimer(self)
        self.status_request_timeout_timer.setSingleShot(True)
        self.status_request_timeout_timer.setInterval(1000)
        self.status_request_timeout_timer.timeout.connect(self._update_status)

    def initialize_ui_logic(self):
        self.main_window.ui.visualInterfacesVerticalLayout.addWidget(self.ui.groupBox)

        self.toggle_virtual_hand_interface_push_button: QPushButton = (
            self.ui.toggleVirtualHandInterfacePushButton
        )
        self.toggle_virtual_hand_interface_push_button.clicked.connect(
            self.toggle_virtual_hand_interface
        )
        self.virtual_hand_interface_status_widget: QWidget = (
            self.ui.virtualHandInterfaceStatusWidget
        )
        self.virtual_hand_interface_not_connected_stylesheet = RED_BACKGROUND
        self.virtual_hand_interface_connected_stylesheet = GREEN_BACKGROUND
        self.virtual_hand_interface_status_widget.setStyleSheet(
            self.virtual_hand_interface_not_connected_stylesheet
        )

        self.use_external_virtual_hand_interface_check_box: QCheckBox = (
            self.ui.useExternalVirtualHandInterfaceCheckBox
        )

    def start_interface(self):
        if not self.use_external_virtual_hand_interface_check_box.isChecked():
            self.unity_process.start()
            self.unity_process.waitForStarted()
        self.status_request_timer.start()
        self.toggle_streaming()

    def stop_interface(self):
        if not self.use_external_virtual_hand_interface_check_box.isChecked():
            self.unity_process.kill()
            self.unity_process.waitForFinished()
        self.status_request_timer.stop()
        self.toggle_streaming()

    def interface_was_killed(self) -> None:
        self.toggle_virtual_hand_interface_push_button.setChecked(False)
        self.toggle_virtual_hand_interface_push_button.setText("Open")
        self.use_external_virtual_hand_interface_check_box.setEnabled(True)
        self.virtual_hand_interface_status_widget.setStyleSheet(
            self.virtual_hand_interface_not_connected_stylesheet
        )
        self.is_connected = False

    def closeEvent(self, _: QCloseEvent) -> None:
        try:
            if self.streaming_udp_socket:
                self.streaming_udp_socket.close()
            if self.unity_process.state() != QProcess.NotRunning:
                self.unity_process.kill()
                self.unity_process.waitForFinished()
        except Exception as e:
            self.main_window.logger.print(
                f"Error during cleanup: {e}", level=LoggerLevel.ERROR
            )

    def _update_status(self) -> None:
        self.is_connected = False
        self.virtual_hand_interface_status_widget.setStyleSheet(
            self.virtual_hand_interface_not_connected_stylesheet
        )

    def toggle_virtual_hand_interface(self):
        if self.toggle_virtual_hand_interface_push_button.isChecked():
            print("Opening Virtual Hand Interface")
            self.start_interface()
            self.use_external_virtual_hand_interface_check_box.setEnabled(False)
            self.toggle_virtual_hand_interface_push_button.setText("Close")
        else:
            print("Closing Virtual Hand Interface")
            self.stop_interface()
            self.use_external_virtual_hand_interface_check_box.setEnabled(True)
            self.toggle_virtual_hand_interface_push_button.setText("Open")

    def toggle_streaming(self) -> None:
        if self.toggle_virtual_hand_interface_push_button.isChecked():
            self.streaming_udp_socket = QUdpSocket(self)
            self.streaming_udp_socket.readyRead.connect(self.read_message)
            self._outgoing_message_signal.connect(self.write_message)
            self.streaming_udp_socket.bind(
                QHostAddress(SOCKET_IP), MYOGESTIC_UDP_PORT
            )

            self.predicted_hand_udp_socket = QUdpSocket(self)
            self.predicted_hand_udp_socket.bind(
                QHostAddress(SOCKET_IP), VHI_PREDICTION__UDP_PORT
            )
            self.predicted_hand_udp_socket.readyRead.connect(self.read_predicted_hand)

            self.last_message_time = time.time()
        else:
            try:
                self.streaming_udp_socket.close()
                self.predicted_hand_udp_socket.close()
            except AttributeError:
                pass
            self.streaming_udp_socket = None
            self.predicted_hand_udp_socket = None
            self.is_connected = False
            self.virtual_hand_interface_status_widget.setStyleSheet(
                self.virtual_hand_interface_not_connected_stylesheet
            )

    def read_predicted_hand(self) -> None:
        while self.predicted_hand_udp_socket.hasPendingDatagrams():
            datagram, _, _ = self.predicted_hand_udp_socket.readDatagram(
                self.predicted_hand_udp_socket.pendingDatagramSize()
            )

            data = datagram.data().decode("utf-8")
            if not data:
                return

            self._predicted_hand_signal.emit(np.array(ast.literal_eval(data)))

    def write_message(self, message: QByteArray) -> None:
        if self.is_connected:
            if (
                time.time() - self.last_message_time
                < self.time_difference_between_messages
            ):
                return
            self.last_message_time = time.time()
            output_bytes = self.streaming_udp_socket.writeDatagram(
                message,
                QHostAddress(SOCKET_IP),
                VHI__UDP_PORT,
            )

            if output_bytes == -1:
                self.main_window.logger.print(
                    "Error in sending message to Virtual Hand Interface!",
                    level=LoggerLevel.ERROR,
                )

    def read_message(self) -> None:
        if self.toggle_virtual_hand_interface_push_button.isChecked():
            while self.streaming_udp_socket.hasPendingDatagrams():
                datagram, _, _ = self.streaming_udp_socket.readDatagram(
                    self.streaming_udp_socket.pendingDatagramSize()
                )

                if len(datagram.data()) == 0:
                    return

                if (
                    len(datagram.data()) == len(self.status_response.encode("utf-8"))
                    and datagram.data().decode("utf-8") == self.status_response
                ):
                    self.is_connected = True
                    self.virtual_hand_interface_status_widget.setStyleSheet(
                        self.virtual_hand_interface_connected_stylesheet
                    )
                    self.status_request_timeout_timer.stop()
                    return

                self._incoming_message_signal.emit(
                    np.array(ast.literal_eval(datagram.data().decode("utf-8")))
                )

    def write_status_message(self) -> None:
        if self.toggle_virtual_hand_interface_push_button.isChecked():
            output_bytes = self.streaming_udp_socket.writeDatagram(
                self.status_request.encode("utf-8"),
                QHostAddress(SOCKET_IP),
                VHI__UDP_PORT,
            )

            if output_bytes == -1:
                self.main_window.logger.print(
                    "Error in sending status message to Virtual Hand Interface!",
                    level=LoggerLevel.ERROR,
                )
                return

            self.status_request_timeout_timer.start()
