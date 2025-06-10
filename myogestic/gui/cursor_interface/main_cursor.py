"""Main cursor interface module for MyoGestic.

This module implements the main cursor interface window which provides:
- A visual interface for cursor movement and control
- UDP communication for cursor position streaming and prediction
- Real-time cursor movement visualization
- Task-movement mapping configuration
- Activation parameter controls
- FPS monitoring and display

It communicates with external systems via UDP sockets for:
- Streaming reference cursor positions to external systems
- Receiving predicted cursor positions from ML models
- Status checks and responses for system synchronization

Constants:
    SOCKET_IP (str): Default IP address for socket communication (127.0.0.1)
    VCI_STREAM_PRED__UDP_PORT (int): Port for streaming predicted cursor coordinates to VCI
    VCI_READ_STATUS__UDP_PORT (int): Port for receiving status checks from VCI
    VCI_READ_PRED__UDP_PORT (int): Port for receiving predicted cursor coordinates from VCI
    STATUS_REQUEST (str): Message for status check requests
    STATUS_RESPONSE (str): Message for status check responses
"""

import sys
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
)
import qdarkstyle
from PySide6.QtNetwork import QUdpSocket, QHostAddress
from PySide6.QtGui import QCloseEvent
import math
import numpy as np
from PySide6.QtCore import Signal
import ast

from myogestic.utils.constants import MYOGESTIC_UDP_PORT

# Import the cursor-specific constant for logging
from myogestic.gui.cursor_interface.utils.constants import (
    DIRECTIONS,
    CURSOR_TASK2LABEL_MAP,
)

# Define constants locally (Ideally move these to a shared constants file)
SOCKET_IP = "127.0.0.1"
VCI_STREAM_PRED__UDP_PORT = 1234  # on this port the cursor sends the interpolated cursor coordinates to the VCI
VCI_READ_STATUS__UDP_PORT = 1235  # on this port the cursor received the status check to which it responds as active
VCI_READ_PRED__UDP_PORT = 1236  # on this port the cursor receives the predicted cursor coordinates from the VCI
STATUS_REQUEST = "status"
STATUS_RESPONSE = "active"

# Import necessary components for trajectory calculation
from myogestic.gui.cursor_interface.utils.helper_functions import generate_sinusoid_trajectory

from myogestic.gui.widgets.logger import CustomLogger, LoggerLevel
from myogestic.gui.cursor_interface.ui.virtual_cursor_window import Ui_CursorInterface
from myogestic.gui.cursor_interface.setup_cursor import VispyWidget


class MyoGestic_Cursor(QMainWindow):
    """Main window for the Virtual Cursor Interface."""

    outgoing_prediction_signal = Signal(list)  # Signal for outgoing predicted cursor data
    window_closed = Signal()  # Signal emitted when window is closed
    is_connected = False  # Class variable to track connection status

    # Add FPS tracking lists
    _ref_cursor_fps_history = []  # Store last 5 reference cursor FPS values
    _pred_cursor_fps_history = []  # Store last 5 predicted cursor FPS values
    _FPS_WINDOW_SIZE = 5  # Number of values to average

    def __init__(self):
        super().__init__()

        # Initialize FPS history lists
        self._ref_cursor_fps_history = []
        self._pred_cursor_fps_history = []

        # Load the UI from the compiled Python file
        self.ui = Ui_CursorInterface()
        self.ui.setupUi(self)

        # Initialize logger first to catch potential errors
        self.logger: CustomLogger = CustomLogger(self.ui.loggingTextEdit)
        self.logger.print("Cursor interface started")

        # UDP Sockets
        self._reference_cursor_stream_socket = QUdpSocket(self)
        self._predicted_status_read_socket = QUdpSocket(self)
        self._predicted_cursor_stream_socket = QUdpSocket(self)
        self._predicted_cursor_read_socket = QUdpSocket(self)

        # Store start/stop streaming button
        self.streaming_push_button: QPushButton = self.ui.streamingPushButton
        if self.streaming_push_button:
            self.streaming_push_button.setCheckable(True)
            self.streaming_push_button.setText("Start Streaming")
            self.streaming_push_button.clicked.connect(self._on_streaming_button_clicked)

        # Store reference to the movement and cursor direction
        self.up_movement_combobox: QComboBox = self.ui.upMovementComboBox
        self.down_movement_combobox: QComboBox = self.ui.downMovementComboBox
        self.right_movement_combobox: QComboBox = self.ui.rightMovementComboBox
        self.left_movement_combobox: QComboBox = self.ui.leftMovementComboBox
        self.update_movement_task_map_push_button: QPushButton = self.ui.updateMovementTaskMapPushButton

        # Store frequencies for the cursor movement and the refresh rate of the reference and predicted cursors
        self.cursor_frequency_double_spin_box: QDoubleSpinBox = self.ui.cursorFrequencyDoubleSpinBox
        self.reference_cursor_refresh_rate_spin_box: QSpinBox = self.ui.referenceCursorRefreshRateSpinBox

        # Store reference activation levels and durations for cursor states
        self.middle_upper_activation_level_spin_box: QSpinBox = self.ui.middleUpperActivationLevelSpinBox
        self.cursor_stop_condition_combo_box: QComboBox = self.ui.cursorStopConditionComboBox

        self.rest_duration_double_spin_box: QDoubleSpinBox = self.ui.restDurationDoubleSpinBox
        self.hold_duration_double_spin_box: QDoubleSpinBox = self.ui.holdDurationDoubleSpinBox
        self.middle_duration_double_spin_box: QDoubleSpinBox = self.ui.middleDurationDoubleSpinBox

        # Store target box parameters
        self.targetBoxGroupBox: QGroupBox = self.ui.targetBoxGroupBox
        self.lowerTargetRangeLevelSpinBox: QSpinBox = self.ui.lowerTargetRangeLevelSpinBox
        self.upperTargetRangeLevelSpinBox: QSpinBox = self.ui.upperTargetRangeLevelSpinBox

        # Store predicted cursor parameters
        self.smoothening_factor_spin_box: QSpinBox = self.ui.smootheningFactorSpinBox
        self.predicted_cursor_stream_rate_spin_box: QSpinBox = (
            self.ui.predictedCursorStreamRateSpinBox
        )
        self.predicted_cursor_freq_div_factor_spin_box: QSpinBox = self.ui.predictedCursorFreqDivFactorSpinBox

        # Store FPS indicators
        self.ref_cursor_fps_label: QLabel = self.ui.refCursorUpdateFPSLabel
        self.pred_cursor_fps_label: QLabel = self.ui.predCursorUpdateFPSLabel

        # Set the initial selected movement for each direction
        self._selected_up_movement = self.up_movement_combobox.currentText() if self.up_movement_combobox else None
        self._selected_down_movement = (
            self.down_movement_combobox.currentText() if self.down_movement_combobox else None
        )
        self._selected_right_movement = (
            self.right_movement_combobox.currentText() if self.right_movement_combobox else None
        )
        self._selected_left_movement = (
            self.left_movement_combobox.currentText() if self.left_movement_combobox else None
        )
        self.logger.print(
            f"Initial movements: Up='{self._selected_up_movement}', "
            f"Down='{self._selected_down_movement}', "
            f"Left='{self._selected_left_movement}', "
            f"Right='{self._selected_right_movement}'"
        )

        self.update_movement_task_map_push_button.clicked.connect(self._on_movement_map_changed)

        self.up_movement_combobox.currentTextChanged.connect(self._on_movement_map_text_changed)
        self.down_movement_combobox.currentTextChanged.connect(self._on_movement_map_text_changed)
        self.right_movement_combobox.currentTextChanged.connect(self._on_movement_map_text_changed)
        self.left_movement_combobox.currentTextChanged.connect(self._on_movement_map_text_changed)

        # Connect cursor frequency and sampling rate value changes to handler methods
        if self.cursor_frequency_double_spin_box:
            self.cursor_frequency_double_spin_box.valueChanged.connect(self._update_vispy_timing_params)
        if self.reference_cursor_refresh_rate_spin_box:
            self.reference_cursor_refresh_rate_spin_box.valueChanged.connect(self._on_cursor_rate_changed)

        # Connect value changes for hold parameters
        if self.rest_duration_double_spin_box:
            self.rest_duration_double_spin_box.valueChanged.connect(self._on_activation_params_changed)
        if self.hold_duration_double_spin_box:
            self.hold_duration_double_spin_box.valueChanged.connect(self._on_activation_params_changed)
        # Connect middle activation/duration widgets
        if self.middle_upper_activation_level_spin_box:
            self.middle_upper_activation_level_spin_box.valueChanged.connect(self._on_activation_params_changed)
        if self.middle_duration_double_spin_box:
            self.middle_duration_double_spin_box.valueChanged.connect(self._on_activation_params_changed)
        # Connect cursor stop condition
        if self.cursor_stop_condition_combo_box:  # Assuming self.cursor_stop_condition_combo_box is already initialized
            self.cursor_stop_condition_combo_box.currentTextChanged.connect(self._on_activation_params_changed)

        # Connect smoothening factor
        if self.smoothening_factor_spin_box:
            self.smoothening_factor_spin_box.valueChanged.connect(self._on_smoothening_factor_changed)

        # Connect predicted cursor frequency division factor
        if self.predicted_cursor_freq_div_factor_spin_box:
            self.predicted_cursor_freq_div_factor_spin_box.valueChanged.connect(self._on_freq_div_factor_changed)

        if self.predicted_cursor_stream_rate_spin_box:
            self.predicted_cursor_stream_rate_spin_box.valueChanged.connect(self._on_pred_freq_changed)

        # Connect target box related widgets to the activation params handler
        if self.targetBoxGroupBox:
            self.targetBoxGroupBox.toggled.connect(self._on_activation_params_changed)
        if self.lowerTargetRangeLevelSpinBox:
            self.lowerTargetRangeLevelSpinBox.valueChanged.connect(self._on_activation_params_changed)
        if self.upperTargetRangeLevelSpinBox:
            self.upperTargetRangeLevelSpinBox.valueChanged.connect(self._on_activation_params_changed)

        # Setup Vispy Widget Display
        # Gather initial mappings first
        initial_mappings = {
            "Up": self._selected_up_movement,
            "Down": self._selected_down_movement,
            "Left": self._selected_left_movement,
            "Right": self._selected_right_movement,
        }
        self._setup_vispy_display(initial_mappings)

        # Connect FPS update signals - connect to the signal handler's signals
        if hasattr(self, 'vispy_widget') and self.vispy_widget:
            # Connect using the signal handler's signals
            self.vispy_widget.signal_handler.ref_cursor_fps_updated.connect(self._update_ref_cursor_fps_label)
            self.vispy_widget.signal_handler.pred_cursor_fps_updated.connect(self._update_pred_cursor_fps_label)
            # Initialize labels with 0 Hz
            self._update_ref_cursor_fps_label(0.0)
            self._update_pred_cursor_fps_label(0.0)

        # Bind the predicted cursor read socket (incoming for status requests and predictions)
        status_read_bound = self._predicted_status_read_socket.bind(QHostAddress(SOCKET_IP), VCI_READ_STATUS__UDP_PORT)
        if status_read_bound:
            self.logger.print(f"Listening for status requests on UDP {SOCKET_IP}:{VCI_READ_STATUS__UDP_PORT}")
            self._predicted_status_read_socket.readyRead.connect(self._process_received_status_datagrams)
        else:
            self.logger.print(
                f"Error: Could not bind to UDP {SOCKET_IP}:{VCI_READ_STATUS__UDP_PORT} for reading", level="ERROR"
            )
            self.logger.print(f"Socket Error: {self._predicted_status_read_socket.errorString()}", level="ERROR")

        predicted_read_bound = self._predicted_cursor_read_socket.bind(QHostAddress(SOCKET_IP), VCI_READ_PRED__UDP_PORT)
        if predicted_read_bound:
            self.logger.print(f"Listening for predictions on UDP {SOCKET_IP}:{VCI_READ_PRED__UDP_PORT}")
            self._predicted_cursor_read_socket.readyRead.connect(
                self._process_received_prediction_datagrams
            )  # Changed to new single handler
        else:
            self.logger.print(
                f"Error: Could not bind to UDP {SOCKET_IP}:{VCI_READ_PRED__UDP_PORT} for reading", level="ERROR"
            )
            self.logger.print(f"Socket Error: {self._predicted_cursor_read_socket.errorString()}", level="ERROR")

        self.outgoing_prediction_signal.connect(self._send_predicted_cursor_datagram)

        self.setWindowTitle("MyoGestic Virtual Cursor")

        # Pass initial timing parameters to VispyWidget
        self._update_vispy_timing_params()

        # Pass initial hold parameters to VispyWidget
        self._update_vispy_activation_params()

        # Pre-calculate initial trajectories
        self._recalculate_trajectories()

    def _setup_vispy_display(self, initial_mappings):
        """Create and embed the VispyWidget into the UI."""
        # Check if the target widget exists in the UI
        if not hasattr(self.ui, 'CursorDisplayWidget'):
            self.logger.print(
                "Error: UI is missing 'CursorDisplayWidget'. Cannot display Vispy content.", level="ERROR"
            )
            return

        # Get the placeholder widget from the UI
        placeholder_widget: QWidget = self.ui.CursorDisplayWidget

        # Create the Vispy widget instance, passing initial mappings
        self.vispy_widget = VispyWidget(initial_mappings=initial_mappings)

        # Create a layout for the placeholder widget
        layout = QVBoxLayout(placeholder_widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Remove margins

        # Add the Vispy canvas's native Qt widget to the layout
        layout.addWidget(self.vispy_widget.native)

        # Set the layout on the placeholder widget
        placeholder_widget.setLayout(layout)
        self.logger.print("Vispy display widget setup complete.")

    def _process_received_status_datagrams(self):
        """Handles incoming status check datagrams on VCI_READ_STATUS__UDP_PORT"""
        while self._predicted_status_read_socket.hasPendingDatagrams():
            datagram_size = self._predicted_status_read_socket.pendingDatagramSize()
            datagram, sender_address, sender_port = self._predicted_status_read_socket.readDatagram(datagram_size)

            message_str = ""
            try:
                message_str = datagram.data().decode("utf-8")
            except UnicodeDecodeError:
                self.logger.print(
                    f"Received undecodable UDP data from {sender_address.toString()}:{sender_port}", level="WARNING"
                )
                continue  # Skip this datagram

            if message_str == STATUS_REQUEST:
                self.is_connected = True
                response_data = STATUS_RESPONSE.encode("utf-8")
                # Send response back to the original sender's port (MYOGESTIC_UDP_PORT)
                # Use the socket that received the request to send the reply.
                bytes_written = self._predicted_status_read_socket.writeDatagram(
                    response_data, sender_address, MYOGESTIC_UDP_PORT
                )
                if bytes_written > 0:
                    pass
                else:
                    self.logger.print(
                        f"Error sending STATUS_RESPONSE: {self._predicted_status_read_socket.errorString()}",
                        level="ERROR",
                    )
            else:
                self.is_connected = False  # As per user request
                self.logger.print(
                    f"STATUS_REQUEST received from {sender_address.toString()}:{sender_port} too soon (<1s). "
                    f"is_connected set to False."
                )

    def _process_received_prediction_datagrams(self):
        """Handles all incoming datagrams on VCI_READ_PRED__UDP_PORT (status requests or predictions)."""
        while self._predicted_cursor_read_socket.hasPendingDatagrams():
            datagram_size = self._predicted_cursor_read_socket.pendingDatagramSize()
            datagram, sender_address, sender_port = self._predicted_cursor_read_socket.readDatagram(datagram_size)

            message_str = ""
            try:
                message_str = datagram.data().decode("utf-8")
            except UnicodeDecodeError:
                self.logger.print(
                    f"Received undecodable UDP data from {sender_address.toString()}:{sender_port}", level="WARNING"
                )
                continue  # Skip this datagram

            # If we reach here, the message was not a STATUS_REQUEST.
            if self.is_connected:  # Only process as prediction if connected
                try:
                    coord_list_outer = ast.literal_eval(message_str)
                    if isinstance(coord_list_outer, tuple) and len(coord_list_outer) == 2:

                        x_raw, y_raw = coord_list_outer
                        if isinstance(x_raw, (int, float)) and isinstance(y_raw, (int, float)):
                            pred_x = float(x_raw)
                            pred_y = float(y_raw)

                            if hasattr(self, 'vispy_widget') and self.vispy_widget:
                                self.vispy_widget.update_predicted_cursor(pred_x, pred_y)

                                if self.vispy_widget.pred_is_read:
                                    self.outgoing_prediction_signal.emit(
                                        (self.vispy_widget.last_predicted_x, self.vispy_widget.last_predicted_y)
                                    )
                        else:
                            self.logger.print(
                                f"Invalid coordinate types in predicted data message: '{message_str}'", level="WARNING"
                            )
                    else:
                        self.logger.print(f"Invalid predicted cursor data format: '{message_str}'", level="WARNING")
                except (SyntaxError, ValueError) as e:
                    self.logger.print(f"Error parsing presumed prediction data '{message_str}': {e}", level="ERROR")
                except Exception as e:
                    self.logger.print(f"Error processing presumed prediction UDP datagram: {e}", level="ERROR")
            else:  # Not connected and not a STATUS_REQUEST
                self.logger.print(
                    f"Not connected. Discarding unexpected non-status message '{message_str}' from "
                    f"{sender_address.toString()}:{sender_port}."
                )

    def closeEvent(self, event: QCloseEvent) -> None:
        """Ensure the UDP sockets and timers are closed/stopped when the window closes."""
        self.logger.print("Closing UDP sockets and stopping timers.")

        # Emit signal that window is closing
        self.window_closed.emit()

        if hasattr(self.vispy_widget, 'cursor_timer') and self.vispy_widget.cursor_timer.isActive():
            self.vispy_widget.cursor_timer.stop()

        if hasattr(self, '_reference_cursor_stream_socket'):
            self._reference_cursor_stream_socket.close()
        if hasattr(self, '_predicted_cursor_read_socket'):
            self._predicted_cursor_read_socket.close()
        if hasattr(self, '_predicted_cursor_stream_socket'):
            self._predicted_cursor_stream_socket.close()

        # Accept the event to allow the window to close
        event.accept()

        # Call parent method closeEvent
        super().closeEvent(event)

    # Method to update VispyWidget mappings
    def _update_vispy_mappings(self):
        """Collects current mappings and sends them to VispyWidget."""
        if hasattr(self, 'vispy_widget'):  # Ensure vispy_widget exists
            mappings = {
                "Up": self._selected_up_movement,
                "Down": self._selected_down_movement,
                "Left": self._selected_left_movement,
                "Right": self._selected_right_movement,
            }
            self.vispy_widget.update_movement_mappings(mappings)
        else:
            self.logger.print("Cannot update Vispy mappings: vispy_widget not initialized.", level="WARNING")

    def _recalculate_trajectories(self):
        """Calculates trajectories for all directions based on current signal frequency."""
        if not hasattr(self, 'vispy_widget'):
            self.logger.print("Cannot recalculate trajectories: vispy_widget not initialized.", level="WARNING")
            return

        signal_freq = self.cursor_frequency_double_spin_box.value() if self.cursor_frequency_double_spin_box else 0.1
        if signal_freq <= 0:
            self.logger.print(
                f"Signal frequency ({signal_freq} Hz) must be positive to calculate trajectories.", level="WARNING"
            )
            # Optionally clear existing trajectories or handle as needed
            self.vispy_widget.set_trajectories({})  # Clear trajectories in VispyWidget
            return

        self.logger.print(
            f"Recalculating trajectories for signal freq.: {signal_freq:.2f} Hz using sampling rate: "
            f"{self.vispy_widget.cursor_sampling_rate} Hz"
        )
        trajectories = {}
        # Calculate for movement directions only (exclude "Rest")
        for direction in DIRECTIONS:
            if direction != "Rest":
                trajectories[direction] = generate_sinusoid_trajectory(
                    signal_frequency=signal_freq,
                    direction=direction,
                    sampling_rate=self.vispy_widget.cursor_sampling_rate,
                    # Amplitude defaults to 1.0 in helper
                )

        # Pass the calculated trajectories to the VispyWidget
        self.vispy_widget.set_trajectories(trajectories)

    # Method to update VispyWidget timing parameters
    def _update_vispy_timing_params(self):
        """Collects current timing parameters and sends them to VispyWidget."""
        if hasattr(self, 'vispy_widget'):  # Ensure vispy_widget exists
            signal_freq = (
                self.cursor_frequency_double_spin_box.value() if self.cursor_frequency_double_spin_box else 0.1
            )

            # Check if signal frequency changed, if so, recalculate trajectories
            current_vispy_signal_freq = getattr(self.vispy_widget, '_signal_frequency', None)
            if current_vispy_signal_freq is None or not math.isclose(signal_freq, current_vispy_signal_freq):
                self._recalculate_trajectories()  # Recalculate before updating VispyWidget

    # Method to update VispyWidget hold parameters
    def _update_vispy_activation_params(self):
        """Collects current activation parameters (rest, hold, middle) and sends them to VispyWidget."""
        if hasattr(self, 'vispy_widget'):  # Ensure vispy_widget exists
            # Rest: Fixed threshold 0%, read duration
            rest_threshold_percent = 0
            rest_duration_s = self.rest_duration_double_spin_box.value() if self.rest_duration_double_spin_box else 0.0

            # Peak (Hold): Fixed threshold 100%, read duration
            peak_duration_s = self.hold_duration_double_spin_box.value() if self.hold_duration_double_spin_box else 0.0

            # Middle: Read threshold and duration
            middle_threshold_percent = (
                self.middle_upper_activation_level_spin_box.value()
                if self.middle_upper_activation_level_spin_box
                else 0
            )
            middle_duration_s = (
                self.middle_duration_double_spin_box.value() if self.middle_duration_double_spin_box else 0.0
            )
            middle_stop_condition = (
                self.cursor_stop_condition_combo_box.currentText()
                if self.cursor_stop_condition_combo_box
                else "Both directions"
            )

            # Target Box parameters
            target_box_visible = self.targetBoxGroupBox.isChecked() if self.targetBoxGroupBox else False
            target_box_lower_percent = (
                self.lowerTargetRangeLevelSpinBox.value() if self.lowerTargetRangeLevelSpinBox else 0
            )
            target_box_upper_percent = (
                self.upperTargetRangeLevelSpinBox.value() if self.upperTargetRangeLevelSpinBox else 0
            )

            self.vispy_widget.update_activation_parameters(
                rest_duration_s,
                peak_duration_s,
                middle_threshold_percent,
                middle_duration_s,
                middle_stop_condition,
                target_box_visible,
                target_box_lower_percent,
                target_box_upper_percent,
            )
        else:
            self.logger.print("Cannot update Vispy activation params: vispy_widget not initialized.",
                              level="WARNING")

    # Signal Handlers (Slots)
    def _on_movement_map_changed(self, text: str):
        self._selected_up_movement = self.up_movement_combobox.currentText()
        self._selected_down_movement = self.down_movement_combobox.currentText()
        self._selected_right_movement = self.right_movement_combobox.currentText()
        self._selected_left_movement = self.left_movement_combobox.currentText()
        self.logger.print(
            f"Task-movement mappings updated: Up-{self._selected_up_movement}, Down-{self._selected_down_movement}, "
            f"Right-{self._selected_right_movement}, Left-{self._selected_left_movement}"
        )
        self._update_vispy_mappings()  # Update display

    def _on_movement_map_text_changed(self):
        self.logger.print("Check if task-movement mapping here matches mapping from loaded model",
                          LoggerLevel.WARNING)

    # Update cursor sampling frequency
    def _on_cursor_rate_changed(self):
        """Handles changes to cursor refresh rate frequency."""
        self.vispy_widget.cursor_sampling_rate = int(self.reference_cursor_refresh_rate_spin_box.value())

        if self.vispy_widget.cursor_timer.isActive():
            self.vispy_widget.cursor_timer.stop()

        self.vispy_widget.cursor_timer.setInterval(int(1000 / self.vispy_widget.cursor_sampling_rate))
        self.vispy_widget.cursor_timer.start()
        self.logger.print(
            f"Check that cursor sampling frequency matches kinematics sampling frequency set in MyoGestic for the "
            f"recording.",
            level=LoggerLevel.WARNING
        )
        self._update_vispy_timing_params()

    # Slot for hold parameter changes
    def _on_activation_params_changed(self):
        """Handles changes in any activation threshold or duration."""
        self._update_vispy_activation_params()

    def _on_smoothening_factor_changed(self):
        """Handles changes in the smoothening factor values."""
        if hasattr(self, 'vispy_widget') and self.vispy_widget:
            factor = self.smoothening_factor_spin_box.value()
            self.vispy_widget.update_smoothening_factor(factor)

    def _on_freq_div_factor_changed(self):
        """Handles changes in the predicted cursor frequency division factor value."""
        if hasattr(self, 'vispy_widget') and self.vispy_widget:
            self.vispy_widget.update_freq_div_factor(self.predicted_cursor_freq_div_factor_spin_box.value())
            current_pred_freq = (
                self.predicted_cursor_stream_rate_spin_box.value()
                / self.predicted_cursor_freq_div_factor_spin_box.value()
            )
            self.logger.print(f"Current prediction refresh rate: {current_pred_freq} Hz")

    def _on_pred_freq_changed(self):
        """Handles changes in the predicted cursor frequency value."""
        if hasattr(self, 'vispy_widget') and self.vispy_widget:
            self.vispy_widget.update_pred_freq(self.predicted_cursor_stream_rate_spin_box.value())
            current_pred_freq = (
                self.predicted_cursor_stream_rate_spin_box.value()
                / self.predicted_cursor_freq_div_factor_spin_box.value()
            )
            self.logger.print(f"Current prediction refresh rate: {current_pred_freq} Hz")
            self.logger.print("Ensure prediction refresh rate does not exceed device refresh rate", LoggerLevel.WARNING)

    def _on_streaming_button_clicked(self):
        """Handles the streaming push button click to toggle data streaming."""
        if not self.streaming_push_button:  # Should not happen if UI is set up
            return

        if self.streaming_push_button.isChecked():
            self._start_cursor_streaming()
            self.streaming_push_button.setText("Stop Reference Streaming")
        else:
            self._stop_cursor_streaming()
            self.streaming_push_button.setText("Start Reference Streaming")

    # --- Cursor Data Streaming Methods ---
    def _start_cursor_streaming(self):
        """Starts the timer for streaming cursor position data."""
        self.logger.print(f"Starting cursor position streaming at {self.vispy_widget.cursor_sampling_rate} Hz.")
        self.vispy_widget.cursor_timer.timeout.connect(self._send_cursor_position_datagram)

    def _stop_cursor_streaming(self):
        """Stops the timer for streaming cursor position data."""
        self.logger.print("Stopping cursor position streaming.")
        self.vispy_widget.cursor_timer.timeout.disconnect(self._send_cursor_position_datagram)

    def _send_cursor_position_datagram(self):
        """Sends the current reference cursor position and task label via UDP."""
        if hasattr(self, 'vispy_widget') and self.vispy_widget:
            try:
                current_pos_xy = self.vispy_widget.get_reference_cursor_position()  # (x, y) tuple
                current_direction_string = self.vispy_widget.get_current_direction_string()
                task_label = "Inactive"

                if self.vispy_widget.movement_active:
                    task_label = current_direction_string

                if current_pos_xy is not None and task_label is not None:
                    pos_array_to_send = np.array(
                        [
                            [current_pos_xy[0]],  # x-coordinate scaled
                            [current_pos_xy[1]],  # y-coordinate scaled
                            [CURSOR_TASK2LABEL_MAP[task_label]],
                        ],
                        dtype=np.float32,
                    ).T

                    # Construct the data string: "[[x, y]]_TaskLabel"
                    data_string = f"{pos_array_to_send.tolist()}"
                    byte_data = data_string.encode("utf-8")

                    self._reference_cursor_stream_socket.writeDatagram(
                        byte_data, QHostAddress(SOCKET_IP), MYOGESTIC_UDP_PORT
                    )

            except Exception as e:
                self.logger.print(f"Error sending cursor position datagram: {e}", level="ERROR")

    def _send_predicted_cursor_datagram(self, prediction_data_list: list):
        """Sends the predicted cursor data (received from VCI) via UDP."""
        try:
            # Check if the prediction data is a list of two elements (x, y)
            # Convert the list to its string representation for sending
            data_string = str(prediction_data_list)
            byte_data = data_string.encode("utf-8")

            # Send to VCI_STREAM_PRED__UDP_PORT on SOCKET_IP
            # (self._predicted_cursor_stream_socket is bound to this port as its source)
            bytes_sent = self._predicted_cursor_stream_socket.writeDatagram(
                byte_data, QHostAddress(SOCKET_IP), VCI_STREAM_PRED__UDP_PORT
            )
        except Exception as e:
            self.logger.print(f"Error in _send_predicted_cursor_datagram: {e}", level="ERROR")

    def _update_ref_cursor_fps_label(self, fps: float):
        """Updates the reference cursor FPS label with averaged value."""
        if self.ref_cursor_fps_label:
            # Add new FPS value to history
            self._ref_cursor_fps_history.append(fps)
            # Keep only last 5 values
            if len(self._ref_cursor_fps_history) > self._FPS_WINDOW_SIZE:
                self._ref_cursor_fps_history.pop(0)
            # Calculate average
            avg_fps = sum(self._ref_cursor_fps_history) / len(self._ref_cursor_fps_history)
            # Update label with averaged value
            self.ref_cursor_fps_label.setText(f"{avg_fps:.1f}")

    def _update_pred_cursor_fps_label(self, fps: float):
        """Updates the predicted cursor FPS label with averaged value."""
        if self.pred_cursor_fps_label:
            # Add new FPS value to history
            self._pred_cursor_fps_history.append(fps)
            # Keep only last 5 values
            if len(self._pred_cursor_fps_history) > self._FPS_WINDOW_SIZE:
                self._pred_cursor_fps_history.pop(0)
            # Calculate average
            avg_fps = sum(self._pred_cursor_fps_history) / len(self._pred_cursor_fps_history)
            # Update label with averaged value
            self.pred_cursor_fps_label.setText(f"{avg_fps:.1f}")


def main():
    """Main function to run the MyoGestic Virtual Cursor application."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyside6"))

    main_window = MyoGestic_Cursor()
    main_window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
