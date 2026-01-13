from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np
from scipy.signal import butter, lfilter, lfilter_zi
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QMainWindow,
    QGroupBox,
    QVBoxLayout,
)
from biosignal_device_interface.constants.devices.core.base_device_constants import (
    DeviceType,
)

from myogestic.gui.biosignal import Ui_BioSignalInterface
from myogestic.gui.main_window import Ui_MyoGestic
from myogestic.gui.protocols.protocol import Protocol
from myogestic.gui.widgets.logger import CustomLogger
from myogestic.gui.widgets.templates.visual_interface import VisualInterface
from myogestic.user_config import DEFAULT_DEVICE_TO_USE, CHANNELS
from myogestic.utils.config import _custom_message_handler, CONFIG_REGISTRY  # noqa
from myogestic.utils.constants import BASE_PATH

if TYPE_CHECKING:
    from biosignal_device_interface.gui.device_template_widgets.otb.otb_devices_widget import (
        OTBDevicesWidget,
    )
    from biosignal_device_interface.gui.plot_widgets.biosignal_plot_widget import (
        BiosignalPlotWidget,
    )

from PySide6.QtCore import qInstallMessageHandler


class EMGfilters:
    """Real-time EMG filtering class for multi-channel biosignal data."""

    def __init__(self, hp_cutOff, lp_cutOff, env_cutOff, fs, order=5, ch_numb=64):
        """Initialize EMG filters with state preservation for real-time processing.

        Args:
            hp_cutOff: Highpass filter cutoff frequency (Hz)
            lp_cutOff: Lowpass filter cutoff frequency (Hz)
            env_cutOff: Envelope lowpass filter cutoff frequency (Hz)
            fs: Sampling frequency (Hz)
            order: Filter order (default 5)
            ch_numb: Number of channels (default 64)
        """
        self.ch_numb = ch_numb
        self.order = order
        self.initialized = False  # Track if states have been initialized with signal

        # Normalize cutoff frequencies
        Wn_hp = hp_cutOff * 2 / fs
        Wn_lp = lp_cutOff * 2 / fs
        Wn_env = env_cutOff * 2 / fs
        Wn_bsl = 45 * 2 / fs
        Wn_bsh = 55 * 2 / fs

        # Design Butterworth filters and get initial state vectors
        self.b_hp, self.a_hp = butter(order, Wn_hp, btype='high', analog=False)
        self.b_lp, self.a_lp = butter(order, Wn_lp, btype='low', analog=False)
        self.b_env, self.a_env = butter(2, Wn_env, btype='low', analog=False)
        self.b_bs, self.a_bs = butter(2, [Wn_bsl, Wn_bsh], btype='bandstop', analog=False)

        # Get steady-state initial conditions for each filter
        self.zi_hp_template = lfilter_zi(self.b_hp, self.a_hp)
        self.zi_lp_template = lfilter_zi(self.b_lp, self.a_lp)
        self.zi_env_template = lfilter_zi(self.b_env, self.a_env)
        self.zi_bs_template = lfilter_zi(self.b_bs, self.a_bs)

        # Initialize filter states (will be set properly on first data)
        self.zil = None
        self.zie = None
        self.zih = None
        self.zibs = None

    def initialize_states(self, first_sample):
        """Initialize filter states based on the first data sample.

        Args:
            first_sample: First data sample (samples, channels) to initialize states
        """
        # Scale initial conditions by first sample for each channel
        self.zih = self.zi_hp_template[:, np.newaxis] * first_sample[0, :]
        self.zibs = self.zi_bs_template[:, np.newaxis] * first_sample[0, :]
        self.zil = self.zi_lp_template[:, np.newaxis] * first_sample[0, :]
        self.zie = self.zi_env_template[:, np.newaxis] * first_sample[0, :]
        self.initialized = True

    def butter_bandstop_filter(self, data):
        """Apply 50Hz notch filter (bandstop 45-55Hz)."""
        y, self.zibs = lfilter(self.b_bs, self.a_bs, data, axis=0, zi=self.zibs)
        return y

    def butter_lowpass_filter(self, data):
        """Apply lowpass filter."""
        y, self.zil = lfilter(self.b_lp, self.a_lp, data, axis=0, zi=self.zil)
        return y

    def butter_lowpassEnv_filter(self, data):
        """Apply envelope extraction lowpass filter."""
        y, self.zie = lfilter(self.b_env, self.a_env, data, axis=0, zi=self.zie)
        return y

    def butter_highpass_filter(self, data):
        """Apply highpass filter."""
        y, self.zih = lfilter(self.b_hp, self.a_hp, data, axis=0, zi=self.zih)
        return y


class MyoGestic(QMainWindow):
    """
    Main window of the MyoGestic application.

    This class is the main window of the MyoGestic application. It contains the
    main user interface and connects the different parts of the application.

    Attributes
    ----------
    ui : Ui_MyoGestic
        The backbone UI of MyoGestic. This is the compiled PySide6 code from the _main_window.ui file.
    logger : CustomLogger
        The ui logger of MyoGestic. This is a custom logger that logs messages to the main window.
    protocols : list[Protocol]
        List of protocols (recording, training, and online) available in MyoGestic.
    selected_visual_interface : Optional[VisualInterface]
        The selected visual interface in MyoGestic. This is distributed to the protocols.
    """

    def __init__(self):
        super().__init__()

        self.ui = Ui_MyoGestic()
        self.ui.setupUi(self)

        # Install the custom message handler
        qInstallMessageHandler(_custom_message_handler)

        # Logging
        self._fps_display__label: QLabel = self.ui.appUpdateFPSLabel
        self._fps_display__label.setText("")
        self._fps__buffer: list[float, float] = []
        self._start_fps_counting__time: float = time.time()

        self.logger: CustomLogger = CustomLogger(self.ui.loggingTextEdit)
        self.logger.print("MyoGestic started!")

        # Tab Widget
        self._tab__widget = self.ui.mindMoveTabWidget
        self._tab__widget.setCurrentIndex(0)

        # Plot Setup
        self._plot__widget: BiosignalPlotWidget = self.ui.vispyPlotWidget
        self.current_bad_channels__list: list = []
        self._plot__widget.bad_channels_updated.connect(self._update_bad_channels)
        self._biosignal_plot_display_time_range__value = (
            self.ui.timeShownDoubleSpinBox.value()
        )

        # Device Setup
        self._biosignal_interface__widget = Ui_BioSignalInterface()
        self._biosignal_interface__widget.setupUi(self)
        self.device__widget: OTBDevicesWidget = (
            self._biosignal_interface__widget.devicesWidget
        )

        self.ui.setupVerticalLayout.addWidget(
            self._biosignal_interface__widget.groupBox
        )

        self.device__widget.biosignal_data_arrived.connect(self.update)
        self.device__widget.configure_toggled.connect(self._prepare_plot)

        self.ui.timeShownDoubleSpinBox.valueChanged.connect(self._reconfigure_plot)

        # Device parameters
        self._device_name: DeviceType | None = None
        self._sampling_frequency = None
        self._samples_per_frame = None
        self._number_of_channels = None

        # EMG Filters for real-time processing (sessantaquattro)
        self._emg_filters: EMGfilters | None = None

        BASE_PATH.mkdir(exist_ok=True, parents=True)
        self.ui.statusbar.showMessage(f"Data path: {Path.cwd() / BASE_PATH}")

        # Protocol Setup
        self._protocol__helper_class = Protocol(self)
        self.protocols = self._protocol__helper_class.available_protocols

        # Visual Interface(s) Setup
        self.ui.visualInterfacesGroupBox = QGroupBox("Visual Interfaces")
        self.ui.visualInterfacesGroupBox.setObjectName("visualInterfacesGroupBox")
        self.ui.visualInterfacesVerticalLayout = QVBoxLayout()
        self.ui.setupVerticalLayout.addWidget(self.ui.visualInterfacesGroupBox)
        self.ui.visualInterfacesGroupBox.setLayout(
            self.ui.visualInterfacesVerticalLayout
        )
        self.ui.visualInterfacesVerticalLayout.setContentsMargins(*([15] * 4))

        self.selected_visual_interface: Optional[VisualInterface] = None
        self._visual_interfaces__dict: dict[str, VisualInterface] = {
            name: VisualInterface(
                self,
                name=name,
                setup_interface_ui=setup_ui,
                recording_interface_ui=interface_ui,
            )
            for name, (
                setup_ui,
                interface_ui,
            ) in CONFIG_REGISTRY.visual_interfaces_map.items()
        }

        # Preferences
        self._toggle_vispy_plot__check_box: QCheckBox = self.ui.toggleVispyPlotCheckBox

        self.device__widget.device_selection_combo_box.setCurrentIndex(
            DEFAULT_DEVICE_TO_USE
        )

        # Add shortcuts
        # Toggle plotting shortcut
        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_T), self).activated.connect(
            self._toggle_vispy_plot__check_box.toggle
        )

        # Set the title of the main window
        self.setWindowTitle("MyoGestic")

    def toggle_selected_visual_interface(self, name: str) -> None:
        """
        Toggles the selected visual interface.

        This methods sets all other visual interfaces to disabled and enables the selected visual interface.

        Parameters
        ----------
        name : str
            Name of the visual interface to toggle.

        Returns
        -------
        None
        """
        if self.selected_visual_interface:
            for visual_interface in self._visual_interfaces__dict.values():
                visual_interface.enable_ui()
            self.selected_visual_interface = None
        else:
            for visual_interface in self._visual_interfaces__dict.values():
                if visual_interface.name != name:
                    visual_interface.disable_ui()
            self.selected_visual_interface = self._visual_interfaces__dict[name]

        self._protocol__helper_class._pass_on_selected_visual_interface()

    def _update_bad_channels(self, bad_channels: np.ndarray) -> None:
        """
        Update the bad channels.

        Parameters
        ----------
        bad_channels : np.ndarray
            Array of bad channels.

        Returns
        -------
        None
        """
        self.current_bad_channels__list = np.nonzero(bad_channels == 0)[0].tolist()

    def update(self, data: np.ndarray) -> None:  # noqa
        """
        Update the application.

        This method updates the application with new data.

        Parameters
        ----------
        data : np.ndarray
            Data to update the application with.

        Returns
        -------
        None
        """
        current_time = time.time()

        self._fps__buffer.append(
            max(current_time - self._start_fps_counting__time, 1e-10)
        )
        last_time = self._fps__buffer[-1]

        self._fps__buffer = list(
            filter(
                lambda x: last_time - 1 < x <= last_time,
                self._fps__buffer,
            )
        )

        self._fps_display__label.setText(f"{len(self._fps__buffer)}")

        # EMG Data
        if self._toggle_vispy_plot__check_box.isChecked():
            # Apply real-time EMG filters for sessantaquattro
            if self._device_name == "Sessantaquattro" and self._emg_filters is not None:
                # Reshape data for filtering: (samples, channels)
                filtered_data = data[: self._number_of_channels].T

                # Initialize filter states on first data chunk
                if not self._emg_filters.initialized:
                    self._emg_filters.initialize_states(filtered_data)

                # Apply filter chain:
                # 1. Highpass filter (remove DC offset and low-freq drift)
                filtered_data = self._emg_filters.butter_highpass_filter(filtered_data)

                # 2. Bandstop filter (remove 50Hz powerline noise)
                filtered_data = self._emg_filters.butter_bandstop_filter(filtered_data)

                # 3. Lowpass filter (anti-aliasing and noise reduction)
                filtered_data = self._emg_filters.butter_lowpass_filter(filtered_data)

                # Reshape back to (channels, samples)
                filtered_data = filtered_data.T
                scale_factor = 0.5  # Use higher scale for filtered data

            elif self._device_name == "NSwitch":
                filtered_data = data[: self._number_of_channels]
                scale_factor = 1000  # Default scale
            else:
                # Default processing for other devices
                filtered_data = data[: self._number_of_channels]
                scale_factor = 5  # Default scale

            self._plot__widget.update_plot(filtered_data * scale_factor)

    def _prepare_plot(self, is_configured: bool) -> None:
        """
        Prepare the plot widget.

        This method prepares the plot widget for displaying biosignal data.

        Returns
        -------
        None
        """
        if not is_configured:
            self.logger.print("Device not configured!")
            return

        device_information = self.device__widget.get_device_information()
        self._device_name = device_information["name"]
        self._sampling_frequency = device_information["sampling_frequency"]
        self._samples_per_frame = device_information["samples_per_frame"]
        self._number_of_channels = device_information["number_of_biosignal_channels"]

        # Initialize EMG filters for sessantaquattro
        if self._device_name == "Sessantaquattro":
            self.logger.print("Initializing EMG filters for Sessantaquattro...")
            self._emg_filters = EMGfilters(
                hp_cutOff=20,      # 20 Hz highpass (remove DC and low-freq drift)
                lp_cutOff=450,     # 450 Hz lowpass (anti-aliasing)
                env_cutOff=10,     # 10 Hz envelope extraction
                fs=self._sampling_frequency,
                order=5,
                ch_numb=self._number_of_channels
            )
            self.logger.print(f"EMG filters initialized: HP=20Hz, LP=450Hz, Notch=50Hz, Env=10Hz, FS={self._sampling_frequency}Hz")
        else:
            self._emg_filters = None

        self._reconfigure_plot(self._biosignal_plot_display_time_range__value)

        # initialize the fps buffer with zeros for one second to avoid a spike in the first few frames
        self._start_fps_counting__time = time.time()
        self._fps__buffer = [time.time() - self._start_fps_counting__time]

    def _reconfigure_plot(self, value) -> None:
        """
        Reconfigure the plot widget.

        This method reconfigures the plot widget for displaying biosignal data based on the given value in seconds.

        Returns
        -------
        None
        """
        if self._sampling_frequency is None or self._number_of_channels is None:
            self.logger.print("Device not configured!")
            return

        self._plot__widget.configure(
            display_time=value,
            sampling_frequency=self._sampling_frequency,
            lines=self._number_of_channels,
        )
        self._plot__widget.resize(0, 0)

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Close the event.

        Parameters
        ----------
        event : QCloseEvent
            The event to close.

        Returns
        -------
        Notes
        """
        self.device__widget.closeEvent(event)

        for vi in self._visual_interfaces__dict.values():
            vi.close_event(event)

        for p in self.protocols:
            p.close_event(event)

        super().closeEvent(event)
