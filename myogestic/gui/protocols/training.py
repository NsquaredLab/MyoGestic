from __future__ import annotations

import pickle
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Optional, Any

import numpy as np
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QStandardItem, QStandardItemModel
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
    QWidget, )

from myogestic.gui.widgets.highlighter import WidgetHighlighter
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
    def __init__(self, selected_features: list[str], model_name: str):
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

        # Get model's temporal preservation requirement
        model_requires_temporal = CONFIG_REGISTRY.models_metadata_map.get(
            model_name, {}
        ).get("requires_temporal_preservation", False)

        # Filter features based on model compatibility
        for feature in CONFIG_REGISTRY.features_map.keys():
            feature_requires_temporal = CONFIG_REGISTRY.features_metadata_map.get(
                feature, {}
            ).get("requires_temporal_preservation", False)

            # Only show features that match the model's temporal requirement
            # - If model requires temporal preservation: show only temporal features
            # - If model doesn't require temporal preservation: show only non-temporal features
            if feature_requires_temporal != model_requires_temporal:
                continue

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

        # Initialize Protocol
        self._selected_recordings__dict: dict[str, dict] | None = None
        self._selected_dataset__filepath: str | None = None

        self._selected_visual_interface: Optional[VisualInterface] = None
        self._active_visual_interfaces: dict[str, VisualInterface] = {}

        # Model interface
        self._model_interface: MyoGesticModelInterface | None = None
        self._current_device_information: dict[str, Any] | None = None

        # Default to CatBoost if available, otherwise first model
        available_models = list(CONFIG_REGISTRY.models_map.keys())
        self._selected_model_name: str = (
            "CatBoost" if "CatBoost" in available_models else available_models[0]
        )
        self._model_changeable_parameters__dict = {}

        # Initialize Protocol UI (after model name is set)
        self._setup_protocol_ui()

        # Select a default feature compatible with the initial model
        model_requires_temporal = CONFIG_REGISTRY.models_metadata_map.get(
            self._selected_model_name, {}
        ).get("requires_temporal_preservation", False)

        compatible_features = [
            name
            for name in CONFIG_REGISTRY.features_map.keys()
            if CONFIG_REGISTRY.features_metadata_map.get(name, {}).get(
                "requires_temporal_preservation", False
            )
            == model_requires_temporal
        ]
        self._selected_features__list: list[str] = (
            [compatible_features[0]] if compatible_features else []
        )

        # Get configuration update
        # self._main_window.device__widget.configure_toggled.connect(
        #     self._update_device_configuration
        # )

        # Threads
        self._create_dataset__thread: PyQtThread | None = None
        self._train_model__thread: PyQtThread | None = None

        # Task to movement mapping (if they are not the same):
        self._task_label_to_movement_map: dict = {}
        self._task_name_to_movement_map: dict = {}

        # File management:
        RECORDING_DIR_PATH.mkdir(parents=True, exist_ok=True)
        MODELS_DIR_PATH.mkdir(parents=True, exist_ok=True)
        DATASETS_DIR_PATH.mkdir(parents=True, exist_ok=True)

        # Visual workflow hints
        self._highlighter = WidgetHighlighter(self._main_window)
        self._last_trained_model_path: str | None = None

    def _check_if_recordings_selected(self) -> None:
        has_selection = bool(
            self.training_create_dataset_selected_recordings_table_widget.selectedItems()
        )
        self.training_remove_selected_recording_push_button.setEnabled(has_selection)

    def _remove_selected_recording(self) -> None:
        selected_rows = {
            index.row()
            for index in self.training_create_dataset_selected_recordings_table_widget.selectedIndexes()
        }
        for row in sorted(selected_rows, reverse=True):
            self.training_create_dataset_selected_recordings_table_widget.removeRow(row)
        self._check_if_recordings_selected()

    def _remove_all_selected_recordings(self) -> None:
        self.training_create_dataset_selected_recordings_table_widget.setRowCount(0)
        self._check_if_recordings_selected()

    def select_recordings(self) -> None:
        self.training_create_dataset_push_button.setEnabled(False)

        # Open dialog to select recordings
        dialog = QFileDialog(self._main_window)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.ExistingFiles)
        dialog.setNameFilter("Pickle files (*.pkl)")
        dialog.setDirectory(str(RECORDING_DIR_PATH))

        self._selected_recordings__dict = {}
        self.training_create_dataset_selected_recordings_table_widget.setRowCount(0)

        if not dialog.exec():
            return

        for file in dialog.selectedFiles():
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

                selected_recordings_key = recording["task"].capitalize()

                # Check if "movement" key is also included in the recording
                if "movement" in list(recording.keys()):
                    self._task_label_to_movement_map[recording["task_label_map"][recording["task"].lower()]] = recording["movement"].capitalize()
                    self._task_name_to_movement_map[recording["task"]] = recording["movement"].capitalize()
                else:
                    self._task_label_to_movement_map = None
                    self._task_name_to_movement_map = None

                if selected_recordings_key in self._selected_recordings__dict.keys():
                    current_recording = self._selected_recordings__dict[
                        selected_recordings_key
                    ]

                    recording["biosignal"] = np.concatenate(
                        [current_recording["biosignal"], recording["biosignal"]],
                        axis=-1,
                    )
                    # Ensure ground_truth arrays have consistent dimensions before concatenating
                    gt_current = current_recording["ground_truth"]
                    gt_new = recording["ground_truth"]
                    if gt_current.ndim == 1:
                        gt_current = gt_current[np.newaxis, :]
                    if gt_new.ndim == 1:
                        gt_new = gt_new[np.newaxis, :]
                    recording["ground_truth"] = np.concatenate(
                        [gt_current, gt_new],
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
                    recording["bad_channels"] = list(set(recording["bad_channels"]))

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

        # Clean up old model interface to avoid Qt timer threading issues
        if self._model_interface is not None:
            self._model_interface.deleteLater()
            self._model_interface = None

        self._model_interface = MyoGesticModelInterface(
            device_information=self._current_device_information,
            logger=self._main_window.logger,
            parent=self._main_window,
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

        # Populate ground truth source combo from recordings' visual interfaces
        all_vi_names: set[str] = set()
        for recording in self._selected_recordings__dict.values():
            vi_field = recording.get("visual_interface", "Default")
            if isinstance(vi_field, list):
                all_vi_names.update(vi_field)
            elif isinstance(vi_field, str):
                # Handle old format "VHI, KHI" or single "VHI"
                all_vi_names.update(v.strip() for v in vi_field.split(","))

        self._ground_truth_source_combo.clear()
        for vi_name in sorted(all_vi_names):
            self._ground_truth_source_combo.addItem(vi_name)

        self.training_create_dataset_push_button.setEnabled(True)

        # Highlight Select Features and Create Dataset buttons to guide user
        self._highlighter.highlight(self.training_create_dataset_select_features_push_button)
        self._highlighter.highlight(self.training_create_dataset_push_button)

    def _create_dataset(self) -> None:
        if not self._selected_recordings__dict:
            self._open_warning_dialog("No recordings selected!")
        self.training_create_dataset_push_button.setEnabled(False)
        self.training_create_datasets_select_recordings_push_button.setEnabled(False)

        self._create_dataset__thread = PyQtThread(
            target=self._create_dataset_thread, parent=self._main_window
        )
        self._create_dataset__thread.has_finished_signal.connect(
            self._create_dataset_thread_finished
        )
        self._create_dataset__thread.start()

    def _create_dataset_thread_finished(self) -> None:
        self.training_create_dataset_selected_recordings_table_widget.setRowCount(0)
        self.training_create_dataset_label_line_edit.setText("")
        self.training_create_datasets_select_recordings_push_button.setEnabled(True)
        self._selected_recordings__dict = None

        # Clear session recordings from Record protocol since they've been used
        record_protocol = self._main_window.protocols[0]
        if hasattr(record_protocol, "_session_recording_paths"):
            record_protocol._session_recording_paths.clear()

        # Auto-select the newly created dataset
        if hasattr(self, "_last_created_dataset_filepath"):
            self._selected_dataset__filepath = self._last_created_dataset_filepath
            self.training_selected_dataset_label.setText(
                self._last_created_dataset_label.title()
            )
            self.train_model_push_button.setEnabled(True)
            del self._last_created_dataset_filepath
            del self._last_created_dataset_label

            # Highlight the Train button to guide user to next step
            self._highlighter.highlight(self.train_model_push_button)

        self._main_window.logger.print("Dataset created!", LoggerLevel.INFO)

    def _create_dataset_thread(self) -> None:
        label = self.training_create_dataset_label_line_edit.text()
        if not label:
            label = "default"

        # Use the selected ground truth source VI
        ground_truth_source = self._ground_truth_source_combo.currentText()
        if not ground_truth_source:
            self._main_window.logger.print(
                "No ground truth source selected!", LoggerLevel.ERROR
            )
            return

        file_name = f"{ground_truth_source}_Dataset_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{label.lower()}"

        # Determine feature window size based on selected model
        # Models like RaulNet need smaller window sizes to preserve temporal dimension
        model_metadata = CONFIG_REGISTRY.models_metadata_map.get(
            self._selected_model_name, {}
        )
        feature_window_size = model_metadata.get("feature_window_size")  # None for sklearn

        dataset_dict = self._model_interface.create_dataset(
            self._selected_recordings__dict,
            self._selected_features__list,
            file_name,
            ground_truth_source,
            feature_window_size=feature_window_size,
        )

        dataset_dict["dataset_file_path"] = str(DATASETS_DIR_PATH / f"{file_name}.pkl")
        dataset_dict["device_information"] = self._current_device_information
        if self._task_label_to_movement_map is not None and self._task_name_to_movement_map is not None:
            dataset_dict["task_label_to_movement_map"] = self._task_label_to_movement_map
            dataset_dict["task_name_to_movement_map"] = self._task_name_to_movement_map

        dataset_filepath = DATASETS_DIR_PATH / f"{file_name}.pkl"
        with dataset_filepath.open("wb") as f:
            pickle.dump(dataset_dict, f)

        # Store for auto-selection after thread finishes
        self._last_created_dataset_filepath = str(dataset_filepath)
        self._last_created_dataset_label = label

    def _select_dataset(self) -> None:
        # Open dialog to select dataset
        dialog = QFileDialog(self._main_window)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Pickle files (*.pkl)")
        dialog.setDirectory(str(DATASETS_DIR_PATH))

        if not dialog.exec():
            self._open_warning_dialog(NO_DATASET_SELECTED_INFO)
            self.training_selected_dataset_label.setText(NO_DATASET_SELECTED_INFO)
            return

        filename = dialog.selectedFiles()[0] if dialog.selectedFiles() else ""

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

        # Create model interface on main thread if needed
        if self._model_interface is None:
            with open(self._selected_dataset__filepath, "rb") as file:
                dataset = pickle.load(file)
            self._current_device_information = dataset["device_information"]
            self._model_interface = MyoGesticModelInterface(
                device_information=self._current_device_information,
                logger=self._main_window.logger,
                parent=self._main_window,
            )

        self._train_model__thread = PyQtThread(
            target=self._train_model_thread, parent=self._main_window
        )
        self._train_model__thread.has_finished_signal.connect(
            self._train_model_finished
        )
        self._train_model__thread.start()

        # Highlight the Log tab to draw attention (without switching)
        self._highlighter.highlight_tab(
            self._main_window._tab__widget,
            self._main_window._tab__widget.indexOf(self._main_window.ui.loggingTab),
        )

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

        # dataset["visual_interface"] is now a single VI name (the ground truth source)
        dataset_vi = dataset["visual_interface"]
        if self._selected_visual_interface is None:
            self._selected_visual_interface = dataset_vi
        else:
            current_vi = getattr(self._selected_visual_interface, 'name', self._selected_visual_interface)
            # Normalize: old format may be comma-separated; new format is single string
            if isinstance(current_vi, list):
                current_vi = current_vi[0] if current_vi else ""
            if current_vi != dataset_vi:
                self._main_window.logger.print(
                    f"Visual interface {current_vi} is open, but the dataset is from {dataset_vi}!",
                    LoggerLevel.ERROR
                )
                return
        file_name = f"{dataset['visual_interface']}_Model_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{label.lower()}.pkl"

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

        # Store path for auto-loading after training completes
        self._last_trained_model_path = str(model_filepath)

    def _train_model_finished(self) -> None:
        self.training_selected_dataset_label.setText(NO_DATASET_SELECTED_INFO)
        self.training_select_dataset_push_button.setEnabled(True)
        self._selected_dataset__filepath = None
        self.training_model_label_line_edit.setText("")
        self._main_window.logger.print("Model trained", LoggerLevel.INFO)

        # Guide user to Online protocol with the trained model
        if self._last_trained_model_path:
            # Highlight the Protocol tab to guide user back
            protocol_tab_index = self._main_window._tab__widget.indexOf(
                self._main_window.ui.procotolWidget
            )
            self._highlighter.highlight_tab(
                self._main_window._tab__widget, protocol_tab_index
            )

            # Highlight the Online radio button
            self._highlighter.highlight(
                self._main_window.ui.protocolOnlineRadioButton
            )

            # Store the path so Online protocol can auto-load when user switches
            online_protocol = self._main_window.protocols[2]
            online_protocol._pending_model_path = self._last_trained_model_path

            self._last_trained_model_path = None

    def _update_model_selection(self) -> None:
        self._selected_model_name = self.training_model_selection_combo_box.currentText()

        self._model_changeable_parameters__dict = {
            key: value["default_value"]
            for key, value in CONFIG_REGISTRY.models_parameters_map[
                self._selected_model_name
            ]["changeable"].items()
        }

        has_parameters = bool(self._model_changeable_parameters__dict)
        self.training_model_parameters_push_button.setEnabled(has_parameters)

        # Reset selected features to the first compatible feature for the new model
        model_requires_temporal = CONFIG_REGISTRY.models_metadata_map.get(
            self._selected_model_name, {}
        ).get("requires_temporal_preservation", False)

        compatible_features = [
            name
            for name in CONFIG_REGISTRY.features_map.keys()
            if CONFIG_REGISTRY.features_metadata_map.get(name, {}).get(
                "requires_temporal_preservation", False
            )
            == model_requires_temporal
        ]

        if compatible_features:
            self._selected_features__list = [compatible_features[0]]
        else:
            self._selected_features__list = []

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
        self.popup_window = PopupWindowFeatures(
            self._selected_features__list, self._selected_model_name
        )
        self.popup_window.show()
        self.popup_window.finished.connect(self._get_features)

    def _get_features(self) -> None:
        self._selected_features__list = list(self.popup_window.selected_features)

    def close_event(self, event) -> None:
        self._main_window.logger.print("Training Protocol Closed", LoggerLevel.INFO)

    def _setup_protocol_ui(self) -> None:
        # 1. Select Model (first section - model determines feature window size)
        self.training_model_selection_group_box = (
            self._main_window.ui.trainingModelSelectionGroupBox
        )
        self.training_model_selection_combo_box = (
            self._main_window.ui.trainingModelSelectionComboBox
        )

        # Create a model with groups (regressors and classifiers)
        model = QStandardItemModel()

        # Separate models into groups
        regressors = []
        classifiers = []
        for name, (_, is_classifier) in CONFIG_REGISTRY.models_map.items():
            if is_classifier:
                classifiers.append(name)
            else:
                regressors.append(name)

        # Add Regressors group
        if regressors:
            header = QStandardItem("── Regressors ──")
            header.setEnabled(False)  # Non-selectable
            model.appendRow(header)
            for name in regressors:
                model.appendRow(QStandardItem(name))

        # Add Classifiers group
        if classifiers:
            header = QStandardItem("── Classifiers ──")
            header.setEnabled(False)  # Non-selectable
            model.appendRow(header)
            for name in classifiers:
                model.appendRow(QStandardItem(name))

        self.training_model_selection_combo_box.setModel(model)

        # Initialize button before connecting signal (signal triggers _update_model_selection)
        self.training_model_parameters_push_button = (
            self._main_window.ui.trainingModelParametersPushButton
        )
        self.training_model_parameters_push_button.clicked.connect(
            self._open_model_parameters_popup
        )

        self.training_model_selection_combo_box.currentIndexChanged.connect(
            self._update_model_selection
        )

        # Set default model to CatBoost if available, otherwise first model
        default_index = 1  # First actual model (skip header)
        for i in range(model.rowCount()):
            item = model.item(i)
            if item and item.text() == self._selected_model_name:
                default_index = i
                break
        self.training_model_selection_combo_box.setCurrentIndex(default_index)

        # 2. Create Datasets
        self.training_create_dataset_group_box = (
            self._main_window.ui.trainingCreateDatasetGroupBox
        )
        self.training_create_datasets_select_recordings_push_button = (
            self._main_window.ui.trainingCreateDatasetsSelectRecordingsPushButton
        )
        self.training_create_datasets_select_recordings_push_button.setToolTip(
            "Select recording files (.pkl) to include in the dataset"
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
        self.training_create_dataset_select_features_push_button.setToolTip(
            "Choose which EMG features to extract for the model"
        )
        self.training_create_dataset_select_features_push_button.clicked.connect(
            self._open_feature_selection_popup
        )

        # Ground Truth Source selector (for multi-VI recordings)
        self._ground_truth_source_label = QLabel("Ground Truth Source:")
        self._ground_truth_source_combo = QComboBox()
        self._ground_truth_source_combo.setToolTip(
            "Select which visual interface's ground truth to use for dataset creation"
        )
        # Insert into the dataset group box grid layout at a new row
        dataset_grid = self._main_window.ui.gridLayout_13
        # Shift existing rows down: label_6 (row 3), label line edit (row 3),
        # features button (row 4), create button (row 4) → move to rows 4, 5
        dataset_grid.addWidget(self._ground_truth_source_label, 3, 0, 1, 1)
        dataset_grid.addWidget(self._ground_truth_source_combo, 3, 1, 1, 1)
        dataset_grid.addWidget(self._main_window.ui.label_6, 4, 0, 1, 1)
        dataset_grid.addWidget(self._main_window.ui.trainingCreateDatasetLabelLineEdit, 4, 1, 1, 1)
        dataset_grid.addWidget(self._main_window.ui.trainingCreateDatasetSelectFeaturesPushButton, 5, 0, 1, 1)
        dataset_grid.addWidget(self._main_window.ui.trainingCreateDatasetPushButton, 5, 1, 1, 1)

        self.training_create_dataset_label_line_edit = (
            self._main_window.ui.trainingCreateDatasetLabelLineEdit
        )
        self.training_create_dataset_push_button = (
            self._main_window.ui.trainingCreateDatasetPushButton
        )
        self.training_create_dataset_push_button.setToolTip(
            "Create a dataset from selected recordings (select recordings first)"
        )
        self.training_create_dataset_push_button.clicked.connect(self._create_dataset)
        self.training_create_dataset_push_button.setEnabled(False)

        # 3. Train Model
        self.training_train_model_group_box = (
            self._main_window.ui.trainingTrainModelGroupBox
        )
        self.training_select_dataset_push_button = (
            self._main_window.ui.trainingSelectDatasetPushButton
        )
        self.training_select_dataset_push_button.setToolTip(
            "Select a previously created dataset to train a model"
        )
        self.training_select_dataset_push_button.clicked.connect(self._select_dataset)
        self.training_selected_dataset_label = (
            self._main_window.ui.trainingSelectedDatasetLabel
        )

        self.training_selected_dataset_label.setText(NO_DATASET_SELECTED_INFO)

        self.training_model_label_line_edit = (
            self._main_window.ui.trainingModelLabelLineEdit
        )

        self.train_model_push_button = self._main_window.ui.trainingTrainModelPushButton
        self.train_model_push_button.setToolTip(
            "Train a machine learning model using the selected dataset"
        )
        self.train_model_push_button.clicked.connect(self._train_model)
        self.train_model_push_button.setEnabled(False)
