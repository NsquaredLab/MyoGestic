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
    QRadioButton,
)
import qdarkstyle
from PySide6.QtNetwork import QUdpSocket, QHostAddress
from PySide6.QtGui import QCloseEvent
import math
import numpy as np
from PySide6.QtCore import QByteArray
from PySide6.QtCore import QTimer
import ast # For safely evaluating string literals

from myogestic.utils.constants import MYOGESTIC_UDP_PORT

# Import the cursor-specific constant for logging
from myogestic.gui.cursor_interface.utils.constants import CURSOR_SAMPLING_RATE, DIRECTIONS, CURSOR_STREAMING_RATE

# Define constants locally (Ideally move these to a shared constants file)
SOCKET_IP = "127.0.0.1"
VCI__UDP_PORT = 1246  # on this port the VCI listens for and incoming messages from MyoGestic
VCI_PREDICTION__UDP_PORT = 1244  # on this port the VCI receives the predicted cursor data from the VCI
STATUS_REQUEST = "status"
STATUS_RESPONSE = "active"

# Import necessary components for trajectory calculation
from myogestic.gui.cursor_interface.utils.helper_functions import generate_sinusoid_trajectory

from myogestic.gui.widgets.logger import CustomLogger
from myogestic.gui.cursor_interface.ui.virtual_cursor_window import Ui_CursorInterface
from myogestic.gui.cursor_interface.setup_cursor import VispyWidget


class MyoGestic_Cursor(QMainWindow):
    """Main window for the Virtual Cursor Interface."""

    def __init__(self):
        super().__init__()

        # Load the UI from the compiled Python file
        self.ui = Ui_CursorInterface()
        self.ui.setupUi(self)

        # Initialize logger first to catch potential errors
        self.logger: CustomLogger = CustomLogger(self.ui.loggingTextEdit)
        self.logger.print("Cursor interface started!")

        # UDP Socket for listening to status requests
        self._udp_socket = QUdpSocket(self)
        # UDP Socket for streaming cursor data
        self._streaming_socket = QUdpSocket(self)
        # UDP Socket for receiving predicted cursor data
        self._predicted_cursor_socket = QUdpSocket(self)
        # Timer for streaming cursor data
        self._streaming_timer = QTimer(self)

        # Store start/stop streaming button
        self.streaming_push_button: QPushButton = self.ui.streamingPushButton
        if self.streaming_push_button:
            self.streaming_push_button.setCheckable(True)
            self.streaming_push_button.setText("Start Streaming")
            self.streaming_push_button.clicked.connect(self._on_streaming_button_clicked)

        # Store reference to the movement and cursor direction upMovementComboBox
        self.up_movement_combobox: QComboBox = self.ui.upMovementComboBox
        self.down_movement_combobox: QComboBox = self.ui.downMovementComboBox
        self.right_movement_combobox: QComboBox = self.ui.rightMovementComboBox
        self.left_movement_combobox: QComboBox = self.ui.leftMovementComboBox

        # Store frequencies for the cursor movement and the refresh rate of the reference and predicted cursors
        self.cursor_frequency_double_spin_box: QDoubleSpinBox = self.ui.cursorFrequencyDoubleSpinBox
        self.reference_cursor_refresh_rate_combo_box: QComboBox = self.ui.referenceCursorRefreshRateComboBox
        self.predicted_cursor_refresh_rate_spin_box: QSpinBox = self.ui.predictedCursorRefreshRateSpinBox

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

        # Setup the initial selected movement for each direction
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

        # Connect combobox changes to handler methods
        if self.up_movement_combobox:
            self.up_movement_combobox.currentTextChanged.connect(self._on_up_movement_changed)
        if self.down_movement_combobox:
            self.down_movement_combobox.currentTextChanged.connect(self._on_down_movement_changed)
        if self.left_movement_combobox:
            self.left_movement_combobox.currentTextChanged.connect(self._on_left_movement_changed)
        if self.right_movement_combobox:
            self.right_movement_combobox.currentTextChanged.connect(self._on_right_movement_changed)

        # Connect spinbox value changes to handler methods
        if self.cursor_frequency_double_spin_box:
            self.cursor_frequency_double_spin_box.valueChanged.connect(self._on_timing_params_changed)
        if self.reference_cursor_refresh_rate_combo_box:
            self.reference_cursor_refresh_rate_combo_box.currentTextChanged.connect(self._on_timing_params_changed)
        if self.predicted_cursor_refresh_rate_spin_box:
            self.predicted_cursor_refresh_rate_spin_box.valueChanged.connect(self._on_predicted_refresh_rate_changed)

        # Connect spinbox/doublespinbox value changes for hold parameters
        if self.rest_duration_double_spin_box:
            self.rest_duration_double_spin_box.valueChanged.connect(self._on_activation_params_changed)
        if self.hold_duration_double_spin_box:
            self.hold_duration_double_spin_box.valueChanged.connect(self._on_activation_params_changed)
        # Connect middle activation/duration widgets
        if self.middle_upper_activation_level_spin_box:
            self.middle_upper_activation_level_spin_box.valueChanged.connect(self._on_activation_params_changed)
        if self.middle_duration_double_spin_box:
            self.middle_duration_double_spin_box.valueChanged.connect(self._on_activation_params_changed)
        # Connect cursor stop condition combobox
        if self.cursor_stop_condition_combo_box:  # Assuming self.cursor_stop_condition_combo_box is already initialized
            self.cursor_stop_condition_combo_box.currentTextChanged.connect(self._on_activation_params_changed)

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

        # Flag to track if the status response has been logged
        self._status_response_logged = False

        # Listen on the port the setup interface sends status requests to
        bound = self._udp_socket.bind(QHostAddress(SOCKET_IP), VCI__UDP_PORT)
        if bound:
            self.logger.print(f"Listening for status requests on UDP {SOCKET_IP}:{VCI__UDP_PORT}")
            self._udp_socket.readyRead.connect(self._read_datagrams)
        else:
            self.logger.print(f"Error: Could not bind to UDP {SOCKET_IP}:{VCI__UDP_PORT}", level="ERROR")
            self.logger.print(f"Socket Error: {self._udp_socket.errorString()}", level="ERROR")

        # Configure streaming timer
        if CURSOR_STREAMING_RATE > 0:
            self._streaming_timer.setInterval(int(1000 / CURSOR_STREAMING_RATE))
            self._streaming_timer.timeout.connect(self._send_cursor_position_datagram)
        else:
            self.logger.print(f"CURSOR_STREAMING_RATE ({CURSOR_STREAMING_RATE} Hz) is not positive. Streaming disabled.", level="WARNING")

        # Bind the predicted cursor socket and connect its readyRead signal
        predicted_bound = self._predicted_cursor_socket.bind(QHostAddress(SOCKET_IP), VCI_PREDICTION__UDP_PORT)
        if predicted_bound:
            self.logger.print(f"Listening for predicted cursor data on UDP {SOCKET_IP}:{VCI_PREDICTION__UDP_PORT}")
            self._predicted_cursor_socket.readyRead.connect(self._read_predicted_cursor_datagrams)
        else:
            self.logger.print(f"Error: Could not bind to UDP {SOCKET_IP}:{VCI_PREDICTION__UDP_PORT} for predicted data", level="ERROR")
            self.logger.print(f"Socket Error: {self._predicted_cursor_socket.errorString()}", level="ERROR")

        # Example: Accessing a widget (replace 'widgetName' with an actual name from your UI, e.g., self.ui.pushButton)
        # self.ui.pushButton.clicked.connect(self.on_button_click)

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

    def _read_datagrams(self):
        """Read incoming UDP datagrams and respond to status requests."""
        while self._udp_socket.hasPendingDatagrams():
            datagram_size = self._udp_socket.pendingDatagramSize()
            datagram, sender_address, sender_port = self._udp_socket.readDatagram(datagram_size)

            try:
                message = datagram.data().decode("utf-8")
                # self.logger.print(f"Received UDP from {sender_address.toString()}:{sender_port}: {message}")

                if message == STATUS_REQUEST:
                    response_data = STATUS_RESPONSE.encode("utf-8")
                    # Send response back to the original sender's port (MYOGESTIC_UDP_PORT)
                    # Note: setup_interface listens on MYOGESTIC_UDP_PORT
                    bytes_written = self._udp_socket.writeDatagram(response_data, sender_address, MYOGESTIC_UDP_PORT)
                    if bytes_written > 0:
                        # Log only the first time the response is sent successfully
                        if not self._status_response_logged:
                            self.logger.print(
                                f"Sent initial status response '{STATUS_RESPONSE}' to {sender_address.toString()}:{MYOGESTIC_UDP_PORT}"
                            )
                            self._status_response_logged = True
                        # pass # Original commented-out logger removed for clarity
                        # self.logger.print(f"Sent status response '{STATUS_RESPONSE}' to {sender_address.toString()}:{MYOGESTIC_UDP_PORT}")
                    else:
                        self.logger.print(
                            f"Error sending status response: {self._udp_socket.errorString()}", level="ERROR"
                        )

            except UnicodeDecodeError:
                self.logger.print(
                    f"Received undecodable UDP data from {sender_address.toString()}:{sender_port}", level="WARNING"
                )
            except Exception as e:
                self.logger.print(f"Error processing UDP datagram: {e}", level="ERROR")

    def _read_predicted_cursor_datagrams(self):
        """Reads and processes incoming UDP datagrams for predicted cursor position."""
        while self._predicted_cursor_socket.hasPendingDatagrams():
            datagram_size = self._predicted_cursor_socket.pendingDatagramSize()
            datagram, sender_address, sender_port = self._predicted_cursor_socket.readDatagram(datagram_size)

            try:
                message_str = datagram.data().decode("utf-8")

                # Safely evaluate the string representation of the list "[[x, y]]"
                coord_list_outer = ast.literal_eval(message_str)
                
                if isinstance(coord_list_outer, list) and len(coord_list_outer) == 1 and \
                   isinstance(coord_list_outer[0], list) and len(coord_list_outer[0]) == 2:
                    
                    x_raw, y_raw = coord_list_outer[0]
                    
                    if isinstance(x_raw, (int, float)) and isinstance(y_raw, (int, float)):
                        pred_x = float(x_raw) / 100.0
                        pred_y = float(y_raw) / 100.0

                        if hasattr(self, 'vispy_widget') and self.vispy_widget:
                            self.vispy_widget.update_predicted_cursor(pred_x, pred_y)
                            # Optional: self.logger.print(f"Updated predicted cursor to ({pred_x:.2f}, {pred_y:.2f}) from {sender_address.toString()}:{sender_port}")
                        else:
                            self.logger.print("Vispy widget not available to update predicted cursor.", level="WARNING")
                    else:
                        self.logger.print(f"Invalid coordinate types in predicted data message: {message_str}", level="WARNING")
                else:
                    self.logger.print(f"Invalid predicted cursor data format: {message_str}", level="WARNING")

            except UnicodeDecodeError:
                self.logger.print(
                    f"Received undecodable UDP data for predicted cursor from {sender_address.toString()}:{sender_port}", level="WARNING"
                )
            except (SyntaxError, ValueError) as e: # ast.literal_eval can raise SyntaxError or ValueError
                self.logger.print(f"Error parsing predicted cursor data '{message_str}': {e}", level="ERROR")
            except Exception as e:
                self.logger.print(f"Error processing predicted cursor UDP datagram: {e}", level="ERROR")

    # Example slot for a button click (replace with actual slots using self.ui.widgetName)
    # def on_button_click(self):
    #     print("Button clicked!")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Ensure the UDP socket is closed when the window closes."""
        self.logger.print("Closing UDP socket.")
        self._udp_socket.close()
        self._stop_cursor_streaming() # Ensure streaming timer is stopped
        if hasattr(self, '_streaming_socket'):
            self._streaming_socket.close()
        if hasattr(self, '_predicted_cursor_socket'):
            self._predicted_cursor_socket.close()
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
            f"Recalculating trajectories for signal freq: {signal_freq:.2f} Hz using sampling rate: {CURSOR_SAMPLING_RATE} Hz"
        )
        trajectories = {}
        # Calculate for movement directions only (exclude "Rest")
        for direction in DIRECTIONS:
            if direction != "Rest":
                trajectories[direction] = generate_sinusoid_trajectory(
                    signal_frequency=signal_freq,
                    direction=direction,
                    sampling_rate=CURSOR_SAMPLING_RATE,
                    # Amplitude defaults to 1.0 in helper
                )
                # Debug print shape
                # print(f"  Direction: {direction}, Trajectory shape: {trajectories[direction].shape}")

        # Pass the calculated trajectories to the VispyWidget
        self.vispy_widget.set_trajectories(trajectories)

    # Method to update VispyWidget timing parameters
    def _update_vispy_timing_params(self):
        """Collects current timing parameters and sends them to VispyWidget."""
        if hasattr(self, 'vispy_widget'):  # Ensure vispy_widget exists
            signal_freq = (
                self.cursor_frequency_double_spin_box.value() if self.cursor_frequency_double_spin_box else 0.1
            )

            # Get display frequency from ComboBox
            display_freq_text = (
                self.reference_cursor_refresh_rate_combo_box.currentText()
                if self.reference_cursor_refresh_rate_combo_box
                else "60.0"
            )
            try:
                display_freq = float(display_freq_text)
            except ValueError:
                self.logger.print(
                    f"Invalid value in reference refresh rate ComboBox: '{display_freq_text}'. Using default 60.0",
                    level="WARNING",
                )
                display_freq = 60.0  # Default value on conversion error

            # Check if signal frequency changed, if so, recalculate trajectories
            # Note: Accessing _signal_frequency directly is not ideal, consider storing previous value
            current_vispy_signal_freq = getattr(self.vispy_widget, '_signal_frequency', None)
            if current_vispy_signal_freq is None or not math.isclose(signal_freq, current_vispy_signal_freq):
                # We need the signal frequency for recalculation, but VispyWidget no longer stores it directly.
                # Let's recalculate based on the current spinbox value directly.
                self._recalculate_trajectories()  # Recalculate before updating VispyWidget

            # Pass display frequency to VispyWidget
            self.vispy_widget.update_timing_parameters(display_freq)
            self.logger.print(f"Updated Vispy display timing: Display Freq={display_freq} Hz")
            # The log message about signal freq might be misleading now, as it's only used for calc.
            # Consider removing or changing: (Sampling Freq fixed at {CURSOR_SAMPLING_RATE} Hz)
        else:
            self.logger.print("Cannot update Vispy timing params: vispy_widget not initialized.", level="WARNING")

    # Method to update VispyWidget hold parameters
    def _update_vispy_activation_params(self):
        """Collects current activation parameters (rest, hold, middle) and sends them to VispyWidget."""
        if hasattr(self, 'vispy_widget'):  # Ensure vispy_widget exists
            # Rest: Fixed threshold 0%, read duration
            rest_threshold_percent = 0
            rest_duration_s = self.rest_duration_double_spin_box.value() if self.rest_duration_double_spin_box else 0.0

            # Peak (Hold): Fixed threshold 100%, read duration
            peak_threshold_percent = 100
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
            self.logger.print(
                f"Updated Vispy activation params: Rest=(0%, {rest_duration_s}s), "
                f"Peak=(100%, {peak_duration_s}s), "
                f"Middle=({middle_threshold_percent}%, {middle_duration_s}s, Stop: {middle_stop_condition}), "
                f"TargetBox=(Visible: {target_box_visible}, Lower: {target_box_lower_percent}%, Upper: {target_box_upper_percent}%)"
            )
        else:
            self.logger.print("Cannot update Vispy activation params: vispy_widget not initialized.", level="WARNING")

    # Signal Handlers (Slots)
    def _on_up_movement_changed(self, text: str):
        self._selected_up_movement = text
        self.logger.print(f"Up movement changed to: {text}")
        self._update_vispy_mappings()  # Update display

    def _on_down_movement_changed(self, text: str):
        self._selected_down_movement = text
        self.logger.print(f"Down movement changed to: {text}")
        self._update_vispy_mappings()  # Update display

    def _on_left_movement_changed(self, text: str):
        self._selected_left_movement = text
        self.logger.print(f"Left movement changed to: {text}")
        self._update_vispy_mappings()  # Update display

    def _on_right_movement_changed(self, text: str):
        self._selected_right_movement = text
        self.logger.print(f"Right movement changed to: {text}")
        self._update_vispy_mappings()  # Update display

    # Slot for timing parameter changes
    def _on_timing_params_changed(self):
        """Handles changes in cursor frequency or reference refresh rate."""
        self._update_vispy_timing_params()

    # Slot for hold parameter changes
    def _on_activation_params_changed(self):
        """Handles changes in any activation threshold or duration."""
        self._update_vispy_activation_params()

    # Slot for predicted refresh rate changes
    def _on_predicted_refresh_rate_changed(self):
        """Handles changes in predicted cursor refresh rate."""
        # This slot is now empty as the predicted cursor refresh rate is no longer used
        pass

    def _on_streaming_button_clicked(self):
        """Handles the streaming push button click to toggle data streaming."""
        if not self.streaming_push_button: # Should not happen if UI is set up
            return

        if self.streaming_push_button.isChecked():
            self._start_cursor_streaming()
            self.streaming_push_button.setText("Stop Streaming")
        else:
            self._stop_cursor_streaming()
            self.streaming_push_button.setText("Start Streaming")

    # --- Cursor Data Streaming Methods ---
    def _start_cursor_streaming(self):
        """Starts the timer for streaming cursor position data."""
        if CURSOR_STREAMING_RATE > 0:
            self.logger.print(f"Starting cursor position streaming at {CURSOR_STREAMING_RATE} Hz.")
            self._streaming_timer.start()
        else:
            self.logger.print("Cannot start streaming: CURSOR_STREAMING_RATE is not positive.", level="WARNING")

    def _stop_cursor_streaming(self):
        """Stops the timer for streaming cursor position data."""
        if self._streaming_timer.isActive(): # Check if timer is active before trying to stop associated processes
            self.logger.print("Stopping cursor position streaming.")
            self._streaming_timer.stop()

    def _send_cursor_position_datagram(self):
        """Sends the current reference cursor position and task label via UDP."""
        if hasattr(self, 'vispy_widget') and self.vispy_widget:
            try:
                current_pos_xy = self.vispy_widget.get_reference_cursor_position() # (x, y) tuple
                current_direction_string = self.vispy_widget.get_current_direction_string()
                task_label = "Inactive"

                if self.vispy_widget.movement_active:
                    if current_direction_string == "Up":
                        task_label = self._selected_up_movement
                    elif current_direction_string == "Down":
                        task_label = self._selected_down_movement
                    elif current_direction_string == "Left":
                        task_label = self._selected_left_movement
                    elif current_direction_string == "Right":
                        task_label = self._selected_right_movement
                    elif current_direction_string == "Rest":
                        task_label = "Rest" # Or specific mapping if you have one for Rest

                if current_pos_xy is not None and task_label is not None:
                    # Format as [[x_int, y_int]] (transposed from user's previous change)
                    pos_array_to_send = np.array([
                        [int(current_pos_xy[0] * 100)],  # x-coordinate scaled
                        [int(current_pos_xy[1] * 100)]   # y-coordinate scaled
                    ], dtype=np.int16).T # Transpose to get [[x_int, y_int]] and use int32 for integer values

                    # Construct the data string: "[[x, y]]_TaskLabel"
                    data_string = f"{pos_array_to_send.tolist()}_{task_label}"
                    byte_data = data_string.encode("utf-8")

                    bytes_sent = self._streaming_socket.writeDatagram(
                        byte_data, QHostAddress(SOCKET_IP), MYOGESTIC_UDP_PORT
                    )
                    # print(f"Sent: {data_string}") # Optional: for high-frequency logging

            except Exception as e:
                self.logger.print(f"Error sending cursor position datagram: {e}", level="ERROR")


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
