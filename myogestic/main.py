import os
import signal
import sys

import qdarkstyle
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

# add myogestic to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from myogestic.gui.myogestic import MyoGestic
from myogestic.utils.config import CONFIG_REGISTRY  # noqa


# Force X11 backend on Linux/Wayland to fix white plot rendering
if sys.platform == "linux":
    os.environ["QT_QPA_PLATFORM"] = "xcb"

# Custom stylesheet additions for improved UI
CUSTOM_STYLESHEET = """
/* Primary action buttons - Connect buttons stand out */
QPushButton[text="Connect"], QPushButton[text="Disconnect"] {
    background-color: #2d7d46;
    border: 1px solid #3d9d56;
    font-weight: bold;
}
QPushButton[text="Connect"]:hover, QPushButton[text="Disconnect"]:hover {
    background-color: #3d9d56;
}
QPushButton[text="Connect"]:pressed, QPushButton[text="Disconnect"]:pressed {
    background-color: #1d5d36;
}

/* Streaming buttons - use accent color */
QPushButton[text="Stream"], QPushButton[text="Start Streaming"],
QPushButton[text="Stop Streaming"] {
    background-color: #4a7fb0;
    border: 1px solid #5a8fc0;
    font-weight: bold;
}
QPushButton[text="Stream"]:hover, QPushButton[text="Start Streaming"]:hover,
QPushButton[text="Stop Streaming"]:hover {
    background-color: #5a8fc0;
}

/* Checkable buttons when checked */
QPushButton:checked {
    background-color: #b04a4a;
    border: 1px solid #c05a5a;
}

/* Group boxes - reduce visual weight */
QGroupBox {
    font-weight: bold;
    margin-top: 8px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
}

/* Protocol mode radio buttons */
QRadioButton {
    spacing: 8px;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
}

/* Tooltips */
QToolTip {
    background-color: #2b2b2b;
    color: #ffffff;
    border: 1px solid #555555;
    padding: 5px;
    border-radius: 3px;
}
"""


def sigint_handler(*args):
    """Handle Ctrl+C by quitting the application."""
    QApplication.quit()


def main():
    """Entry point for the MyoGestic application."""
    # Set up signal handler before creating QApplication
    signal.signal(signal.SIGINT, sigint_handler)

    # Set high DPI scaling policy BEFORE creating QApplication
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)

    # Timer allows Python to process signals during Qt event loop
    timer = QTimer()
    timer.start(500)  # Check every 500ms
    timer.timeout.connect(lambda: None)  # Empty handler keeps Python responsive

    app.setStyle("Fusion")
    # Combine qdarkstyle with custom improvements
    base_stylesheet = qdarkstyle.load_stylesheet(qt_api="pyside6")
    app.setStyleSheet(base_stylesheet + CUSTOM_STYLESHEET)

    main_window = MyoGestic()
    main_window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
