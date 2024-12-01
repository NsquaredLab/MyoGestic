from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QFileDialog,
    QMessageBox,
    QWidget,
    QSizePolicy
)
from vispy import scene
import sys
import numpy as np
import pickle

from vispy.scene import SceneCanvas, visuals

from myogestic.gui.widgets.monitoring.template import _MonitoringWidgetBaseClass
from myogestic.utils.constants import DATASETS_DIR_PATH, NO_DATASET_SELECTED_INFO
from myogestic.gui.widgets.monitoring.ui_compiled.umap_window import Ui_UMAP

NUM_LINE_POINTS = 200
IMAGE_SHAPE = (600, 800)  # (height, width)


class UMAPMonitoringWidget(_MonitoringWidgetBaseClass, QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_UMAP()  # Create an instance of the UI class
        self.ui.setupUi(self)  # Set up the UI
        self.selected_dataset_filepath = (
            None  # Initialize the selected dataset filepath
        )
        self._setup_functionality()

    def _select_dataset(self) -> None:
        # Open dialog to select dataset
        dialog = QFileDialog(self)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Pickle files (*.pkl)")
        dialog.setDirectory(str(DATASETS_DIR_PATH))

        filename, _ = dialog.getOpenFileName()

        if not filename:
            QMessageBox.warning(
                self, "Warning", NO_DATASET_SELECTED_INFO, QMessageBox.Ok
            )
            self.ui.trainingSelectedDatasetLabel.setText(NO_DATASET_SELECTED_INFO)
            return

        self.selected_dataset_filepath = filename
        self.ui.trainingSelectedDatasetLabel.setText(
            self.selected_dataset_filepath.split("_")[-1].replace(".pkl", "").title()
        )

        self.ui.pushButton.setEnabled(True)

    def run(self):
        if not self.selected_dataset_filepath:
            QMessageBox.warning(self, "Warning", "No dataset selected.", QMessageBox.Ok)
            return

        # Load the dataset
        dataset = self.load_dataset(self.selected_dataset_filepath)

        # Perform UMAP
        umap_data = self.umap(dataset["X"])

        # Plot the UMAP
        self.plot_umap(umap_data)

    def load_dataset(self, filepath: str) -> dict:
        with open(filepath, "rb") as file:
            return pickle.load(file)

    def umap(self, data: np.ndarray) -> np.ndarray:
        # Placeholder for UMAP implementation
        # Replace with actual UMAP computation
        return data  # Assuming data is already in 2D for simplicity

    def plot_umap(self, umap_data: np.ndarray) -> None:
        self.view.camera = "turntable"
        scatter = scene.visuals.Markers()
        scatter.set_data(umap_data, edge_color=None, face_color=(1, 1, 1, 0.5), size=5)
        self.view.add(scatter)

    def _setup_functionality(self) -> None:
        # Connect the button to the select dataset function
        self.ui.trainingSelectDatasetPushButton.clicked.connect(self._select_dataset)

        self.ui.pushButton.clicked.connect(self.run)

        self.ui.pushButton.setEnabled(False)

        self._canvas_wrapper = CanvasWrapper()
        # set _canvas_wrapper's canvas policy to expand and fill the layout
        self._canvas_wrapper.canvas.native.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )



        self.ui.verticalLayout_2.addWidget(self._canvas_wrapper.canvas.native)

        # update central widget to fit the canvas
        self.setCentralWidget(self.ui.centralwidget)
        self.adjustSize()

        self.setMinimumSize(400, 400)
        self.setMaximumSize(self.sizeHint())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_size = self.size()
        self._canvas_wrapper.canvas.size = (new_size.width() - 20, new_size.height() - 20)


class CanvasWrapper:
    def __init__(self):
        self.canvas = SceneCanvas(size=(800, 800))
        self.grid = self.canvas.central_widget.add_grid()

        # Create a new view for the scatter plot
        self.view = self.grid.add_view(0, 0, bgcolor="white")

        # Generate random scatter plot data
        scatter_data = _generate_random_scatter_data(1000)
        self.scatter = visuals.Markers()
        self.scatter.set_data(scatter_data, edge_color=None, face_color=(1, 0, 0, 0.5), size=10)
        self.view.add(self.scatter)

        self.view.camera = "panzoom"
        self.view.camera.set_range(x=(0, 1), y=(0, 1))


def _generate_random_scatter_data(num_points, dtype=np.float32):
    rng = np.random.default_rng()
    data = rng.random((num_points, 2), dtype=dtype)
    return data


if __name__ == "__main__":
    app = QApplication(sys.argv)
    mainWin = UMAPMonitoringWidget()
    mainWin.show()
    sys.exit(app.exec())
