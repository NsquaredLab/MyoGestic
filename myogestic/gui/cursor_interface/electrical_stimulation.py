from __future__ import annotations
from typing import TYPE_CHECKING, Optional

import re
import time
import numpy as np

from PySide6.QtCore import QObject, Signal, QByteArray, QIODevice
from PySide6.QtNetwork import QTcpSocket, QHostAddress
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QGroupBox,
    QPushButton,
    QLabel,
    QLineEdit,
    QMessageBox,
)
from PySide6.QtGui import QCloseEvent

from myogestic.gui.cursor_interface.utils.constants import CURSOR_LABEL2TASK_MAP, CURSOR_TASK2LABEL_MAP
from myogestic.gui.cursor_interface.utils.helper_functions import convert_cursor2stimulation

if TYPE_CHECKING:
    from myogestic.gui.cursor_interface.main_cursor import MyoGestic_Cursor


class ElectricalStimulationControl(QObject):
    """Control class for electrical stimulation that interfaces with the main cursor window.

    This class is a QObject that maintains a reference to the main window (MyoGestic_Cursor)
    to access its UI elements and parameters. It handles the electrical stimulation control
    logic while the main window handles the display and user interface.
    """

    output_message_signal = Signal(QByteArray)  # use to trigger message writing via the opened TCP port

    def __init__(self, main_window: Optional['MyoGestic_Cursor'] = None) -> None:
        """Initialize the electrical stimulation control.

        Args:
            main_window: Reference to the main cursor window instance. This is required
                        to access UI elements and parameters.

        Raises:
            ValueError: If main_window is None or not an instance of MyoGestic_Cursor
        """
        # Set the Qt parent to None since we're managing our own reference to main_window
        super().__init__(None)

        if main_window is None:
            raise ValueError("main_window must be provided to ElectricalStimulationControl")

        # Store reference to main window
        self.main_window: 'MyoGestic_Cursor' = main_window

        # Validate that we have access to required UI elements
        if not hasattr(self.main_window, 'ui'):
            raise ValueError("main_window must have a 'ui' attribute")

        # Check if connection to the server has been made via the defined user
        self.is_connected: bool = False

        # Check if data streaming has started
        self.is_streaming: bool = False

        # Set stimulation parameters
        self.stim_on_time: int = self.main_window.ui.stimOnTimeSpinBox.value()
        self.stim_off_time: int = self.main_window.ui.stimOffTimeSpinBox.value()
        self.stimulation_freq: int = self.main_window.ui.stimFrequencySpinBox.value()

        self.main_window.ui.stimOnTimeSpinBox.valueChanged.connect(self._update_stim_time_freq_parameters)
        self.main_window.ui.stimOffTimeSpinBox.valueChanged.connect(self._update_stim_time_freq_parameters)
        self.main_window.ui.stimFrequencySpinBox.valueChanged.connect(self._update_stim_time_freq_parameters)

        # Store TCP communication parameters with external device
        self.external_data_streaming_group_box: QGroupBox = self.main_window.ui.stimStreamGroupBox
        self.stim_pulse_params_group_box: QGroupBox = self.main_window.ui.stimPulseParamsGroupBox
        self.external_device_IP = self.main_window.ui.externalDeviceIPLineEdit
        self.external_device_port = self.main_window.ui.externalDevicePortLineEdit

        self.external_device_connect_push_button: QPushButton = self.main_window.ui.externalDeviceConnectPushButton
        self.external_device_configure_push_button: QPushButton = self.main_window.ui.externalDeviceConfigurePushButton
        self.external_device_stream_push_button: QPushButton = self.main_window.ui.externalDeviceStreamPushButton

        self.external_device_connect_push_button.toggled.connect(self._toggle_connection)
        self.external_device_configure_push_button.toggled.connect(self._configure_connection)
        self.external_device_stream_push_button.toggled.connect(self._toggle_streaming)

        # Connect cursor prediction to streamed message for stimulator
        self.main_window.vispy_widget.signal_handler.send_interpolated_prediction.connect(self._prepare_output_message)

        # Initialize TCP Socket
        self._setup_external_streaming_interface()

    def _prepare_output_message(self, pred_cursor_x: float, pred_cursor_y: float):
        """Handles message which shall be streamed to the external stimulator device.

        Args:
            pred_cursor_x (float): Predicted x-axis cursor position.
            pred_cursor_y (float): Predicted y-axis cursor position.

        Returns:
            list: A list containing the stimulation parameters:
                - stim_proportional (bool): Whether the stimulation shall be proportional to stimulation level or ON/OFF
                - trigger_stimulation (bool): Whether to trigger stimulation.
                - target_movement (str): The target movement to be stimulated.
                - stimulation_level (float): The stimulation level (0-100%).
                - stim_on_time (int): The time duration for stimulation ON.
                - stim_off_time (int): The time duration for stimulation OFF.
                - stimulation_freq (int): The frequency of stimulation.
        """
        trigger_stimulation = False  # initialized if prediction below threshold

        if self.main_window.ui.externalDeviceStreamPushButton.isChecked():
            # Check which task is selected and which stimulation level is required
            target_movement, target_direction, stimulation_level = convert_cursor2stimulation(
                pred_x_axis=pred_cursor_x,
                pred_y_axis=pred_cursor_y,
                task_up=self.main_window.up_movement_combobox.currentText(),
                task_down=self.main_window.down_movement_combobox.currentText(),
                task_right=self.main_window.right_movement_combobox.currentText(),
                task_left=self.main_window.left_movement_combobox.currentText(),
            )

            # Check if stimulation should be triggered
            if self.main_window.stim_proportional:
                trigger_stimulation = True
            else:  # Check if cursor above threshold for current task
                if target_direction == "Up":
                    trigger_stimulation = (
                        True if abs(pred_cursor_y) >= self.main_window.cursor_up_stim_threshold.value() / 100 else False
                    )
                elif target_direction == "Down":
                    trigger_stimulation = (
                        True
                        if abs(pred_cursor_y) >= self.main_window.cursor_down_stim_threshold.value() / 100
                        else False
                    )
                elif target_direction == "Right":
                    trigger_stimulation = (
                        True
                        if abs(pred_cursor_x) >= self.main_window.cursor_right_stim_threshold.value() / 100
                        else False
                    )
                elif target_direction == "Left":
                    trigger_stimulation = (
                        True
                        if abs(pred_cursor_x) >= self.main_window.cursor_left_stim_threshold.value() / 100
                        else False
                    )
                else:
                    trigger_stimulation = False

            self.main_window.logger.print(f"{stimulation_level}")

            output_message = np.array(
                [
                    int(self.main_window.stim_proportional),
                    int(trigger_stimulation),
                    CURSOR_TASK2LABEL_MAP[target_movement],
                    stimulation_level,
                    self.stim_on_time,
                    self.stim_off_time,
                    self.stimulation_freq,
                ],
                dtype=np.int32,
            )

            self.main_window.logger.print(f"Output message: {output_message}")
            # self.output_message_signal.emit(str(output_message).encode("utf-8"))
            self.output_message_signal.emit(output_message.tobytes())

    def _update_stim_time_freq_parameters(self):
        """Handles UI updates for the time duration and frequency of stimulation"""
        self.stim_on_time = self.main_window.ui.stimOnTimeSpinBox.value()
        self.stim_off_time = self.main_window.ui.stimOffTimeSpinBox.value()
        self.stimulation_freq = self.main_window.ui.stimFrequencySpinBox.value()

    def _write_message(self, message: QByteArray) -> None:
        if self.is_streaming:
            # self.main_window.logger.print("Stream freq:", 1 / (time.time() - self.last_message_time), "Hz")
            self.last_message_time = time.time()

            # Clear socket before streaming new data
            self.clear_socket()
            output_bytes = self.external_streaming_tcp_socket.write(message)

            if output_bytes == -1:
                print("Error sending message")

                return

    def _toggle_connection(self) -> None:
        """
        Toggle connection on by opening the socket and connecting to the server or disconnect from it and close the
        socket.
        """
        if self.external_device_connect_push_button.isChecked():
            self.external_device_connect_push_button.setText("Disconnect")
            self.external_device_configure_push_button.setEnabled(False)
            self._connect_to_server()

        else:
            self.external_device_connect_push_button.setText("Connect")
            self.external_device_configure_push_button.setEnabled(True)
            self._disconnect_from_server()

    def _configure_connection(self) -> None:
        if self.external_device_configure_push_button.isChecked():
            self.external_streaming_tcp_ip = self.external_device_IP.text()
            self.external_streaming_tcp_port = int(self.external_device_port.text())

            self.external_device_IP.setEnabled(False)
            self.external_device_port.setEnabled(False)

            self.external_device_configure_push_button.setText("Change Configuration")
            print("External data streaming configured")

        else:
            self.main_window.ui.externalDeviceIPLineEdit.setEnabled(True)
            self.main_window.ui.externalDevicePortLineEdit.setEnabled(True)
            self.external_device_configure_push_button.setText("Configure connection")

    def _toggle_streaming(self) -> None:
        """
        Open socket and connect to server when the streaming button is clicked. On a second click, the socket is closed
        and the connection is removed.
        """

        if self.external_device_stream_push_button.isChecked():
            if self.external_device_connect_push_button.isChecked():
                self.is_streaming = True
                self.external_device_stream_push_button.setText("Stop Streaming")
                self.external_device_configure_push_button.setEnabled(False)
                self.external_device_connect_push_button.setEnabled(False)
            else:
                print("Connect first before starting the data stream.")

        else:
            self.is_streaming = False
            self.external_device_stream_push_button.setText("Stream")
            self.external_device_configure_push_button.setEnabled(True)
            self.external_device_connect_push_button.setEnabled(True)

    def _check_and_validate_ip(self, ip_line_edit: QLineEdit, default: str):
        ip = ip_line_edit.text()
        if not self._check_for_valid_ip(ip):
            QMessageBox.warning(self, "Invalid IP", "The IP address you entered is not valid.")
            ip_line_edit.setText(default)

    def _check_and_validate_port(self, port_line_edit: QLineEdit, default: int):
        port = port_line_edit.text()
        if not self._check_for_correct_port(port):
            QMessageBox.warning(self, "Invalid Port", "The port you entered is not valid.")
            port_line_edit.setText(str(default))

    def _check_for_valid_ip(self, ip: str) -> bool:
        """
        Checks if the provided IP is valid.

        Args:
            ip (str): IP to be checked.

        Returns:
            bool: True if IP is valid. False if not.
        """
        ip_pattern = re.compile(
            r"^([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\."
            r"([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\."
            r"([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\."
            r"([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$"
        )

        return bool(ip_pattern.match(ip))

    def _check_for_correct_port(self, port: int) -> bool:
        """
        Checks if the provided port is valid.

        Args:
            port (str): Port to be checked.

        Returns:
            bool: True if port is valid. False if not.
        """
        try:
            port_num = int(port)
            return 0 <= port_num <= 65535
        except ValueError:
            return False

    def _connect_to_server(self) -> None:
        """
        Opens socket and requests a connection to the server.

        self.external_streaming_tcp_socket opens and is connected to the server IP and port.
        Server state is_connected is set to True.
        If connection is unsuccessful, set is_connected to False.
        """

        # Create socket and connect to server
        print(self.external_streaming_tcp_ip, self.external_streaming_tcp_port)
        self.external_streaming_tcp_socket = QTcpSocket(self)
        self.external_streaming_tcp_socket.connectToHost(
            self.external_streaming_tcp_ip, self.external_streaming_tcp_port, QIODevice.ReadWrite
        )

        # Check if connection has been established
        if not self.external_streaming_tcp_socket.waitForConnected(1000):
            self.main_window.logger.print("Connection to device failed.")
            self.is_connected = False

    def _disconnect_from_server(self) -> None:
        """
        Closes connection to the server.

        self.external_streaming_tcp_socket closes and is set to None.
        Server state is_connected is set to False.
        """

        # Check first if socket is connected before disconnecting
        if self.is_connected:
            self.external_streaming_tcp_socket.disconnectFromHost()

        self.external_streaming_tcp_socket.close()
        self.external_streaming_tcp_socket = None
        self.is_connected = False

    def clear_socket(self) -> None:
        """Reads all the bytes from the buffer."""

        self.external_streaming_tcp_socket.readAll()

    def _setup_external_streaming_interface(self):
        """
        Check validity of IP address and port information.
        """
        self.external_streaming_tcp_ip: str = None
        self.external_streaming_tcp_ip_default: str = self.external_device_IP.text()
        self.external_streaming_tcp_port: int = None
        self.external_streaming_tcp_port_default: int = int(self.external_device_port.text())
        self.external_device_IP.editingFinished.connect(
            lambda: self._check_and_validate_ip(self.external_device_IP, self.external_streaming_tcp_ip_default)
        )
        self.external_device_port.editingFinished.connect(
            lambda: self._check_and_validate_port(self.external_device_port, self.external_streaming_tcp_port_default)
        )

        self.output_message_signal.connect(self._write_message)

        self.last_message_time = time.time()

    def closeEvent(self, event: QCloseEvent) -> None:
        return super().closeEvent(event)
