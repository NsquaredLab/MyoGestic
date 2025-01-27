from __future__ import annotations

import pickle
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Optional, Any

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
from myogestic.gui.widgets.logger import LoggerLevel, CustomLogger
from myogestic.gui.widgets.templates.visual_interface import VisualInterface

from myogestic.models.interface import MyoGesticModelInterface
from myogestic.utils.config import (
    UnchangeableParameter,
    CONFIG_REGISTRY,
    ChangeableParameter,
)
from myogestic.utils.constants import (
    RECORDING_DIR_PATH,
    MODELS_DIR_PATH,
    DATASETS_DIR_PATH,
    NO_DATASET_SELECTED_INFO,
    REQUIRED_RECORDING_KEYS,
)

if TYPE_CHECKING:
    from myogestic.gui.myogestic import MyoGestic


class PopupWindowParameters(QDialog):
    """
    Class for the popup window for the model parameters.

    Parameters
    ----------
    selected_model_name : str
        The selected model name.
    logger : CustomLogger
        The logger object from the main window.

    Attributes
    ----------
    model_changeable_parameters : dict[str, ChangeableParameter]
        Dictionary for the model changeable parameters.

    """

    def __init__(self, selected_model_name: str, logger: CustomLogger):
        super().__init__()

        self.model_changeable_parameters: dict[str, ChangeableParameter] = {}
        self._logger = logger

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
        self._logger.print(
            f"Parameter {parameter_name} changed to {value}", LoggerLevel.INFO
        )


class PopupWindowFeatures(QDialog):
    def __init__(self, selected_features: list[str]):
        super().__init__()

        self.selected_visual_interface: Optional[VisualInterface] = None

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

        for feature in CONFIG_REGISTRY.features_map.keys():
            feature_checkbox = QCheckBox(feature)
            self.checkboxes.append(feature_checkbox)
            self.scroll_area_layout.addWidget(feature_checkbox)
            if feature in self.selected_features:
                feature_checkbox.setChecked(True)

            feature_checkbox.checkStateChanged.connect(
                partial(self._on_change, feature)
            )

        self.scroll_area_widget.setLayout(self.scroll_area_layout)
        self.scroll_area.setWidget(self.scroll_area_widget)
        layout.addWidget(self.scroll_area)

        self.setLayout(layout)

    def _recheck_checkboxes(self):
        for checkbox in self.checkboxes:
            if checkbox.text() in self.selected_features:
                checkbox.setCheckState(Qt.CheckState.Checked)

    def _on_change(self, feature_name: str, state) -> None:
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
    main_window : MyoGestic
        The main window of the MyoGestic application.

    Attributes
    ----------
    _main_window : MyoGestic
        The main window of the MyoGestic application.
    _model_interface : MyoGesticModelInterface
        Interface for the models.
    _selected_recordings__dict : dict[str, dict]
        Dictionary for the selected recordings.
    _selected_dataset__filepath : dict[str, np.ndarray]
        Dictionary for the selected dataset file path.
    _create_dataset__thread : PyQtThread
        Thread for creating a dataset.
    _train_model__thread : PyQtThread
        Thread for training a models.
    """

    def __init__(self, main_window: MyoGestic) -> None:
        super().__init__(main_window)

        self._main_window = main_window

        # Initialize Protocol UI
        self._setup_protocol_ui()

        # Initialize Protocol
        self._selected_recordings__dict: dict[str, dict] | None = None
        self._selected_dataset__filepath: str | None = None

        self._selected_visual_interface: Optional[VisualInterface] = None

        # Model interface
        self._model_interface: MyoGesticModelInterface | None = None
        self._current_device_information: dict[str, Any] | None = None

        self._selected_model_name: str = list(CONFIG_REGISTRY.models_map.keys())[0]
        self._model_changeable_parameters__dict = {}
        self._selected_features__list: list[str] = [
            list(CONFIG_REGISTRY.features_map.keys())[0]
        ]

        # Get configuration update
        # self._main_window.device__widget.configure_toggled.connect(
        #     self._update_device_configuration
        # )

        # Threads
        self._create_dataset__thread: PyQtThread | None = None
        self._train_model__thread: PyQtThread | None = None

        # File management:
        RECORDING_DIR_PATH.mkdir(parents=True, exist_ok=True)
        MODELS_DIR_PATH.mkdir(parents=True, exist_ok=True)
        DATASETS_DIR_PATH.mkdir(parents=True, exist_ok=True)

    def _check_if_recordings_selected(self) -> None:
        if (
            not self.training_create_dataset_selected_recordings_table_widget.selectedItems()
        ):
            self.training_remove_selected_recording_push_button.setEnabled(False)
        else:
            self.training_remove_selected_recording_push_button.setEnabled(True)

    def _remove_selected_recording(self) -> None:
        for row in reversed(
            list(
                set(
                    index.row()
                    for index in self.training_create_dataset_selected_recordings_table_widget.selectedIndexes()
                )
            )
        ):
            self.training_create_dataset_selected_recordings_table_widget.removeRow(row)
        self._check_if_recordings_selected()

    def _remove_all_selected_recordings(self) -> None:
        self.training_create_dataset_selected_recordings_table_widget.setRowCount(0)
        self._check_if_recordings_selected()

    def select_recordings(self) -> None:
        self.training_create_dataset_push_button.setEnabled(False)

        # Open dialog to select recordings
        dialog = QFileDialog(self._main_window)
        dialog.setFileMode(QFileDialog.ExistingFiles)
        dialog.setNameFilter("Pickle files (*.pkl)")
        dialog.setDirectory(str(RECORDING_DIR_PATH))

        self._selected_recordings__dict = {}
        self.training_create_dataset_selected_recordings_table_widget.setRowCount(0)

        for file in dialog.getOpenFileNames()[0]:
            with open(file, "rb") as f:
                recording: dict = pickle.load(f)

                if not recording or not isinstance(recording, dict):
                    continue

                keys = recording.keys()

                missing_keys = REQUIRED_RECORDING_KEYS - set(keys)
                if missing_keys:
                    self._main_window.logger.print(
                        f" {f} is an invalid recording! \n Missing keys: {missing_keys}",
                        LoggerLevel.ERROR,
                    )
                    continue

                # if recording["device"] != self._main_window._device_name:
                #     self._main_window.logger.print(
                #         f" {f} is not recorded with the current device! \n Please select {recording['device']}.",
                #         LoggerLevel.ERROR,
                #     )
                #     continue

                selected_recordings_key = recording["task"].capitalize()
                if selected_recordings_key in self._selected_recordings__dict.keys():
                    current_recording = self._selected_recordings__dict[
                        selected_recordings_key
                    ]

                    recording["biosignal"] = np.concatenate(
                        [current_recording["biosignal"], recording["biosignal"]],
                        axis=-1,
                    )
                    recording["ground_truth"] = np.concatenate(
                        [current_recording["ground_truth"], recording["ground_truth"]],
                        axis=-1,
                    )
                    recording["biosignal_timings"] = np.concatenate(
                        [
                            current_recording["biosignal_timings"],
                            recording["biosignal_timings"],
                        ]
                    )
                    recording["ground_truth_timings"] = np.concatenate(
                        [
                            current_recording["ground_truth_timings"],
                            recording["ground_truth_timings"],
                        ]
                    )

                    recording["recording_label"] += (
                        "; " + current_recording["recording_label"]
                    )

                    recording["bad_channels"].extend(current_recording["bad_channels"])
                    recording["bad_channels"] = list(
                        set([item for item in recording["bad_channels"]])
                    )

                    recording["use_as_classification"] = (
                        recording["use_as_classification"]
                        and current_recording["use_as_classification"]
                    )

                    if (
                        recording["ground_truth_sampling_frequency"]
                        != current_recording["ground_truth_sampling_frequency"]
                    ):
                        self._open_warning_dialog(
                            "Recordings have different ground truth sampling frequencies!"
                        )
                        continue

                    if (
                        recording["device_information"]
                        != current_recording["device_information"]
                    ):
                        self._open_warning_dialog(
                            "Recordings are not from the same device!"
                        )
                        continue

                    recording["recording_time"] += current_recording["recording_time"]

                    recording["task"] = selected_recordings_key

                self._selected_recordings__dict[selected_recordings_key] = recording

        if len(self._selected_recordings__dict) == 0:
            self._open_warning_dialog("No valid recordings selected!")
            return

        for i, (_, item) in enumerate(self._selected_recordings__dict.items()):
            if i == 0:
                self._current_device_information = item["device_information"]

            if item["device_information"] != self._current_device_information:
                self._open_warning_dialog("Recordings are not from the same device!")
                self._selected_recordings__dict = {}
                self.training_create_dataset_push_button.setEnabled(False)

        self._model_interface = MyoGesticModelInterface(
            device_information=self._current_device_information,
            logger=self._main_window.logger,
        )

        for key, item in self._selected_recordings__dict.items():
            row_position = (
                self.training_create_dataset_selected_recordings_table_widget.rowCount()
            )
            self.training_create_dataset_selected_recordings_table_widget.insertRow(
                row_position
            )

            self.training_create_dataset_selected_recordings_table_widget.setItem(
                row_position, 0, QTableWidgetItem(key)
            )
            self.training_create_dataset_selected_recordings_table_widget.setItem(
                row_position,
                1,
                QTableWidgetItem(
                    f"{((item['biosignal'].shape[-1] * item['biosignal'].shape[-2]) / item['device_information']['sampling_frequency']):.2f} s"
                ),
            )
            self.training_create_dataset_selected_recordings_table_widget.setItem(
                row_position, 2, QTableWidgetItem(item["recording_label"])
            )

        self.training_create_dataset_push_button.setEnabled(True)

    def _create_dataset(self) -> None:
        if not self._selected_recordings__dict:
            self._open_warning_dialog("No recordings selected!")
        self.training_create_dataset_push_button.setEnabled(False)
        self.training_create_datasets_select_recordings_push_button.setEnabled(False)

        self._create_dataset__thread = PyQtThread(
            target=self._create_dataset_thread, parent=self._main_window
        )
        self._create_dataset__thread.has_finished_signal.connect(
            self.__create_dataset_thread_finished
        )
        self._create_dataset__thread.start()

    def __create_dataset_thread_finished(self) -> None:
        self.training_create_dataset_selected_recordings_table_widget.setRowCount(0)
        self.training_create_dataset_label_line_edit.setText("")
        self.training_create_datasets_select_recordings_push_button.setEnabled(True)
        self._selected_recordings__dict = None
        self._main_window.logger.print("Dataset created!", LoggerLevel.INFO)

    def _create_dataset_thread(self) -> None:
        label = self.training_create_dataset_label_line_edit.text()
        if not label:
            label = "default"

        file_name = f"{self._selected_visual_interface.name}_Dataset_{datetime.now().strftime("%Y%m%d_%H%M%S%f")}_{label.lower()}"

        dataset_dict = self._model_interface.create_dataset(
            self._selected_recordings__dict, self._selected_features__list, file_name
        )

        dataset_dict["dataset_file_path"] = str(DATASETS_DIR_PATH / f"{file_name}.pkl")
        dataset_dict["device_information"] = self._current_device_information

        with (DATASETS_DIR_PATH / f"{file_name}.pkl").open("wb") as f:
            pickle.dump(dataset_dict, f)

    def _select_dataset(self) -> None:
        # Open dialog to select dataset
        dialog = QFileDialog(self._main_window)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Pickle files (*.pkl)")
        dialog.setDirectory(str(DATASETS_DIR_PATH))

        filename, _ = dialog.getOpenFileName()

        if not filename:
            self._open_warning_dialog(NO_DATASET_SELECTED_INFO)
            self.training_selected_dataset_label.setText(NO_DATASET_SELECTED_INFO)
            return

        self._selected_dataset__filepath = filename
        self.training_selected_dataset_label.setText(
            self._selected_dataset__filepath.split("_")[-1].replace(".pkl", "").title()
        )

        self.train_model_push_button.setEnabled(True)

    def _open_warning_dialog(self, info: str) -> None:
        QMessageBox.warning(self._main_window, "Warning", info, QMessageBox.Ok)

    def _train_model(self) -> None:
        if not self._selected_dataset__filepath:
            self._open_warning_dialog(NO_DATASET_SELECTED_INFO)
            return

        self.train_model_push_button.setEnabled(False)
        self.training_select_dataset_push_button.setEnabled(False)

        self._train_model__thread = PyQtThread(
            target=self._train_model_thread, parent=self._main_window
        )
        self._train_model__thread.has_finished_signal.connect(
            self._train_model_finished
        )
        self._train_model__thread.start()

    def _train_model_thread(self) -> None:
        label = self.training_model_label_line_edit.text()
        if not label:
            label = "default"

        assert self._selected_dataset__filepath is not None

        with open(self._selected_dataset__filepath, "rb") as file:
            dataset = pickle.load(file)

        if len(self._model_changeable_parameters__dict) == 0:
            self._model_changeable_parameters__dict = {
                key: value["default_value"]
                for key, value in CONFIG_REGISTRY.models_parameters_map[
                    self._selected_model_name
                ]["changeable"].items()
            }

        if not self._model_interface:
            self._current_device_information = dataset["device_information"]

            self._model_interface = MyoGesticModelInterface(
                device_information=self._current_device_information,
                logger=self._main_window.logger,
            )

        try:
            func_map = CONFIG_REGISTRY.models_functions_map[self._selected_model_name]

            self._model_interface.train_model(
                dataset=dataset,
                model_name=self._selected_model_name,
                model_parameters={
                    **CONFIG_REGISTRY.models_parameters_map[self._selected_model_name][
                        "unchangeable"
                    ],
                    **self._model_changeable_parameters__dict,
                },
                selected_features=dataset["selected_features"],
                save=func_map["save"],
                load=func_map["load"],
                train=func_map["train"],
            )
        except Exception as e:
            self._main_window.logger.print(
                f"Error during training: {e}", LoggerLevel.ERROR
            )
            return

        file_name = f"{self._selected_visual_interface.name}_Model_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{label.lower()}.pkl"

        model_filepath = MODELS_DIR_PATH / file_name

        try:
            model_save_dict = self._model_interface.save_model(model_filepath)
        except Exception as e:
            self._main_window.logger.print(
                f"Error during saving model: {e}", LoggerLevel.ERROR
            )
            return

        with model_filepath.open("wb") as file:
            pickle.dump(model_save_dict, file)

    def _train_model_finished(self) -> None:
        self.training_selected_dataset_label.setText(NO_DATASET_SELECTED_INFO)
        self.training_select_dataset_push_button.setEnabled(True)
        self._selected_dataset__filepath = None
        self.training_model_label_line_edit.setText("")
        self._main_window.logger.print("Model trained", LoggerLevel.INFO)

    def _update_model_selection(self) -> None:
        self._selected_model_name = (
            self.training_model_selection_combo_box.currentText()
        )

        self._model_changeable_parameters__dict = {
            key: value["default_value"]
            for key, value in CONFIG_REGISTRY.models_parameters_map[
                self._selected_model_name
            ]["changeable"].items()
        }

        if len(self._model_changeable_parameters__dict) > 0:
            self.training_model_parameters_push_button.setEnabled(True)
        else:
            self.training_model_parameters_push_button.setEnabled(False)

    def _open_model_parameters_popup(self) -> None:
        self.popup_window = PopupWindowParameters(
            self._selected_model_name, self._main_window.logger
        )
        self.popup_window.show()
        self.popup_window.finished.connect(self._get_model_parameters)

    def _get_model_parameters(self) -> None:
        self._model_changeable_parameters__dict = (
            self.popup_window.model_changeable_parameters
        )

    def _open_feature_selection_popup(self) -> None:
        self.popup_window = PopupWindowFeatures(self._selected_features__list)
        self.popup_window.show()
        self.popup_window.finished.connect(self._get_features)

    def _get_features(self) -> None:
        self._selected_features__list = list(self.popup_window.selected_features)

    def closeEvent(self, event) -> None:
        self._main_window.logger.print("Training Protocol Closed", LoggerLevel.INFO)

    def _setup_protocol_ui(self) -> None:
        # Create Datasets
        self.training_create_dataset_group_box = (
            self._main_window.ui.trainingCreateDatasetGroupBox
        )
        self.training_create_datasets_select_recordings_push_button = (
            self._main_window.ui.trainingCreateDatasetsSelectRecordingsPushButton
        )
        self.training_create_datasets_select_recordings_push_button.clicked.connect(
            self.select_recordings
        )

        # Table Widget for recordings
        self.training_create_dataset_selected_recordings_table_widget: QTableWidget = (
            self._main_window.ui.trainingCreateDatasetSelectedRecordingsTableWidget
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
            self._main_window.ui.trainingRemoveSelectedRecordingPushButton
        )
        self.training_remove_selected_recording_push_button.clicked.connect(
            self._remove_selected_recording
        )
        self.training_remove_selected_recording_push_button.setEnabled(False)

        self.training_remove_all_selected_recordings_push_button: QPushButton = (
            self._main_window.ui.trainingRemoveAllSelectedRecordingsPushButton
        )
        self.training_remove_all_selected_recordings_push_button.clicked.connect(
            self._remove_all_selected_recordings
        )

        self.training_create_dataset_select_features_push_button = (
            self._main_window.ui.trainingCreateDatasetSelectFeaturesPushButton
        )
        self.training_create_dataset_select_features_push_button.clicked.connect(
            self._open_feature_selection_popup
        )

        self.training_create_dataset_label_line_edit = (
            self._main_window.ui.trainingCreateDatasetLabelLineEdit
        )
        self.training_create_dataset_push_button = (
            self._main_window.ui.trainingCreateDatasetPushButton
        )
        self.training_create_dataset_push_button.clicked.connect(self._create_dataset)
        self.training_create_dataset_push_button.setEnabled(False)

        # Train Model
        self.training_train_model_group_box = (
            self._main_window.ui.trainingTrainModelGroupBox
        )
        self.training_select_dataset_push_button = (
            self._main_window.ui.trainingSelectDatasetPushButton
        )
        self.training_select_dataset_push_button.clicked.connect(self._select_dataset)
        self.training_selected_dataset_label = (
            self._main_window.ui.trainingSelectedDatasetLabel
        )

        self.training_selected_dataset_label.setText(NO_DATASET_SELECTED_INFO)

        self.training_model_selection_combo_box = (
            self._main_window.ui.trainingModelSelectionComboBox
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
            self._main_window.ui.trainingModelLabelLineEdit
        )

        self.training_model_parameters_push_button = (
            self._main_window.ui.trainingModelParametersPushButton
        )
        # connect the models parameters push button to the models parameters popup
        self.training_model_parameters_push_button.clicked.connect(
            self._open_model_parameters_popup
        )

        self.train_model_push_button = self._main_window.ui.trainingTrainModelPushButton
        self.train_model_push_button.clicked.connect(self._train_model)
        self.train_model_push_button.setEnabled(False)
