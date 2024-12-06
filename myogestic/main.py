import qdarkstyle
import sys

from PySide6.QtWidgets import QApplication
import qdarktheme

from myogestic.gui.myogestic import MyoGestic

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("DarkFusion")
    app.setStyleSheet(qdarkstyle.load_stylesheet())

    main_window = MyoGestic()
    main_window.show()

    sys.exit(app.exec())
