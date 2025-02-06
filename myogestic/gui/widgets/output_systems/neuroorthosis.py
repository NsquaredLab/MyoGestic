from typing import Any

from PySide6.QtCore import Signal, QByteArray, QTimer
from PySide6.QtNetwork import QHostAddress, QUdpSocket

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.output_system import OutputSystemTemplate
from myogestic.utils.constants import MYOGESTIC_UDP_PORT

PREDICTION2INTERFACE_MAP = {
    -1: "Rejected Sample",
    0: "[0, 0, 0, 0, 0, 0, 0, 0, 0]",
    1: "[0, 0, 1, 0, 0, 0, 0, 0, 0]",
    2: "[1, 0, 0, 0, 0, 0, 0, 0, 0]",
    3: "[0, 0, 0, 1, 0, 0, 0, 0, 0]",
    4: "[0, 0, 0, 0, 1, 0, 0, 0, 0]",
    5: "[0, 0, 0, 0, 0, 1, 0, 0, 0]",
    6: "[1, 1, 1, 1, 1, 1, 0, 0, 0]",
    7: "[1, 1, 1, 0, 0, 0, 0, 0, 0]",
    8: "[1, 1, 1, 1, 0, 0, 0, 0, 0]",
}

SOCKET_IP = "127.0.0.1"
NEUROORTHOSIS_UDP_PORT = 1212

STREAM_ASAP = False  # Stream predictions as soon as they are available

STREAMING_FREQUENCY = 32  # Desired streaming frequency in Hz
STREAMING_INTERVAL = 1.0 / STREAMING_FREQUENCY  # Interval in seconds


class NeuroOrthosisOutputSystem(OutputSystemTemplate):
    outgoing_message_signal = Signal(QByteArray)

    def __init__(self, main_window, prediction_is_classification: bool) -> None:
        super().__init__(main_window, prediction_is_classification)

        self._streaming_udp_socket = QUdpSocket(self)
        self.outgoing_message_signal.connect(self._write_mechatronic_control_message)
        self._streaming_udp_socket.bind(QHostAddress(SOCKET_IP), MYOGESTIC_UDP_PORT + 1)

        self._latest_prediction = None  # Always store the latest prediction

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._emit_latest_prediction)
        self._timer.start(1000 // STREAMING_FREQUENCY)

    def _write_mechatronic_control_message(self, message: QByteArray) -> None:
        output_bytes = self._streaming_udp_socket.writeDatagram(
            message, QHostAddress(SOCKET_IP), NEUROORTHOSIS_UDP_PORT
        )

        if output_bytes == -1:
            self._main_window.logger.print(
                "Error in sending message to the Neuroorthosis",
                level=LoggerLevel.ERROR,
            )

    def _process_prediction__classification(self, prediction: Any) -> bytes:
        return PREDICTION2INTERFACE_MAP[prediction].encode("utf-8")

    def _process_prediction__regression(self, prediction: Any) -> bytes:
        return str([prediction[0]] + [0] + prediction[1:] + [0, 0, 0]).encode("utf-8")

    def send_prediction(self, prediction: Any) -> None:
        processed_prediction = self.process_prediction(prediction)

        if STREAM_ASAP:
            # If immediate streaming is enabled, emit the prediction directly
            self.outgoing_message_signal.emit(processed_prediction)
        else:
            # Otherwise, buffer the prediction for delayed streaming
            self._latest_prediction = processed_prediction

    def _emit_latest_prediction(self) -> None:
        # Emit the latest buffered prediction if available and in delayed mode
        if self._latest_prediction is not None and not STREAM_ASAP:
            self.outgoing_message_signal.emit(self._latest_prediction)

    def close_event(self, event):
        self._timer.stop()
        self._streaming_udp_socket.close()
