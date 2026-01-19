import os
import sys

import qdarkstyle
from PySide6.QtWidgets import QApplication

# add myogestic to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from myogestic.gui.myogestic import MyoGestic
from myogestic.utils.config import CONFIG_REGISTRY  # noqa


# Force X11 backend on Linux/Wayland to fix white plot rendering
if sys.platform == "linux":
    os.environ["QT_QPA_PLATFORM"] = "xcb"

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyside6"))

    main_window = MyoGestic()
    main_window.show()

    sys.exit(app.exec())
