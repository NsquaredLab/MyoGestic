import sys
import socket
from PySide6.QtCore import QSocketNotifier, QTimer
from PySide6.QtWidgets import QApplication, QTextEdit, QVBoxLayout, QLabel, QWidget


class UDPListenerApp(QWidget):
    def __init__(self, ip: str, port: int):
        super().__init__()

        # Set up the GUI
        self.setWindowTitle("UDP Listener")
        self.resize(600, 400)

        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.message_counter_label = QLabel("Messages per second: 0", self)

        layout = QVBoxLayout(self)
        layout.addWidget(self.message_counter_label)
        layout.addWidget(self.text_edit)

        # Set up the UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((ip, port))
        self.sock.setblocking(False)

        # Integrate with Qt event loop
        self.notifier = QSocketNotifier(self.sock.fileno(), QSocketNotifier.Read)
        self.notifier.activated.connect(self.handle_data)

        # Set up the message counter
        self.message_count = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_message_rate)
        self.timer.start(1000)  # Update every second

    def handle_data(self):
        try:
            while True:
                data, addr = self.sock.recvfrom(1024)  # Buffer size is 1024 bytes
                message = f"Received from {addr}: {data.decode('utf-8')}\n"
                self.text_edit.append(message)
                self.message_count += 1
        except BlockingIOError:
            pass

    def update_message_rate(self):
        self.message_counter_label.setText(f"Messages per second: {self.message_count}")
        self.message_count = 0

    def closeEvent(self, event):
        # Clean up the socket on exit
        self.notifier.setEnabled(False)
        self.sock.close()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    listener = UDPListenerApp(ip="127.0.0.1", port=1212)
    listener.show()
    sys.exit(app.exec())
