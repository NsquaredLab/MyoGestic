import qdarkstyle
import sys

from PySide6.QtWidgets import QApplication

from myogestic.gui.myogestic import MyoGestic

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyside6"))

    main_window = MyoGestic()
    main_window.show()

    sys.exit(app.exec())
