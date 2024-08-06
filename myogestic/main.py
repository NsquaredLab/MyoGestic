from myogestic.gui.myogestic import MyoGestic
import sys
from PySide6.QtWidgets import QApplication, QMessageBox


class UserWarning(QMessageBox):
    def __init__(self, message: str, parent=None):
        super(UserWarning, self).__init__(parent)
        self.setIcon(QMessageBox.Warning)
        self.setWindowTitle("Warning")
        self.setText(message)
        self.setStandardButtons(QMessageBox.Ok)
        self.exec()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    main_window = MyoGestic()
    main_window.show()

    sys.exit(app.exec())
