from __future__ import annotations

import ast
import os
import platform
import sys
import time
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QByteArray, QObject, QProcess, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtNetwork import QHostAddress, QUdpSocket
from PySide6.QtWidgets import QCheckBox, QMessageBox, QPushButton, QWidget
from myogestic.gui.widgets.logger import LoggerLevel


class VHIStatus(Enum):
    CONNECTED: 0
    DISCONNECTED: 1
    ERROR: 2


if TYPE_CHECKING:
    from myogestic.gui.myogestic import MyoGestic


class VirtualHandInterface(QObject):
    output_message_signal = Signal(QByteArray)
    mechatronic_output_message_signal = Signal(QByteArray)
    input_message_signal = Signal(np.ndarray)

    def __init__(self, parent: MyoGestic | None = ...) -> None:
        super().__init__(parent)

        self.main_window = parent

        # Initialize Virtual Hand Interface
        # Create QProcess that runs Unity .exe
        self.unity_process = QProcess()
        self.unity_process.finished.connect(
            self._virtual_hand_interface_process_stopped
        )

        # Get OS of the user
        if hasattr(sys, "_MEIPASS"):
            base_dir = os.path.join(sys._MEIPASS, "dist")
        else:
            base_dir = "dist"

        local_os = platform.system()
        match local_os:
            case "Windows":
                unity_executable = os.path.join(
                    base_dir, "windows", "Virtual Hand Interface.exe"
                )

            case "Darwin":
                unity_executable = os.path.join(
                    base_dir,
                    "macOS",
                    "Virtual Hand Interface.app",
                    "Contents",
                    "MacOS",
                    "Virtual Hand Interface",
                )

            case "Linux":
                unity_executable = os.path.join(
                    base_dir, "linux", "VirtualHandInterface.x86_64"
                )

            case _:
                QMessageBox.critical(
                    self.main_window,
                    "Error",
                    "OS not supported for Virtual Hand Interface!",
                )
                return
        if not os.path.exists(unity_executable):
            QMessageBox.critical(
                self.main_window,
                "Error",
                "Virtual Hand Interface executable not found!",
            )
            return

        self.unity_process.setProgram(unity_executable)

        # Initialize MyoGestic UDP Socket
        self._setup_virtual_hand_interface()

        # Initialize Virtual Hand Interface
        self.status_request: str = "status"
        self.status_response: str = "active"
        self.status_request_timer = QTimer(self)
        self.status_request_timer.setInterval(2000)
        self.status_request_timer.timeout.connect(self._write_status_message)
        self.status_request_timeout_timer = QTimer(self)
        self.status_request_timeout_timer.timeout.connect(self._update_status)
        self.status_request_timeout_timer.setSingleShot(True)
        self.status_request_timeout_timer.setInterval(1000)

    def show(self):
        if not self.use_external_virtual_hand_interface_check_box.isChecked():
            self.unity_process.start()
            self.unity_process.waitForStarted()
        self.status_request_timer.start()
        self._toggle_streaming()

    def hide(self):
        if not self.use_external_virtual_hand_interface_check_box.isChecked():
            self.unity_process.kill()
            self.unity_process.waitForFinished()
        self.status_request_timer.stop()
        self._toggle_streaming()

    def _virtual_hand_interface_process_stopped(self) -> None:
        self.toggle_virtual_hand_interface_push_button.setChecked(False)
        self.toggle_virtual_hand_interface_push_button.setText("Open")
        self.use_external_virtual_hand_interface_check_box.setEnabled(True)
        self.virtual_hand_interface_status_widget.setStyleSheet(
            self.virtual_hand_interface_not_connected_stylesheet
        )
        self.is_connected = False

    def _update_status(self) -> None:
        self.is_connected = False
        self.virtual_hand_interface_status_widget.setStyleSheet(
            self.virtual_hand_interface_not_connected_stylesheet
        )

    def _read_message(self) -> None:
        if self.toggle_virtual_hand_interface_push_button.isChecked():
            while self.streaming_udp_socket.hasPendingDatagrams():
                datagram, _, port = self.streaming_udp_socket.readDatagram(
                    self.streaming_udp_socket.pendingDatagramSize()
                )

                if port != self.virtual_hand_interface_udp_port:
                    continue

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

                self.input_message_signal.emit(
                    np.array(ast.literal_eval(datagram.data().decode("utf-8")))
                )

    def _write_message(self, message: QByteArray) -> None:
        if self.is_connected:
            if (
                time.time() - self.last_message_time
                < self.time_difference_between_messages
            ):
                return
            self.last_message_time = time.time()
            output_bytes = self.streaming_udp_socket.writeDatagram(
                message,
                QHostAddress(self.socket_ip),
                self.virtual_hand_interface_udp_port,
            )

            if output_bytes == -1:
                self.main_window.logger.print(
                    "Error in sending message to Virtual Hand Interface!",
                    level=LoggerLevel.ERROR,
                )

    def _write_mechatronic_control_message(self, message: QByteArray) -> None:
        if self.is_connected:
            output_bytes = self.streaming_udp_socket.writeDatagram(
                message,
                QHostAddress(self.socket_ip),
                self.neuroorthosis_udp_port,
            )

            # print("Message sent to Mechatronic")

            if output_bytes == -1:
                self.main_window.logger.print(
                    "Error in sending message to the Neuroorthosis",
                    level=LoggerLevel.ERROR,
                )

    def _toggle_streaming(self) -> None:
        if self.toggle_virtual_hand_interface_push_button.isChecked():
            self.streaming_udp_socket = QUdpSocket(self)
            self.streaming_udp_socket.readyRead.connect(self._read_message)
            self.output_message_signal.connect(self._write_message)
            self.mechatronic_output_message_signal.connect(
                self._write_mechatronic_control_message
            )
            self.streaming_udp_socket.bind(
                QHostAddress(self.socket_ip), self.myogestic_udp_port
            )
            self.last_message_time = time.time()
        else:
            self.streaming_udp_socket.close()
            self.streaming_udp_socket = None
            self.is_connected = False
            self.virtual_hand_interface_status_widget.setStyleSheet(
                self.virtual_hand_interface_not_connected_stylesheet
            )

    def _write_status_message(self) -> None:
        if self.toggle_virtual_hand_interface_push_button.isChecked():
            output_bytes = self.streaming_udp_socket.writeDatagram(
                self.status_request.encode("utf-8"),
                QHostAddress(self.socket_ip),
                self.virtual_hand_interface_udp_port,
            )

            if output_bytes == -1:
                self.main_window.logger.print(
                    "Error in sending status message to Virtual Hand Interface!",
                    level=LoggerLevel.ERROR,
                )
                return

            self.status_request_timeout_timer.start()

    def _toggle_virtual_hand_interface(self):
        if self.toggle_virtual_hand_interface_push_button.isChecked():
            self.show()
            self.use_external_virtual_hand_interface_check_box.setEnabled(False)
            self.toggle_virtual_hand_interface_push_button.setText("Close")
        else:
            self.hide()
            self.use_external_virtual_hand_interface_check_box.setEnabled(True)
            self.toggle_virtual_hand_interface_push_button.setText("Open")

    def _setup_virtual_hand_interface(self):
        self.socket_ip: str = "127.0.0.1"
        self.myogestic_udp_port: int = 1233
        self.virtual_hand_interface_udp_port: int = 1236
        self.neuroorthosis_udp_port: int = 1212

        self.streaming_frequency: int = 32
        self.time_difference_between_messages = float(1 / self.streaming_frequency)
        self.last_message_time = time.time()
        self.is_connected: bool = False

        self.streaming_udp_socket: QUdpSocket | None = None

        self.toggle_virtual_hand_interface_push_button: QPushButton = (
            self.main_window.ui.toggleVirtualHandInterfacePushButton
        )
        self.toggle_virtual_hand_interface_push_button.clicked.connect(
            self._toggle_virtual_hand_interface
        )
        self.virtual_hand_interface_status_widget: QWidget = (
            self.main_window.ui.virtualHandInterfaceStatusWidget
        )
        self.virtual_hand_interface_not_connected_stylesheet = (
            "background-color: red; border-radius: 5px;"
        )
        self.virtual_hand_interface_connected_stylesheet = (
            "background-color: green; border-radius: 5px;"
        )
        self.virtual_hand_interface_status_widget.setStyleSheet(
            self.virtual_hand_interface_not_connected_stylesheet
        )

        self.use_external_virtual_hand_interface_check_box: QCheckBox = (
            self.main_window.ui.useExternalVirtualHandInterfaceCheckBox
        )

    def closeEvent(self, _: QCloseEvent) -> None:
        if (
            self.toggle_virtual_hand_interface_push_button.isChecked()
            and not self.use_external_virtual_hand_interface_check_box.isChecked()
        ):
            self.unity_process.kill()
            self.unity_process.waitForFinished()
