from __future__ import annotations

import pickle
import time
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.gui.widgets.templates.output_system import OutputSystemTemplate
from myogestic.gui.widgets.templates.visual_interface import VisualInterface
from myogestic.models.interface import MyoGesticModelInterface
from myogestic.user_config import CHANNELS
from myogestic.utils.config import CONFIG_REGISTRY
from myogestic.utils.constants import PREDICTIONS_DIR_PATH, MODELS_DIR_PATH


if TYPE_CHECKING:
    from myogestic.gui.myogestic import MyoGestic


class OnlineProtocol(QObject):
    """
    Class for handling the online protocol of the MyoGestic application.


    Parameters
    ----------
    main_window : MyoGestic
        The main window of the application.

    Attributes
    ----------
    _main_window : MyoGestic
        The main window of the application.
    _selected_visual_interface : VisualInterface | None
        The selected visual interface for the online protocol.
    _time_since_last_prediction : float
        Time since the last prediction.
    _model_interface : MyoGesticModelInterface | None
        The model interface for the online protocol.
    _biosignal_recording__buffer : list[(float, np.ndarray)]
        Buffer for storing the biosignal data.
    _ground_truth_recording__buffer : list[(float, np.ndarray)]
        Buffer for storing the ground truth data.
    _prediction_before_filter_recording__buffer : list[(float, np.ndarray)]
        Buffer for storing the predictions before filtering.
    _predictions_after_filter_recording__buffer : list[(float, np.ndarray)]
        Buffer for storing the predictions after filtering.
    _selected_real_time_filter_recording__buffer : list[(float, str)]
        Buffer for storing the selected real-time filter.
    recording_start_time : float
        Start time of the recording.
    _device_information__dict : dict[str, Any] | None
        Information about the device.
    _model_information__dict : dict[str, Any] | None
        Information about the model.
    active_monitoring_widgets : dict[str, _MonitoringWidgetBaseClass]
        Active monitoring widgets.
    _output_systems__dict : dict[str, OutputSystemTemplate]
        Output systems for the online
    """

    model_information_signal = Signal(dict)

    def __init__(self, main_window: MyoGestic) -> None:
        super().__init__(main_window)

        self._main_window = main_window

        self._selected_visual_interface: VisualInterface | None = None

        # Initialize Protocol UI
        self._setup_protocol_ui()

        self._main_window.device__widget.device_changed_signal.connect(
            partial(self.online_load_model_push_button.setEnabled, False)
        )
        self._time_since_last_prediction: float = 0

        self._model_interface: MyoGesticModelInterface | None = None
        self._main_window.device__widget.configure_toggled.connect(
            self._update_device_configuration
        )

        # Initialize Buffers
        self._biosignal_recording__buffer: list[(float, np.ndarray)] = []
        self._ground_truth_recording__buffer: list[(float, np.ndarray)] = []

        self._prediction_before_filter_recording__buffer: list[(float, np.ndarray)] = []
        self._predictions_after_filter_recording__buffer: list[(float, np.ndarray)] = []

        self._selected_real_time_filter_recording__buffer: list[(float, str)] = []

        self.recording_start_time: float = 0

        # Device
        self._device_information__dict: dict[str, Any] | None = None
        self._model_information__dict: dict[str, Any] | None = None

        # File management
        PREDICTIONS_DIR_PATH.mkdir(exist_ok=True, parents=True)
        MODELS_DIR_PATH.mkdir(exist_ok=True, parents=True)

        self.real_time_filter_combo_box.addItems(
            CONFIG_REGISTRY.real_time_filters_map.keys()
        )

        self.active_monitoring_widgets = {}

        self._output_systems__dict: dict[str, OutputSystemTemplate] = {}

    def _update_real_time_filter(self) -> None:
        self._model_interface.set_real_time_filter(
            self.real_time_filter_combo_box.currentText()
        )

    def _update_device_configuration(self, is_configured: bool) -> None:
        if not is_configured:
            self._main_window.logger.print(
                "Device not configured! Please configure the device!",
                LoggerLevel.ERROR,
            )
            return

        self._device_information__dict = (
            self._main_window.device__widget.get_device_information()
        )

        self._model_interface = MyoGesticModelInterface(
            device_information=self._device_information__dict,
            logger=self._main_window.logger,
            parent=self._main_window,
        )

        self.online_load_model_push_button.setEnabled(True)

    def online_emg_update(self, data: np.ndarray) -> None:
        try:
            (
                prediction_before_filter,
                prediction_after_filter,
                selected_real_time_filter,
            ) = self._model_interface.predict(
                data,
                bad_channels=self._main_window.current_bad_channels__list,
                selected_real_time_filter=self.real_time_filter_combo_box.currentText(),
            )
        except Exception as e:
            self._main_window.logger.print(
                f"Error in prediction: {e}", LoggerLevel.ERROR
            )
            return

        try:
            if prediction_before_filter == -1:
                return
        except Exception:
            pass

        if len(self._output_systems__dict) == 0:
            self._main_window.logger.print(
                "No output systems available!", LoggerLevel.ERROR
            )
            raise ValueError("No output systems available!")

        prediction = (
            prediction_before_filter
            if (
                prediction_after_filter is None
                or np.isnan(prediction_after_filter).any()
            )
            else prediction_after_filter
        )

        for output_system in self._output_systems__dict.values():
            output_system.send_prediction(prediction)

        # Save buffer
        if self.online_record_toggle_push_button.isChecked():
            current_time = time.time()

            self._biosignal_recording__buffer.append(
                (current_time - self.recording_start_time, data)
            )

            self._prediction_before_filter_recording__buffer.append(
                (current_time - self.recording_start_time, prediction_before_filter)
            )
            self._predictions_after_filter_recording__buffer.append(
                (current_time - self.recording_start_time, prediction_after_filter)
            )
            self._selected_real_time_filter_recording__buffer.append(
                (current_time - self.recording_start_time, selected_real_time_filter)
            )

    def online_ground_truth_update(self, data: np.ndarray) -> None:
        if self.online_record_toggle_push_button.isChecked():
            self._ground_truth_recording__buffer.append(
                (time.time() - self.recording_start_time, data)
            )

    def _set_conformal_prediction(self) -> None:
        params = {
            "calibrator_type": self.conformal_prediction_type_combo_box.currentText(),
            "alpha": self.conformal_prediction_alpha_spin_box.value(),
            "kernel_size": self.conformal_prediction_kernel_spin_box.value(),
            "solver_strategy": self.conformal_prediction_solving_combo_box.currentText(),
        }
        self._model_interface.set_conformal_predictor(params)

    def _reset_conformal_predictor(self) -> None:
        self.conformal_prediction_type_combo_box.setCurrentIndex(0)

    def _toggle_prediction(self):
        # Check for connections!
        if self.online_prediction_toggle_push_button.isChecked():
            self.online_prediction_toggle_push_button.setText("Stop Prediction")
            self.online_load_model_push_button.setEnabled(False)
            self._main_window.device__widget.biosignal_data_arrived.connect(
                self.online_emg_update
            )
            self.online_record_toggle_push_button.setEnabled(True)
            self.conformal_prediction_group_box.setEnabled(False)
        else:
            self.online_prediction_toggle_push_button.setText("Start Prediction")
            self.online_load_model_push_button.setEnabled(True)
            self._main_window.device__widget.biosignal_data_arrived.disconnect(
                self.online_emg_update
            )
            self.online_record_toggle_push_button.setEnabled(False)
            # self.conformal_prediction_group_box.setEnabled(True)

    def _toggle_recording(self):
        if self.online_record_toggle_push_button.isChecked():
            self.online_prediction_toggle_push_button.setEnabled(False)

            self._main_window.selected_visual_interface.incoming_message_signal.connect(
                self.online_ground_truth_update
            )

            self._selected_visual_interface.setup_interface_ui.connect_custom_signals()

            self._biosignal_recording__buffer = []
            self._ground_truth_recording__buffer = []

            self._selected_visual_interface.setup_interface_ui.clear_custom_signal_buffers()

            self._prediction_before_filter_recording__buffer = []
            self._predictions_after_filter_recording__buffer = []
            self._selected_real_time_filter_recording__buffer = []

            self.recording_start_time = time.time()
            self.online_record_toggle_push_button.setText("Stop Recording")
        else:
            self.online_prediction_toggle_push_button.setEnabled(True)
            self._main_window.selected_visual_interface.incoming_message_signal.disconnect(
                self.online_ground_truth_update
            )

            self._selected_visual_interface.setup_interface_ui.disconnect_custom_signals()

            self.online_record_toggle_push_button.setText("Start Recording")

            self._save_data()

    def _save_data(self) -> None:
        save_pickle_dict = {
            "biosignal": np.stack(
                [data for _, data in self._biosignal_recording__buffer], axis=-1
            ),
            "biosignal_timings": np.array(
                [time for time, _ in self._biosignal_recording__buffer]
            ),
            "ground_truth": np.vstack(
                [data for _, data in self._ground_truth_recording__buffer]
            ).T,
            "ground_truth_timings": np.array(
                [time for time, _ in self._ground_truth_recording__buffer]
            ),
            "predictions_before_filters": np.stack(
                [data for _, data in self._prediction_before_filter_recording__buffer],
                axis=-1,
            ),
            "predictions_before_filters_timings": np.array(
                [time for time, _ in self._prediction_before_filter_recording__buffer]
            ),
            "predictions_after_filters": np.stack(
                [data for _, data in self._predictions_after_filter_recording__buffer],
                axis=-1,
            ),
            "predictions_after_filters_timings": np.array(
                [time for time, _ in self._predictions_after_filter_recording__buffer]
            ),
            "selected_real_time_filters": np.array(
                [data for _, data in self._selected_real_time_filter_recording__buffer]
            ),
            "label": self.online_model_label.text().split(" ")[0],
            "model_information": self._model_information__dict,
            "device_information": self._device_information__dict,
            "bad_channels": set(
                self._main_window.current_bad_channels__list
                + self._model_information__dict["bad_channels"]
            ),
            "channels": CHANNELS,
        }

        save_pickle_dict.update(
            self._selected_visual_interface.setup_interface_ui.get_custom_save_data()
        )

        file_name = f"{self._selected_visual_interface.name}_Prediction_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{self.online_model_label.text().lower().split(' ')[0]}.pkl"

        with (PREDICTIONS_DIR_PATH / file_name).open("wb") as f:
            pickle.dump(save_pickle_dict, f)

    def _load_model(self) -> None:
        dialog = QFileDialog(self._main_window)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Checkpoint files (*.pkl)")

        file_name = dialog.getOpenFileName(
            self._main_window,
            "Open Model",
            str(MODELS_DIR_PATH),
            "Checkpoint files (*.pkl)",
        )[0]

        if not file_name:
            print("Error in file selection!")
            return

        try:
            self._model_information__dict = self._model_interface.load_model(file_name)
        except Exception as e:
            self._main_window.logger.print(
                f"Error in loading models: {e}", LoggerLevel.ERROR
            )
            return

        label = file_name.split("/")[-1].split("_")[-1].split(".")[0]

        self.online_model_label.setText(f"{label} loaded!")

        # self.conformal_prediction_group_box.setEnabled(True)
        self.online_commands_group_box.setEnabled(True)
        self.online_record_toggle_push_button.setEnabled(False)

        self._main_window.logger.print(
            f"Model loaded. Label: {label}",
            LoggerLevel.INFO,
        )

        if len(self.active_monitoring_widgets) != 0:
            self._send_model_information()

        self._output_systems__dict = {
            k: v(self._main_window, self._model_interface.model.is_classifier)
            for k, v in CONFIG_REGISTRY.output_systems_map.items()
        }

    def close_event(self, event) -> None:
        for output_system in self._output_systems__dict.values():
            output_system.close_event(event)

    def _toggle_conformal_prediction_widget(self) -> None:
        if self.conformal_prediction_type_combo_box.currentText() == "None":
            self.conformal_prediction_solving_combo_box.setEnabled(False)
            self.conformal_prediction_alpha_spin_box.setEnabled(False)
            self.conformal_prediction_kernel_spin_box.setEnabled(False)
            self.conformal_prediction_label_kernel_size.setEnabled(False)
            self.conformal_prediction_label_alpha.setEnabled(False)
            self.conformal_prediction_label_solving_method.setEnabled(False)
            self.conformal_prediction_set_pushbutton.setEnabled(False)
        else:
            self.conformal_prediction_solving_combo_box.setEnabled(True)
            self.conformal_prediction_alpha_spin_box.setEnabled(True)
            self.conformal_prediction_kernel_spin_box.setEnabled(True)
            self.conformal_prediction_label_kernel_size.setEnabled(True)
            self.conformal_prediction_label_alpha.setEnabled(True)
            self.conformal_prediction_label_solving_method.setEnabled(True)
            self.conformal_prediction_set_pushbutton.setEnabled(True)

    def _send_model_information(self) -> None:
        self.model_information_signal.emit(
            {
                "models_map": CONFIG_REGISTRY.models_map[
                    self._model_information__dict["model_name"]
                ],
                "functions_map": CONFIG_REGISTRY.models_functions_map[
                    self._model_information__dict["model_name"]
                ],
                "model_path": self._model_information__dict["model_path"],
                "model_params": self._model_information__dict["model_params"],
            }
        )

    # def _setup_monitoring_widget(
    #     self,
    #     name_of_monitoring_widget: str,
    #     monitoring_widget: Type[_MonitoringWidgetBaseClass],
    #     state: int,
    # ) -> None:
    #     if state.value == 2:
    #         self.active_monitoring_widgets[name_of_monitoring_widget] = (
    #             monitoring_widget(None, self.model_interface.model.predicted_emg_signal)
    #         )
    #         self.active_monitoring_widgets[name_of_monitoring_widget].show()
    #
    #         self.model_information_signal.connect(
    #             self.active_monitoring_widgets[
    #                 name_of_monitoring_widget
    #             ].update_model_information
    #         )
    #
    #         self._send_model_information()
    #
    #     else:
    #         self.active_monitoring_widgets[name_of_monitoring_widget].close()
    #         del self.active_monitoring_widgets[name_of_monitoring_widget]

    # def _setup_monitoring_widgets_ui(self) -> None:
    #     container_widget = QWidget()
    #
    #     layout = QVBoxLayout(container_widget)
    #     # For each monitoring widget in CONFIG_REGISTRY.monitoring_widgets add a push button to the monitoring list
    #     for k, v in CONFIG_REGISTRY.monitoring_widgets_map.items():
    #         monitoring_push_button = QCheckBox(k)
    #         monitoring_push_button.checkStateChanged.connect(
    #             partial(
    #                 self._setup_monitoring_widget,
    #                 k,
    #                 v,
    #             )
    #         )
    #
    #         layout.addWidget(monitoring_push_button)
    #
    #     self.monitoring_widgets_scroll_area.setWidget(container_widget)

    def _setup_protocol_ui(self) -> None:
        self.online_load_model_group_box = self._main_window.ui.onlineLoadModelGroupBox

        self.online_load_model_push_button = (
            self._main_window.ui.onlineLoadModelPushButton
        )
        self.online_load_model_push_button.setEnabled(False)
        self.online_load_model_push_button.clicked.connect(self._load_model)
        self.online_model_label = self._main_window.ui.onlineModelLabel
        self.online_model_label.setText("No models loaded!")

        self.online_commands_group_box = self._main_window.ui.onlineCommandsGroupBox
        self.online_commands_group_box.setEnabled(False)
        self.online_record_toggle_push_button = (
            self._main_window.ui.onlineRecordTogglePushButton
        )
        self.online_record_toggle_push_button.clicked.connect(self._toggle_recording)

        self.online_prediction_toggle_push_button = (
            self._main_window.ui.onlinePredictionTogglePushButton
        )
        self.online_prediction_toggle_push_button.clicked.connect(
            self._toggle_prediction
        )

        # Conformal Prediction
        self.conformal_prediction_set_pushbutton = (
            self._main_window.ui.conformalPredictionSetPushButton
        )
        self.conformal_prediction_set_pushbutton.clicked.connect(
            self._set_conformal_prediction
        )
        self.conformal_prediction_set_pushbutton.setEnabled(False)

        self.conformal_prediction_type_combo_box = (
            self._main_window.ui.conformalPredictionTypeComboBox
        )
        self.conformal_prediction_solving_combo_box = (
            self._main_window.ui.conformalPredictionSolvingComboBox
        )
        self.conformal_prediction_alpha_spin_box = (
            self._main_window.ui.conformalPredictionAlphaDoubleSpinBox
        )
        self.conformal_prediction_kernel_spin_box = (
            self._main_window.ui.conformalPredictionSolvingKernel
        )
        self.conformal_prediction_type_combo_box.currentIndexChanged.connect(
            self._toggle_conformal_prediction_widget
        )

        self.conformal_prediction_group_box = (
            self._main_window.ui.conformalPredictionGroupBox
        )
        self.conformal_prediction_group_box.setEnabled(False)

        self.conformal_prediction_label_kernel_size = (
            self._main_window.ui.labelCpKernelSize
        )
        self.conformal_prediction_label_alpha = self._main_window.ui.labelCpAlpha
        self.conformal_prediction_label_solving_method = (
            self._main_window.ui.labelCpSolvingMethod
        )

        self.real_time_filter_combo_box = self._main_window.ui.onlineFiltersComboBox

        self._toggle_conformal_prediction_widget()
