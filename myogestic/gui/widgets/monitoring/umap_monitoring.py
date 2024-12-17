import cuml
import numpy as np
import pickle
import sys
import torch
from PySide6.QtCore import QObject, Signal, Slot, QThread
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QSizePolicy,
)
from cuml import UMAP
from datetime import datetime
from doc_octopy.datasets.loader import EMGDatasetLoader
from joblib import dump, load
from pathlib import Path
from tqdm import tqdm
from typing import Any
from vispy import scene
from vispy.scene import SceneCanvas, visuals

from myogestic.gui.widgets.monitoring.template import _MonitoringWidgetBaseClass
from myogestic.gui.widgets.monitoring.ui_compiled.umap_window import Ui_UMAP
from myogestic.utils.constants import (
    DATASETS_DIR_PATH,
    NO_DATASET_SELECTED_INFO,
    MONITORING_WIDGETS_EXCHANGE_DIR_PATH,
)

NUM_LINE_POINTS = 200
IMAGE_SHAPE = (600, 800)  # (height, width)


class RunningWorker(QObject):
    finished = Signal()
    plot_info = Signal(np.ndarray, list)

    def __init__(
        self,
        parent=None,
        model=None,
        umap_model=None,
        transformed_training_data=None,
    ):
        super().__init__(parent)
        self.model = model
        self.umap_model = umap_model
        self.transformed_training_data = transformed_training_data
        self.transformed_online_data = []
        self.color_list = [(1, 0, 0, 0.5)] * len(self.transformed_training_data)

    @Slot(np.ndarray)
    def run(self, emg_data: np.ndarray) -> None:
        if not self.umap_model:
            QMessageBox.warning(
                self,
                "Warning",
                "You need to train the umap model first.",
                QMessageBox.Ok,
            )
            return

        latent_vector = (
            self.model.cnn_encoder(
                self.model._reshape_and_normalize(
                    torch.from_numpy(emg_data[:, None].astype(np.float32)).to(
                        self.model.device
                    )
                )
            )
            .cpu()
            .detach()
            .numpy()
        )

        self.transformed_online_data.append(
            list(self.umap_model.transform(latent_vector)[0])
        )

        self.color_list.append((0, 0, 1, 0.5))

        self.plot_info.emit(
            np.concatenate(
                [self.transformed_training_data, np.array(self.transformed_online_data)]
            ),
            self.color_list,
        )


class TrainingWorker(QObject):
    finished = Signal()
    pass_info = Signal(str, str)

    def __init__(
        self,
        parent=None,
        dataset_path: str = None,
        model_information: dict[str, Any] = None,
    ):
        super().__init__(parent)
        self.dataset_path = dataset_path
        self.model_information = model_information

    @Slot()
    def run(self):
        with open(self.dataset_path, "rb") as file:
            dataset = pickle.load(file)

        loader = EMGDatasetLoader(
            Path(DATASETS_DIR_PATH, dataset["zarr_file_path"]).resolve(),
            dataloader_parameters={
                "batch_size": 64,
                "drop_last": True,
                "num_workers": 10,
                "pin_memory": True,
                "persistent_workers": True,
            },
        )

        model = self.model_information["functions_map"]["load"](
            self.model_information["model_path"],
            self.model_information["models_map"][0](
                **self.model_information["model_params"]
            ),
        )

        latent_vectors = []
        with torch.inference_mode():
            for i, (input_tensor, _) in tqdm(enumerate(loader.train_dataloader())):
                input_tensor = input_tensor.to(model.device)
                latent_vector = model._reshape_and_normalize(input_tensor)
                latent_vector = model.cnn_encoder(latent_vector)
                latent_vectors.append(latent_vector.cpu().detach().numpy())

        latent_vectors = np.concatenate(latent_vectors, axis=0)

        now = datetime.now()
        formatted_now = now.strftime("%Y%m%d_%H%M%S%f")

        umap_model = UMAP(metric="euclidean", verbose=False)
        train_data_transformed = umap_model.fit_transform(latent_vectors)

        print(cuml.metrics.trustworthiness(latent_vectors, train_data_transformed))

        path_umap_model = (
            MONITORING_WIDGETS_EXCHANGE_DIR_PATH
            / "umap"
            / f"{formatted_now}_umap_model.joblib"
        )
        path_transformed_train_data = (
            MONITORING_WIDGETS_EXCHANGE_DIR_PATH
            / "umap"
            / f"{formatted_now}_transformed_train_data.joblib"
        )

        path_umap_model.parent.mkdir(parents=True, exist_ok=True)
        path_transformed_train_data.parent.mkdir(parents=True, exist_ok=True)

        dump(umap_model, path_umap_model)
        dump(train_data_transformed, path_transformed_train_data)

        self.pass_info.emit(str(path_umap_model), str(path_transformed_train_data))
        self.finished.emit()


class UMAPMonitoringWidget(_MonitoringWidgetBaseClass):
    def __init__(self, parent=None, emg_signal=None):
        super().__init__(parent, emg_signal)
        self.ui = Ui_UMAP()  # Create an instance of the UI class
        self.ui.setupUi(self)  # Set up the UI
        self.selected_dataset_filepath = (
            None  # Initialize the selected dataset filepath
        )
        self.model = None
        self.umap_model = None
        self.color_list = None
        self.transformed_online_data = []
        self.running_thread = None

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

        self.training_worker = TrainingWorker(
            None, self.selected_dataset_filepath, self.model_information
        )
        self.training_thread = QThread()
        self.training_worker.moveToThread(self.training_thread)

        self.training_thread.started.connect(self.training_worker.run)
        self.training_worker.finished.connect(self.training_thread.quit)
        self.training_worker.finished.connect(self.training_worker.deleteLater)
        self.training_thread.finished.connect(self.training_thread.deleteLater)
        self.training_worker.pass_info.connect(self.stop_training_umap)

        self.ui.umapCreateModelPushButton.setEnabled(True)

    def start_training_umap(self, dataset: dict) -> None:
        self.training_thread.start()

    @Slot(np.ndarray, list)
    def plot_data(self, scatter_data: np.ndarray, color_list=None) -> None:
        self._canvas_wrapper.scatter.set_data(
            scatter_data,
            edge_color=None,
            face_color=color_list if color_list else (1, 0, 0, 0.5),
            size=10,
        )

    @Slot(str, str)
    def stop_training_umap(
        self, umap_model_path, transformed_training_data_path
    ) -> None:
        self.ui.umapCreateModelPushButton.setEnabled(False)

        self.umap_model = load(umap_model_path)
        self.transformed_training_data = load(transformed_training_data_path)

        self.color_list = [(1, 0, 0, 0.5)] * len(self.transformed_training_data)

        self.training_thread.quit()

        print("UMAP model trained successfully!")

        self.plot_data(self.transformed_training_data, self.color_list)

        self.model = self.model_information["functions_map"]["load"](
            self.model_information["model_path"],
            self.model_information["models_map"][0](
                **self.model_information["model_params"]
            ),
        )

        self.running_worker = RunningWorker(
            None, self.model, self.umap_model, self.transformed_training_data
        )
        self.running_thread = QThread()
        self.running_worker.moveToThread(self.running_thread)

        self.running_thread.finished.connect(self.running_thread.deleteLater)
        self.running_worker.plot_info.connect(self.plot_data)
        self.running_thread.finished.connect(self.running_thread.deleteLater)
        self.emg_signal.connect(self.running_worker.run)

        self.running_thread.start()

    def load_dataset(self, filepath: str) -> dict:
        with open(filepath, "rb") as file:
            return pickle.load(file)

    def plot_umap(self, umap_data: np.ndarray, color_list=None) -> None:
        self.view.camera = "turntable"
        scatter = scene.visuals.Markers()
        scatter.set_data(
            umap_data,
            edge_color=None,
            face_color=color_list if color_list else (1, 0, 0, 0.5),
            size=5,
        )
        self.view.add(scatter)

    def _setup_functionality(self) -> None:
        # Connect the button to the select dataset function
        self.ui.trainingSelectDatasetPushButton.clicked.connect(self._select_dataset)

        self.ui.umapCreateModelPushButton.clicked.connect(self.start_training_umap)
        self.ui.umapCreateModelPushButton.setEnabled(False)

        self._canvas_wrapper = CanvasWrapper()
        # set _canvas_wrapper's canvas policy to expand and fill the layout
        self._canvas_wrapper.canvas.native.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.ui.horizontalLayout.addWidget(self._canvas_wrapper.canvas.native)

        # update central widget to fit the canvas
        self.setCentralWidget(self.ui.centralwidget)
        self.adjustSize()

        self.setMinimumSize(400, 400)
        self.setMaximumSize(self.sizeHint())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_size = self.size()
        self._canvas_wrapper.canvas.size = (
            new_size.width() - 20,
            new_size.height() - 20,
        )


class CanvasWrapper:
    def __init__(self):
        self.canvas = SceneCanvas(size=(800, 800))
        self.grid = self.canvas.central_widget.add_grid()

        # Create a new view for the scatter plot
        self.view = self.grid.add_view(0, 0, bgcolor="white")

        # Generate random scatter plot data
        scatter_data = _generate_random_scatter_data(1000)
        self.scatter = visuals.Markers()
        self.scatter.set_data(
            scatter_data, edge_color=None, face_color=(1, 0, 0, 0.5), size=10
        )
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
