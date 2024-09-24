from __future__ import annotations

import os
import pickle
import time
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFileDialog

from myogestic.gui.widgets.logger import LoggerLevel
from myogestic.models.interface import MyoGesticModelInterface

if TYPE_CHECKING:
    from myogestic.gui.myogestic import MyoGestic


class OnlineProtocol(QObject):
    def __init__(self, parent: MyoGestic | None = ...) -> None:
        """
        Class for handling the online protocol of the MyoGestic application.


        Parameters
        ----------
        parent : MyoGestic | None
            The parent object of the protocol object.

        Attributes
        ----------
        main_window : MyoGestic
            The main window of the MyoGestic application.
        emg_buffer : list[np.ndarray]
            Buffer for storing the EMG data.
        kinematics_buffer : list[(int, np.ndarray)]
            Buffer for storing the kinematics data.
        buffer_emg_recording : list[(float, np.ndarray)] | None
            Buffer for storing the EMG data during recording.
        buffer_kinematics_recording : list[(float, np.ndarray)] | None
            Buffer for storing the kinematics data during recording.
        buffer_predictions_recording : list[(float, np.ndarray)] | None
            Buffer for storing the predictions during recording.
        buffer_prediction_proba_recording : list[(float, np.ndarray)] | None
            Buffer for storing the prediction probabilities during recording.
        start_time : float | None
            Start time of the recording.
        device_information : dict[str, str] | None
            Information about the connected device.
        model_information : dict[str, str] | None
            Information about the loaded models.
        prediction_dir_path : str
            Path for storing the predictions.
        model_dir_path : str
            Path for storing the models.
        time_since_last_prediction : float
            Time since the last prediction.
        model_interface : MyoGesticModelInterface | None
            Interface for the Myogestic models.
        online_load_model_push_button : QPushButton
            Push button for loading the models.
        online_model_label : QLabel
            Label for displaying the loaded models.
        online_commands_group_box : QGroupBox
            Group box for the online commands.
        online_record_toggle_push_button : QPushButton
            Push button for toggling the recording.
        online_prediction_toggle_push_button : QPushButton
            Push button for toggling the prediction.
        conformal_prediction_set_pushbutton : QPushButton
            Push button for setting the conformal predictor.
        conformal_prediction_type_combo_box : QComboBox
            Combo box for selecting the conformal predictor type.
        conformal_prediction_solving_combo_box : QComboBox
            Combo box for selecting the conformal predictor solving method.
        conformal_prediction_alpha_spin_box : QDoubleSpinBox
            Spin box for setting the conformal predictor alpha.
        conformal_prediction_kernel_spin_box : QSpinBox
            Spin box for setting the conformal predictor kernel size.
        conformal_prediction_group_box : QGroupBox
            Group box for the conformal predictor.
        conformal_prediction_label_kernel_size : QLabel
            Label for the conformal predictor kernel size.
        conformal_prediction_label_alpha : QLabel
            Label for the conformal predictor alpha.
        conformal_prediction_label_solving_method : QLabel
            Label for the conformal predictor solving method
        """

        super().__init__(parent)

        self.main_window = parent

        # Initialize Protocol UI
        self._setup_protocol_ui()

        self.main_window.device_widget.device_changed_signal.connect(
            partial(self.online_load_model_push_button.setEnabled, False)
        )
        self.time_since_last_prediction = 0

        self.model_interface: MyoGesticModelInterface | None = None
        self.main_window.device_widget.configure_toggled.connect(
            self._update_device_configuration
        )

        # Initialize Protocol
        self.emg_buffer: list[np.ndarray] = []
        self.kinematics_buffer: list[(int, np.ndarray)] = []

        # Timings
        self.buffer_emg_recording: list[(float, np.ndarray)] = None
        self.buffer_kinematics_recording: list[(float, np.ndarray)] = None
        self.buffer_predictions_recording: list[(float, np.ndarray)] = None
        self.buffer_prediction_proba_recording: list[(float, np.ndarray)] = None
        self.start_time: float = None

        # Device
        self.device_information: dict[str, str] = None
        self.model_information: dict[str, str] = None

        # File management
        self.prediction_dir_path: str = os.path.join(
            self.main_window.base_path, "predictions"
        )
        self.model_dir_path: str = os.path.join(self.main_window.base_path, "models")

        if not os.path.exists(self.prediction_dir_path):
            os.makedirs(self.prediction_dir_path)

        if not os.path.exists(self.model_dir_path):
            os.makedirs(self.model_dir_path)

    def _update_device_configuration(self, is_configured: bool) -> None:
        if not is_configured:
            return

        self.device_information = (
            self.main_window.device_widget.get_device_information()
        )
        self.model_interface = MyoGesticModelInterface(
            device_information=self.device_information, logger=self.main_window.logger
        )
        self.online_load_model_push_button.setEnabled(True)

    def online_emg_update(self, data: np.ndarray) -> None:
        try:
            (
                vhi_prediction,
                mechatronic_prediction,
                prediction,
                prediction_proba,
            ) = self.model_interface.predict(
                data, bad_channels=self.main_window.current_bad_channels
            )
        except Exception as e:
            self.main_window.logger.print(
                f"Error in prediction: {e}", LoggerLevel.ERROR
            )
            return

        try:
            if prediction == -1:
                return
        except Exception:
            pass

        vhi_input = vhi_prediction.encode("utf-8")
        # mechatronic_input = mechatronic_prediction.encode("utf-8")
        self.main_window.virtual_hand_interface.output_message_signal.emit(vhi_input)
        # self.main_window.virtual_hand_interface.mechatronic_output_message_signal.emit(
        #     mechatronic_input
        # )

        # Save buffer
        if self.online_record_toggle_push_button.isChecked():
            self.buffer_emg_recording.append((time.time() - self.start_time, data))
            self.buffer_predictions_recording.append(
                (time.time() - self.start_time, prediction)
            )
            self.buffer_prediction_proba_recording.append(
                (time.time() - self.start_time, prediction_proba)
            )

    def online_kinematics_update(self, data: np.ndarray) -> None:
        if self.online_record_toggle_push_button.isChecked():
            self.buffer_kinematics_recording.append(
                (time.time() - self.start_time, data)
            )

    def _set_conformal_prediction(self) -> None:
        params = {
            "calibrator_type": self.conformal_prediction_type_combo_box.currentText(),
            "alpha": self.conformal_prediction_alpha_spin_box.value(),
            "kernel_size": self.conformal_prediction_kernel_spin_box.value(),
            "solver_strategy": self.conformal_prediction_solving_combo_box.currentText(),
        }
        self.model_interface.set_conformal_predictor(params)

    def _reset_conformal_predictor(self) -> None:
        self.conformal_prediction_type_combo_box.setCurrentIndex(0)

    def _toggle_prediction(self):
        # Check for connections!
        if self.online_prediction_toggle_push_button.isChecked():
            self.online_prediction_toggle_push_button.setText("Stop Prediction")
            self.online_load_model_push_button.setEnabled(False)
            self.main_window.device_widget.biosignal_data_arrived.connect(
                self.online_emg_update
            )
            self.online_record_toggle_push_button.setEnabled(True)
            self.conformal_prediction_group_box.setEnabled(False)
        else:
            self.online_prediction_toggle_push_button.setText("Start Prediction")
            self.online_load_model_push_button.setEnabled(True)
            self.main_window.device_widget.biosignal_data_arrived.disconnect(
                self.online_emg_update
            )
            self.online_record_toggle_push_button.setEnabled(False)
            # self.conformal_prediction_group_box.setEnabled(True)

    def _toggle_recording(self):
        if self.online_record_toggle_push_button.isChecked():
            self.online_prediction_toggle_push_button.setEnabled(False)
            self.main_window.virtual_hand_interface.input_message_signal.connect(
                self.online_kinematics_update
            )
            self.buffer_emg_recording = []
            self.buffer_kinematics_recording = []
            self.buffer_predictions_recording = []
            self.buffer_prediction_proba_recording = []
            self.start_time = time.time()
            self.online_record_toggle_push_button.setText("Stop Recording")
        else:
            self.online_prediction_toggle_push_button.setEnabled(True)
            self.main_window.virtual_hand_interface.input_message_signal.disconnect(
                self.online_kinematics_update
            )
            self.online_record_toggle_push_button.setText("Start Recording")

            self._save_data()

    def _save_data(self) -> None:
        save_pickle_dict = {
            "emg": np.hstack([data for _, data in self.buffer_emg_recording]),
            "emg_timings": np.array([time for time, _ in self.buffer_emg_recording]),
            "kinematics": np.vstack(
                [data for _, data in self.buffer_kinematics_recording]
            ).T,
            "kinematics_timings": np.array(
                [time for time, _ in self.buffer_kinematics_recording]
            ),
            "predictions": np.hstack(
                [data for _, data in self.buffer_predictions_recording]
            ),
            "predictions_timings": np.array(
                [time for time, _ in self.buffer_predictions_recording]
            ),
            "prediction_proba": np.hstack(
                [data for _, data in self.buffer_prediction_proba_recording]
            ),
            "prediction_proba_timings": np.array(
                [time for time, _ in self.buffer_prediction_proba_recording]
            ),
            "label": self.online_model_label.text().split(" ")[0],
            "model_information": self.model_information,
            "sampling_frequency": self.device_information["sampling_frequency"],
            "bad_channels": set(
                self.main_window.current_bad_channels
                + self.model_information["bad_channels"]
            ),
        }
        now = datetime.now()
        formatted_now = now.strftime("%Y%m%d_%H%M%S%f")
        file_name = f"MyoGestic_Prediction_{formatted_now}_{self.online_model_label.text().lower().split(' ')[0]}.pkl"

        with open(os.path.join(self.prediction_dir_path, file_name), "wb") as f:
            pickle.dump(save_pickle_dict, f)

        # Reset buffers
        self.emg_buffer = []
        self.kinematics_buffer = []

    def _load_model(self) -> None:
        dialog = QFileDialog(self.main_window)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Checkpoint files (*.pkl)")

        file_name = dialog.getOpenFileName(
            self.main_window,
            "Open Model",
            self.model_dir_path,
            "Checkpoint files (*.pkl)",
        )[0]

        if not file_name:
            print("Error in file selection!")
            return

        try:
            self.model_information = self.model_interface.load_model(file_name)
        except Exception as e:
            self.main_window.logger.print(
                f"Error in loading models: {e}", LoggerLevel.ERROR
            )
            return

        label = file_name.split("/")[-1].split("_")[-1].split(".")[0]

        self.online_model_label.setText(f"{label} loaded!")

        # self.conformal_prediction_group_box.setEnabled(True)
        self.online_commands_group_box.setEnabled(True)
        self.online_record_toggle_push_button.setEnabled(False)

        self.main_window.logger.print(
            f"Model loaded. Label: {label}",
            LoggerLevel.INFO,
        )

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

    def _setup_protocol_ui(self) -> None:
        self.online_load_model_group_box = self.main_window.ui.onlineLoadModelGroupBox

        self.online_load_model_push_button = (
            self.main_window.ui.onlineLoadModelPushButton
        )
        self.online_load_model_push_button.setEnabled(False)
        self.online_load_model_push_button.clicked.connect(self._load_model)
        self.online_model_label = self.main_window.ui.onlineModelLabel
        self.online_model_label.setText("No models loaded!")

        self.online_commands_group_box = self.main_window.ui.onlineCommandsGroupBox
        self.online_commands_group_box.setEnabled(False)
        self.online_record_toggle_push_button = (
            self.main_window.ui.onlineRecordTogglePushButton
        )
        self.online_record_toggle_push_button.clicked.connect(self._toggle_recording)

        self.online_prediction_toggle_push_button = (
            self.main_window.ui.onlinePredictionTogglePushButton
        )
        self.online_prediction_toggle_push_button.clicked.connect(
            self._toggle_prediction
        )

        # Conformal Prediction
        self.conformal_prediction_set_pushbutton = (
            self.main_window.ui.conformalPredictionSetPushButton
        )
        self.conformal_prediction_set_pushbutton.clicked.connect(
            self._set_conformal_prediction
        )
        self.conformal_prediction_set_pushbutton.setEnabled(False)

        self.conformal_prediction_type_combo_box = (
            self.main_window.ui.conformalPredictionTypeComboBox
        )
        self.conformal_prediction_solving_combo_box = (
            self.main_window.ui.conformalPredictionSolvingComboBox
        )
        self.conformal_prediction_alpha_spin_box = (
            self.main_window.ui.conformalPredictionAlphaDoubleSpinBox
        )
        self.conformal_prediction_kernel_spin_box = (
            self.main_window.ui.conformalPredictionSolvingKernel
        )
        self.conformal_prediction_type_combo_box.currentIndexChanged.connect(
            self._toggle_conformal_prediction_widget
        )

        self.conformal_prediction_group_box = (
            self.main_window.ui.conformalPredictionGroupBox
        )
        self.conformal_prediction_group_box.setEnabled(False)

        self.conformal_prediction_label_kernel_size = (
            self.main_window.ui.labelCpKernelSize
        )
        self.conformal_prediction_label_alpha = self.main_window.ui.labelCpAlpha
        self.conformal_prediction_label_solving_method = (
            self.main_window.ui.labelCpSolvingMethod
        )

        self._toggle_conformal_prediction_widget()
