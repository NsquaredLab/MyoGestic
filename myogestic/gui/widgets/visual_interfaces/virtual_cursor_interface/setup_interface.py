import ast
import sys
import time
from pathlib import Path
import os

import numpy as np
from PySide6.QtCore import QByteArray, QMetaObject, QProcess, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtNetwork import QHostAddress, QUdpSocket
from PySide6.QtWidgets import QCheckBox, QPushButton, QWidget, QApplication

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.visual_interface import SetupInterfaceTemplate
from myogestic.gui.widgets.visual_interfaces.virtual_cursor_interface.ui import Ui_SetupVirtualCursorInterface
from myogestic.utils.constants import MYOGESTIC_UDP_PORT

# Stylesheets
NOT_CONNECTED_STYLESHEET = "background-color: red; border-radius: 5px;"
CONNECTED_STYLESHEET = "background-color: green; border-radius: 5px;"

# Constants
STREAMING_FREQUENCY = 60
TIME_BETWEEN_MESSAGES = 1 / STREAMING_FREQUENCY

SOCKET_IP = "127.0.0.1"
STATUS_REQUEST = "status"
STATUS_RESPONSE = "active"


# Ports
# on this port the VCI listens for incoming messages from MyoGestic
VCI__UDP_PORT = 1236

# on this port the VCI sends the status check
VCI_STATUS__UDP_PORT = 1235

# on this port the VCI sends the currently displayed predicted cursor
VCI_PREDICTION__UDP_PORT = 1234


class VirtualCursorInterface_SetupInterface(SetupInterfaceTemplate):
    """
    Setup interface for the Virtual Cursor Interface.

    This class is responsible for setting up the Virtual Cursor Interface.

    Attributes
    ----------
    predicted_cursor__signal : Signal
        Signal that emits the predicted cursor data.
    incoming_message_signal : Signal
        Signal that emits both an array and a string.

    Parameters
    ----------
    main_window : QMainWindow
        The main window of the application.
    name : str
        The name of the interface. Default is "VirtualCursorInterface".

        .. important:: The name of the interface must be unique.
    """

    predicted_cursor__signal = Signal(np.ndarray)
    incoming_message_signal = Signal(np.ndarray)

    def __init__(self, main_window, name="VirtualCursorInterface"):
        super().__init__(main_window, name, ui=Ui_SetupVirtualCursorInterface())

        self._cursor_process = QProcess()
        self._cursor_process.setProgram(sys.executable)
        self._cursor_process.setArguments([self._get_cursor_py_executable()])
        self._cursor_process.started.connect(lambda: self._main_window.toggle_selected_visual_interface(self.name))
        self._cursor_process.finished.connect(self.interface_was_killed)
        self._cursor_process.finished.connect(lambda: self._main_window.toggle_selected_visual_interface(self.name))

        self._setup_timers()

        self._last_message_time = time.time()
        self._is_connected: bool = False
        self._streaming__udp_socket: QUdpSocket | None = None

        # Custom Stuff
        self._predicted_cursor__udp_socket: QUdpSocket | None = None
        self._predicted_cursor_recording__buffer: list[(float, np.ndarray)] = []

        # Initialize Virtual Cursor Interface UI
        self.initialize_ui_logic()

    def _get_cursor_py_executable(self) -> str:
        """Get the path to the Python main script for the cursor application."""
        python_executable = sys.executable
        script_dir = os.path.dirname(__file__)
        base_gui_path = os.path.abspath(os.path.join(script_dir, "..", "..", ".."))
        main_cursor_path = os.path.join(base_gui_path, "cursor_interface", "main_cursor.py")

        return main_cursor_path

    def _setup_timers(self):
        """Setup the timers for the Virtual Cursor Interface."""
        self._status_request__timer = QTimer(self)
        self._status_request__timer.setInterval(2000)
        self._status_request__timer.timeout.connect(self.write_status_message)

        self._status_request_timeout__timer = QTimer(self)
        self._status_request_timeout__timer.setSingleShot(True)
        self._status_request_timeout__timer.setInterval(1000)
        self._status_request_timeout__timer.timeout.connect(self._update_status)

    def initialize_ui_logic(self):
        """Initialize the UI logic for the Virtual Cursor Interface."""
        self._main_window.ui.visualInterfacesVerticalLayout.addWidget(self.ui.groupBox)

        self._toggle_virtual_cursor_interface__push_button: QPushButton = self.ui.toggleVirtualCursorInterfacePushButton
        self._toggle_virtual_cursor_interface__push_button.clicked.connect(self.toggle_virtual_cursor_interface)
        self._virtual_cursor_interface__status_widget: QWidget = self.ui.virtualCursorInterfaceStatusWidget

        self._virtual_cursor_interface__status_widget.setStyleSheet(NOT_CONNECTED_STYLESHEET)

        self._use_external_virtual_cursor_interface__check_box: QCheckBox = (
            self.ui.useExternalVirtualCursorInterfaceCheckBox
        )

    def start_interface(self):
        """Start the Virtual Cursor Interface."""
        if not self._use_external_virtual_cursor_interface__check_box.isChecked():
            # Connect to process finished signal before starting
            self._cursor_process.finished.connect(self.stop_interface)
            self._cursor_process.start()
            self._cursor_process.waitForStarted()

        self._status_request__timer.start()
        self.toggle_streaming()

    def stop_interface(self):
        """Stop the Virtual Cursor Interface."""
        if not self._use_external_virtual_cursor_interface__check_box.isChecked():
            # Disconnect from process finished signal
            try:
                self._cursor_process.finished.disconnect(self.stop_interface)
            except (TypeError, RuntimeError):
                pass  # Signal was not connected

            if self._cursor_process.state() != QProcess.NotRunning:
                self._cursor_process.kill()
                self._cursor_process.waitForFinished()
        QMetaObject.invokeMethod(self._status_request__timer, "stop", Qt.QueuedConnection)
        self.toggle_streaming()

    def interface_was_killed(self) -> None:
        """Handle the case when the Virtual Cursor Interface was killed or finished."""
        self._toggle_virtual_cursor_interface__push_button.setChecked(False)
        self._toggle_virtual_cursor_interface__push_button.setText("Open")
        self._use_external_virtual_cursor_interface__check_box.setEnabled(True)
        self._virtual_cursor_interface__status_widget.setStyleSheet(NOT_CONNECTED_STYLESHEET)
        self._is_connected = False

    def close_event(self, _: QCloseEvent) -> None:
        """Handle the close event of the Virtual Cursor Interface."""
        try:
            if self._streaming__udp_socket:
                self._streaming__udp_socket.close()
            if self._predicted_cursor__udp_socket:
                self._predicted_cursor__udp_socket.close()
            if self._cursor_process.state() != QProcess.NotRunning:
                self._cursor_process.kill()
                self._cursor_process.waitForFinished()
        except Exception as e:
            self._main_window.logger.print(f"Error during cleanup: {e}", level=LoggerLevel.ERROR)

    def _update_status(self) -> None:
        """Update the status of the Virtual Cursor Interface."""
        self._is_connected = False
        self._virtual_cursor_interface__status_widget.setStyleSheet(NOT_CONNECTED_STYLESHEET)

    def toggle_virtual_cursor_interface(self):
        """Toggle the Virtual Cursor Interface."""
        if self._toggle_virtual_cursor_interface__push_button.isChecked():
            print("Opening Virtual Cursor Interface")
            self.start_interface()
            self._use_external_virtual_cursor_interface__check_box.setEnabled(False)
            self._toggle_virtual_cursor_interface__push_button.setText("Close")
        else:
            print("Closing Virtual Cursor Interface")
            self.stop_interface()
            self._use_external_virtual_cursor_interface__check_box.setEnabled(True)
            self._toggle_virtual_cursor_interface__push_button.setText("Open")

    def toggle_streaming(self) -> None:
        """Toggle the streaming of the Virtual Cursor Interface."""
        if self._toggle_virtual_cursor_interface__push_button.isChecked():
            self._streaming__udp_socket = QUdpSocket(self)
            self._streaming__udp_socket.readyRead.connect(self.read_message)
            self.outgoing_message_signal.connect(self.write_message)
            self._streaming__udp_socket.bind(QHostAddress(SOCKET_IP), MYOGESTIC_UDP_PORT)

            self._predicted_cursor__udp_socket = QUdpSocket(self)
            self._predicted_cursor__udp_socket.bind(QHostAddress(SOCKET_IP), VCI_PREDICTION__UDP_PORT)
            self._predicted_cursor__udp_socket.readyRead.connect(self.read_predicted_cursor)

            self._last_message_time = time.time()
        else:
            try:
                self._streaming__udp_socket.close()
                self._predicted_cursor__udp_socket.close()
            except AttributeError:
                pass
            self._streaming__udp_socket = None
            self._predicted_cursor__udp_socket = None
            self._is_connected = False
            self._virtual_cursor_interface__status_widget.setStyleSheet(NOT_CONNECTED_STYLESHEET)

    def read_predicted_cursor(self) -> None:
        """Read the predicted cursor data from the Virtual Cursor Interface."""
        while self._predicted_cursor__udp_socket.hasPendingDatagrams():
            datagram, _, _ = self._predicted_cursor__udp_socket.readDatagram(
                self._predicted_cursor__udp_socket.pendingDatagramSize()
            )

            data = datagram.data().decode("utf-8")
            if not data:
                return

            self.predicted_cursor__signal.emit(np.array(ast.literal_eval(data)))

    def write_message(self, message: QByteArray) -> None:
        """Write a message to the Virtual Cursor Interface."""
        if self._is_connected and (time.time() - self._last_message_time >= TIME_BETWEEN_MESSAGES):
            self._last_message_time = time.time()
            output_bytes = self._streaming__udp_socket.writeDatagram(message, QHostAddress(SOCKET_IP), VCI__UDP_PORT)

            if output_bytes == -1:
                self._main_window.logger.print(
                    "Error in sending message to Virtual Cursor Interface!",
                    level=LoggerLevel.ERROR,
                )

    def read_message(self) -> None:
        """Read a message from the Virtual Cursor Interface."""
        if self._toggle_virtual_cursor_interface__push_button.isChecked():
            while self._streaming__udp_socket.hasPendingDatagrams():
                datagram, _, _ = self._streaming__udp_socket.readDatagram(
                    self._streaming__udp_socket.pendingDatagramSize()
                )

                try:
                    data_str = datagram.data().decode("utf-8")
                    if not data_str:
                        return

                    if data_str == STATUS_RESPONSE:
                        self._is_connected = True
                        self._virtual_cursor_interface__status_widget.setStyleSheet(CONNECTED_STYLESHEET)
                        self._status_request_timeout__timer.stop()
                        return

                    # Default values
                    task_label = ""
                    coord_data_str = data_str

                    # Check for underscore to separate coordinates and task label
                    if "_" in data_str:
                        parts = data_str.rsplit("_", 1)
                        if len(parts) == 2:
                            coord_data_str = parts[0]
                            task_label = parts[1]

                    try:
                        # Convert the coordinate part to a numpy array
                        coord_array = np.array(ast.literal_eval(coord_data_str))
                        self.incoming_message_signal.emit(coord_array)
                    except (SyntaxError, ValueError) as e:
                        self._main_window.logger.print(
                            f'Error parsing coordinate data "{coord_data_str}" from message "{data_str}": {e}',
                            level=LoggerLevel.WARNING,
                        )

                except UnicodeDecodeError:
                    self._main_window.logger.print(
                        f"Failed to decode UDP message: {datagram.data()[:50]}...", level=LoggerLevel.WARNING
                    )  # Log part of the message
                except Exception as e:  # Catch any other unexpected errors during message processing
                    self._main_window.logger.print(
                        f"Unexpected error processing message in read_message: {e}", level=LoggerLevel.ERROR
                    )

    def write_status_message(self) -> None:
        """Write a status message to the Virtual Cursor Interface."""
        if self._toggle_virtual_cursor_interface__push_button.isChecked():
            output_bytes = self._streaming__udp_socket.writeDatagram(
                STATUS_REQUEST.encode("utf-8"),
                QHostAddress(SOCKET_IP),
                VCI_STATUS__UDP_PORT,
            )

            if output_bytes == -1:
                self._main_window.logger.print(
                    "Error in sending status message to Virtual Cursor Interface!",
                    level=LoggerLevel.ERROR,
                )
                return

            self._status_request_timeout__timer.start()

    def connect_custom_signals(self) -> None:
        """Connect custom signals for the Virtual Cursor Interface."""
        self.predicted_cursor__signal.connect(self.online_predicted_cursor_update)

    def disconnect_custom_signals(self) -> None:
        """Disconnect custom signals for the Virtual Cursor Interface."""
        self.predicted_cursor__signal.disconnect(self.online_predicted_cursor_update)

    def get_custom_save_data(self) -> dict:
        """Get custom save data for the Virtual Cursor Interface."""
        return {
            "predicted_cursor": np.vstack(
                [data for _, data in self._predicted_cursor_recording__buffer],
            ).T,
            "predicted_cursor_timings": np.array(
                [time for time, _ in self._predicted_cursor_recording__buffer],
            ),
        }

    def clear_custom_signal_buffers(self) -> None:
        """Clear custom signal buffers for the Virtual Cursor Interface."""
        self._predicted_cursor_recording__buffer = []

    def online_predicted_cursor_update(self, data: np.ndarray) -> None:
        """Update the predicted cursor data for the online protocol."""
        if self._online_protocol.online_record_toggle_push_button.isChecked():
            self._predicted_cursor_recording__buffer.append(
                (time.time() - self._online_protocol.recording_start_time, data)
            )
