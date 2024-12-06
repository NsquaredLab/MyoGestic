from __future__ import annotations

import pickle
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from myogestic.gui.widgets.logger import LoggerLevel

from myogestic.models.interface import MyoGesticModelInterface
from myogestic.utils.config import UnchangeableParameter, CONFIG_REGISTRY
from myogestic.utils.constants import (
    RECORDING_DIR_PATH,
    MODELS_DIR_PATH,
    DATASETS_DIR_PATH,
    NO_DATASET_SELECTED_INFO,
)

if TYPE_CHECKING:
    from myogestic.gui.myogestic import MyoGestic


class PopupWindowParameters(QDialog):
    def __init__(self, selected_model_name):
        super().__init__()

        self.model_changeable_parameters = {}

        # set for each parameter the default value in an appropriate widget
        self.setWindowTitle("Model Parameters")
        self.setGeometry(100, 100, 300, 200)  # x, y, width, height

        layout = QVBoxLayout()

        for parameter, value in CONFIG_REGISTRY.models_parameters_map[
            selected_model_name
        ]["changeable"].items():
            horizontal_layout = QHBoxLayout()
            horizontal_layout.addWidget(QLabel(parameter.replace("_", " ").title()))
            default_value = value["default_value"]

            self.model_changeable_parameters[parameter] = default_value

            if isinstance(default_value, int):
                parameter_widget = QSpinBox()
                parameter_widget.setValue(default_value)
                parameter_widget.setRange(value["start_value"], value["end_value"])
                parameter_widget.setSingleStep(value["step"])
                parameter_widget.valueChanged.connect(
                    partial(self._on_change, parameter)
                )
            elif isinstance(default_value, float):
                parameter_widget = QDoubleSpinBox()
                parameter_widget.setValue(default_value)
                parameter_widget.setRange(value["start_value"], value["end_value"])
                parameter_widget.setSingleStep(value["step"])
                parameter_widget.valueChanged.connect(
                    partial(self._on_change, parameter)
                )
            elif isinstance(default_value, str):
                parameter_widget = QLineEdit(default_value)
                parameter_widget.textChanged.connect(
                    partial(self._on_change, parameter)
                )
            elif isinstance(default_value, bool):
                parameter_widget = QCheckBox()
                parameter_widget.setChecked(default_value)
                parameter_widget.stateChanged.connect(
                    partial(self._on_change, parameter)
                )
            elif isinstance(default_value, list):
                parameter_widget = QComboBox()
                parameter_widget.addItems(default_value)
                parameter_widget.setCurrentText(value["default_value"])
                parameter_widget.currentTextChanged.connect(
                    partial(self._on_change, parameter)
                )

            horizontal_layout.addWidget(parameter_widget)
            layout.addLayout(horizontal_layout)
        self.setLayout(layout)

    def _on_change(self, parameter_name: str, value: UnchangeableParameter) -> None:
        self.model_changeable_parameters[parameter_name] = value
        print(self.model_changeable_parameters)


class PopupWindowFeatures(QDialog):
    def __init__(self, selected_features: list[str]):
        super().__init__()

        self.selected_features = set(selected_features)

        self.setWindowTitle("Feature Selection")
        self.setGeometry(100, 100, 300, 200)  # x, y, width, height

        layout = QVBoxLayout()

        # add a scrollable list of features that are a checkbox and a label
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area_widget = QWidget()
        self.scroll_area_layout = QVBoxLayout()

        self.checkboxes = []

        for filter in CONFIG_REGISTRY.features_map.keys():
            feature_checkbox = QCheckBox(filter)
            self.checkboxes.append(feature_checkbox)
            self.scroll_area_layout.addWidget(feature_checkbox)
            if filter in self.selected_features:
                feature_checkbox.setChecked(True)

            feature_checkbox.checkStateChanged.connect(partial(self._on_change, filter))

        self.scroll_area_widget.setLayout(self.scroll_area_layout)
        self.scroll_area.setWidget(self.scroll_area_widget)
        layout.addWidget(self.scroll_area)

        self.setLayout(layout)

    def _recheck_checkboxes(self):
        for checkbox in self.checkboxes:
            if checkbox.text() in self.selected_features:
                checkbox.setCheckState(Qt.CheckState.Checked)

    def _on_change(self, feature_name: str, state: int) -> None:
        if state.value == 2:
            self.selected_features.add(feature_name)
        else:
            if len(self.selected_features) == 1:
                self._recheck_checkboxes()
            else:
                self.selected_features.remove(feature_name)


class PyQtThread(QThread):
    """
    Custom PyQt thread class for running
    a target function in a separate thread.

    Parameters
    ----------
    target : function
        The target function to run in the thread.
    parent : QObject | None
        The parent object of the thread.

    Attributes
    ----------
    has_finished_signal : Signal
        Signal for emitting when the thread has finished.
    progress_bar_signal : Signal
        Signal for emitting the progress
        of the thread.
    """

    has_finished_signal = Signal()
    progress_bar_signal = Signal(int)

    def __init__(self, target, parent=None) -> None:
        super(PyQtThread, self).__init__(parent)

        self.t = target

    @Slot()
    def run(self):
        self.t()
        self.has_finished_signal.emit()

    def quit(self) -> None:
        self.exit(0)


class TrainingProtocol(QObject):
    """
    Class for handling the training protocol of the MyoGestic application.

    Parameters
    ----------
    parent : MyoGestic | None
        The parent object of the protocol object.

    Attributes
    ----------
    main_window : MyoGestic
        The main window of the MyoGestic application.
    model_interface : MyoGesticModelInterface
        Interface for the models.
    selected_recordings : dict[str, dict]
        Dictionary for the selected recordings.
    selected_dataset_filepath : dict[str, np.ndarray]
        Dictionary for the selected dataset file path.
    create_dataset_thread : PyQtThread
        Thread for creating a dataset.
    train_model_thread : PyQtThread
        Thread for training a models.
    """

    def __init__(self, parent: MyoGestic | None = ...) -> None:
        super().__init__(parent)

        self.main_window = parent

        # Initialize Protocol UI
        self._setup_protocol_ui()

        # Initialize Protocol
        self.selected_recordings: dict[str, dict] = None
        self.selected_dataset_filepath: dict[str, np.ndarray] = None

        # Model interface
        self.model_interface = None

        self.selected_model_name = list(CONFIG_REGISTRY.models_map.keys())[0]
        self.selected_model, self.model_is_classifier = CONFIG_REGISTRY.models_map[
            self.selected_model_name
        ]
        self.model_changeable_parameters = {}
        self.selected_features = [list(CONFIG_REGISTRY.features_map.keys())[0]]

        # Get configuration update
        self.main_window.device_widget.configure_toggled.connect(
            self._update_device_configuration
        )

        # Threads
        self.create_dataset_thread = None
        self.train_model_thread = None

        # File management:
        RECORDING_DIR_PATH.mkdir(parents=True, exist_ok=True)
        MODELS_DIR_PATH.mkdir(parents=True, exist_ok=True)
        DATASETS_DIR_PATH.mkdir(parents=True, exist_ok=True)

    def _update_device_configuration(self, is_configured: bool) -> None:
        if not is_configured:
            return
        self.model_interface = MyoGesticModelInterface(
            device_information=self.main_window.device_widget.get_device_information(),
            logger=self.main_window.logger,
        )

    def _check_if_recordings_selected(self) -> None:
        if (
            not self.training_create_dataset_selected_recordings_table_widget.selectedItems()
        ):
            self.training_remove_selected_recording_push_button.setEnabled(False)
        else:
            self.training_remove_selected_recording_push_button.setEnabled(True)

    def _remove_selected_recording(self) -> None:
        selected_rows = list(
            set(
                index.row()
                for index in self.training_create_dataset_selected_recordings_table_widget.selectedIndexes()
            )
        )
        for row in selected_rows[::-1]:
            self.training_create_dataset_selected_recordings_table_widget.removeRow(row)
        self._check_if_recordings_selected()

    def _remove_all_selected_recordings(self) -> None:
        self.training_create_dataset_selected_recordings_table_widget.setRowCount(0)
        self._check_if_recordings_selected()

    def select_recordings(self) -> None:
        self.training_create_dataset_push_button.setEnabled(False)

        # Open dialog to select recordings
        dialog = QFileDialog(self.main_window)
        dialog.setFileMode(QFileDialog.ExistingFiles)
        dialog.setNameFilter("Pickle files (*.pkl)")
        dialog.setDirectory(str(RECORDING_DIR_PATH))

        filenames, _ = dialog.getOpenFileNames()
        self.selected_recordings = {}
        self.training_create_dataset_selected_recordings_table_widget.setRowCount(0)

        for file in filenames:
            with open(file, "rb") as f:
                recording: dict = pickle.load(f)

                if not recording:
                    continue

                if not isinstance(recording, dict):
                    continue

                keys = recording.keys()

                required_keys = [
                    "emg",
                    "kinematics",
                    "timings_kinematics",
                    "timings_emg",
                    "label",
                    "task",
                    "device",
                    "bad_channels",
                ]

                if not all(key in keys for key in required_keys):
                    self.main_window.logger.print(
                        f" {f} is an invalid recording! \n Missing keys: {set(required_keys) - set(keys)}",
                        LoggerLevel.ERROR,
                    )
                    continue

                if recording["device"] != self.main_window.device_name:
                    self.main_window.logger.print(
                        f" {f} is not recorded with the current device! \n Please select {recording['device']}.",
                        LoggerLevel.ERROR,
                    )
                    continue

                selected_recordings_key = recording["task"].capitalize()
                if selected_recordings_key in self.selected_recordings.keys():
                    current_recording = self.selected_recordings[
                        selected_recordings_key
                    ]

                    recording["emg"] = np.hstack(
                        [current_recording["emg"], recording["emg"]]
                    )
                    recording["kinematics"] = np.concatenate(
                        [current_recording["kinematics"], recording["kinematics"]],
                        axis=-1,
                    )
                    recording["timings_kinematics"] = np.concatenate(
                        [
                            current_recording["timings_kinematics"],
                            recording["timings_kinematics"],
                        ]
                    )
                    recording["timings_emg"] = np.concatenate(
                        [current_recording["timings_emg"], recording["timings_emg"]]
                    )

                    recording["label"] += "; " + current_recording["label"]

                    recording["bad_channels"].extend(current_recording["bad_channels"])
                    recording["bad_channels"] = list(
                        set([item for item in recording["bad_channels"]])
                    )

                    recording["use_kinematics"] = (
                        recording["use_kinematics"]
                        and current_recording["use_kinematics"]
                    )

                self.selected_recordings[selected_recordings_key] = recording

        if len(self.selected_recordings) == 0:
            self._open_warning_dialog("No valid recordings selected!")
            return

        for key, item in self.selected_recordings.items():
            row_position = (
                self.training_create_dataset_selected_recordings_table_widget.rowCount()
            )
            self.training_create_dataset_selected_recordings_table_widget.insertRow(
                row_position
            )

            # Insert new recording
            recording_time = int(
                item["emg"].shape[1] / self.main_window.sampling_frequency
            )

            self.training_create_dataset_selected_recordings_table_widget.setItem(
                row_position, 0, QTableWidgetItem(key)
            )
            self.training_create_dataset_selected_recordings_table_widget.setItem(
                row_position, 1, QTableWidgetItem(str(recording_time))
            )
            self.training_create_dataset_selected_recordings_table_widget.setItem(
                row_position, 2, QTableWidgetItem(item["label"])
            )

        self.training_create_dataset_push_button.setEnabled(True)

    def _create_dataset(self) -> None:
        if not self.selected_recordings:
            self._open_warning_dialog("No recordings selected!")
        self.training_create_dataset_push_button.setEnabled(False)
        self.training_create_datasets_select_recordings_push_button.setEnabled(False)

        self.create_dataset_thread = PyQtThread(
            target=self._create_dataset_thread, parent=self.main_window
        )
        self.create_dataset_thread.has_finished_signal.connect(
            self.__create_dataset_thread_finished
        )
        self.create_dataset_thread.start()

    def __create_dataset_thread_finished(self) -> None:
        self.training_create_dataset_selected_recordings_table_widget.setRowCount(0)
        self.training_create_dataset_label_line_edit.setText("")
        self.training_create_datasets_select_recordings_push_button.setEnabled(True)
        self.selected_recordings = None
        self.main_window.logger.print(f"Dataset created!", LoggerLevel.INFO)

    def _create_dataset_thread(self) -> None:
        label = self.training_create_dataset_label_line_edit.text()
        if not label:
            label = "default"

        now = datetime.now()
        formatted_now = now.strftime("%Y%m%d_%H%M%S%f")

        file_name = f"MindMove_Dataset_{formatted_now}_{label.lower()}"

        dataset_dict = self.model_interface.create_dataset(
            self.selected_recordings, self.selected_features, file_name
        )

        dataset_dict["dataset_file_path"] = str(DATASETS_DIR_PATH / f"{file_name}.pkl")

        with (DATASETS_DIR_PATH / f"{file_name}.pkl").open("wb") as f:
            pickle.dump(dataset_dict, f)

    def _select_dataset(self) -> None:
        # Open dialog to select dataset
        dialog = QFileDialog(self.main_window)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Pickle files (*.pkl)")
        dialog.setDirectory(str(DATASETS_DIR_PATH))

        filename, _ = dialog.getOpenFileName()

        if not filename:
            self._open_warning_dialog(NO_DATASET_SELECTED_INFO)
            self.training_selected_dataset_label.setText(NO_DATASET_SELECTED_INFO)
            return

        self.selected_dataset_filepath = filename
        self.training_selected_dataset_label.setText(
            self.selected_dataset_filepath.split("_")[-1].replace(".pkl", "").title()
        )

        self.train_model_push_button.setEnabled(True)

    def _open_warning_dialog(self, info: str) -> None:
        QMessageBox.warning(self.main_window, "Warning", info, QMessageBox.Ok)

    def _train_model(self) -> None:
        if not self.selected_dataset_filepath:
            self._open_warning_dialog(NO_DATASET_SELECTED_INFO)
            return

        self.train_model_push_button.setEnabled(False)
        self.training_select_dataset_push_button.setEnabled(False)

        self.train_model_thread = PyQtThread(
            target=self._train_model_thread, parent=self.main_window
        )
        self.train_model_thread.has_finished_signal.connect(self._train_model_finished)
        self.train_model_thread.start()

    def _train_model_thread(self) -> None:
        label = self.training_model_label_line_edit.text()
        if not label:
            label = "default"

        assert self.selected_dataset_filepath is not None

        with open(self.selected_dataset_filepath, "rb") as file:
            dataset = pickle.load(file)

        if len(self.model_changeable_parameters) == 0:
            self.model_changeable_parameters = {
                key: value["default_value"]
                for key, value in CONFIG_REGISTRY.models_parameters_map[
                    self.selected_model_name
                ]["changeable"].items()
            }

        try:
            func_map = CONFIG_REGISTRY.models_functions_map[self.selected_model_name]

            train = func_map["train"]
            save = func_map["save"]
            load = func_map["load"]

            self.model_interface.train_model(
                dataset=dataset,
                model_name=self.selected_model_name,
                model_parameters={
                    **CONFIG_REGISTRY.models_parameters_map[self.selected_model_name][
                        "unchangeable"
                    ],
                    **self.model_changeable_parameters,
                },
                selected_features=dataset["selected_features"],
                save=save,
                load=load,
                train=train,
            )
        except Exception as e:
            self.main_window.logger.print(
                f"Error during training: {e}", LoggerLevel.ERROR
            )
            return

        now = datetime.now()
        formatted_now = now.strftime("%Y%m%d_%H%M%S%f")

        file_name = f"MindMove_Model_{formatted_now}_{label.lower()}.pkl"

        model_filepath = MODELS_DIR_PATH / file_name

        try:
            model_save_dict = self.model_interface.save_model(model_filepath)
        except Exception as e:
            self.main_window.logger.print(
                f"Error during saving models: {e}", LoggerLevel.ERROR
            )
            return

        with model_filepath.open("wb") as file:
            pickle.dump(model_save_dict, file)

    def _train_model_finished(self) -> None:
        self.training_selected_dataset_label.setText(NO_DATASET_SELECTED_INFO)
        self.training_select_dataset_push_button.setEnabled(True)
        self.selected_dataset_filepath = None
        self.training_model_label_line_edit.setText("")
        self.main_window.logger.print(f"Model trained", LoggerLevel.INFO)

    def _update_model_selection(self) -> None:
        self.selected_model_name = self.training_model_selection_combo_box.currentText()
        self.selected_model, self.model_is_classifier = CONFIG_REGISTRY.models_map[
            self.selected_model_name
        ]

        self.model_changeable_parameters = {
            key: value["default_value"]
            for key, value in CONFIG_REGISTRY.models_parameters_map[
                self.selected_model_name
            ]["changeable"].items()
        }

        if len(self.model_changeable_parameters) > 0:
            self.training_model_parameters_push_button.setEnabled(True)
        else:
            self.training_model_parameters_push_button.setEnabled(False)

    def _open_model_parameters_popup(self) -> None:
        self.popup_window = PopupWindowParameters(self.selected_model_name)
        self.popup_window.show()
        self.popup_window.finished.connect(self._get_model_parameters)

    def _get_model_parameters(self) -> None:
        self.model_changeable_parameters = self.popup_window.model_changeable_parameters

    def _open_feature_selection_popup(self) -> None:
        self.popup_window = PopupWindowFeatures(self.selected_features)
        self.popup_window.show()
        self.popup_window.finished.connect(self._get_features)

    def _get_features(self) -> None:
        self.selected_features = list(self.popup_window.selected_features)

    def _setup_protocol_ui(self) -> None:
        # Create Datasets
        self.training_create_dataset_group_box = (
            self.main_window.ui.trainingCreateDatasetGroupBox
        )
        self.training_create_datasets_select_recordings_push_button = (
            self.main_window.ui.trainingCreateDatasetsSelectRecordingsPushButton
        )
        self.training_create_datasets_select_recordings_push_button.clicked.connect(
            self.select_recordings
        )

        # Table Widget for recordings
        self.training_create_dataset_selected_recordings_table_widget: QTableWidget = (
            self.main_window.ui.trainingCreateDatasetSelectedRecordingsTableWidget
        )
        self.training_create_dataset_selected_recordings_table_widget.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )
        self.training_create_dataset_selected_recordings_table_widget.itemSelectionChanged.connect(
            self._check_if_recordings_selected
        )

        self.training_create_dataset_selected_recordings_table_widget.verticalHeader().setVisible(
            False
        )
        header = (
            self.training_create_dataset_selected_recordings_table_widget.horizontalHeader()
        )
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        # Reset table
        self.training_create_dataset_selected_recordings_table_widget.setRowCount(0)

        self.training_remove_selected_recording_push_button: QPushButton = (
            self.main_window.ui.trainingRemoveSelectedRecordingPushButton
        )
        self.training_remove_selected_recording_push_button.clicked.connect(
            self._remove_selected_recording
        )
        self.training_remove_selected_recording_push_button.setEnabled(False)

        self.training_remove_all_selected_recordings_push_button: QPushButton = (
            self.main_window.ui.trainingRemoveAllSelectedRecordingsPushButton
        )
        self.training_remove_all_selected_recordings_push_button.clicked.connect(
            self._remove_all_selected_recordings
        )

        self.training_create_dataset_select_features_push_button = (
            self.main_window.ui.trainingCreateDatasetSelectFeaturesPushButton
        )
        self.training_create_dataset_select_features_push_button.clicked.connect(
            self._open_feature_selection_popup
        )

        self.training_create_dataset_label_line_edit = (
            self.main_window.ui.trainingCreateDatasetLabelLineEdit
        )
        self.training_create_dataset_push_button = (
            self.main_window.ui.trainingCreateDatasetPushButton
        )
        self.training_create_dataset_push_button.clicked.connect(self._create_dataset)
        self.training_create_dataset_push_button.setEnabled(False)

        # Train Model
        self.training_train_model_group_box = (
            self.main_window.ui.trainingTrainModelGroupBox
        )
        self.training_select_dataset_push_button = (
            self.main_window.ui.trainingSelectDatasetPushButton
        )
        self.training_select_dataset_push_button.clicked.connect(self._select_dataset)
        self.training_selected_dataset_label = (
            self.main_window.ui.trainingSelectedDatasetLabel
        )

        self.training_selected_dataset_label.setText(NO_DATASET_SELECTED_INFO)

        self.training_model_selection_combo_box = (
            self.main_window.ui.trainingModelSelectionComboBox
        )
        # set the models selection combo box
        self.training_model_selection_combo_box.addItems(
            list(CONFIG_REGISTRY.models_map.keys())
        )
        # connect the models selection combo box to the models selection function
        self.training_model_selection_combo_box.currentIndexChanged.connect(
            self._update_model_selection
        )

        self.training_model_selection_combo_box.setCurrentIndex(0)

        self.training_model_label_line_edit = (
            self.main_window.ui.trainingModelLabelLineEdit
        )

        self.training_model_parameters_push_button = (
            self.main_window.ui.trainingModelParametersPushButton
        )
        # connect the models parameters push button to the models parameters popup
        self.training_model_parameters_push_button.clicked.connect(
            self._open_model_parameters_popup
        )

        self.train_model_push_button = self.main_window.ui.trainingTrainModelPushButton
        self.train_model_push_button.clicked.connect(self._train_model)
        self.train_model_push_button.setEnabled(False)
