from myogestic.gui.myogestic import MyoGestic
import sys
from PySide6.QtWidgets import QApplication

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    main_window = MyoGestic()
    main_window.show()

    sys.exit(app.exec())
