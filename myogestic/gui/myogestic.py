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
    QGroupBox,
    QVBoxLayout,
)
from biosignal_device_interface.constants.devices.core.base_device_constants import (
    DeviceType,
)

from myogestic.gui.biosignal import Ui_BioSignalInterface
from myogestic.gui.main_window import Ui_MyoGestic
from myogestic.gui.protocols.protocol import Protocol
from myogestic.gui.scalable_window import ScalableMainWindow
from myogestic.gui.widgets.default_recording import DefaultRecordingInterface
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


class ExponentialMovingAverage:
    """Real-time exponential moving average filter for multi-channel data.

    Uses RC filter formulas:
        RC = 1 / (2π * fc)
        Low-pass:  α = 1 / (1 + fs * RC)
        High-pass: α = RC / (RC + 1/fs)
    """

    def __init__(self, fc: float, fs: float, filter_type: str = "lowpass", ch_numb: int = 64):
        """Initialize EMA filter with cutoff frequency.

        Args:
            fc: Cutoff frequency (Hz)
            fs: Sampling frequency (Hz)
            filter_type: "lowpass" or "highpass"
            ch_numb: Number of channels.
        """
        self.fc = fc
        self.fs = fs
        self.filter_type = filter_type
        self.ch_numb = ch_numb

        # Calculate RC and alpha
        self.RC = 1 / (2 * np.pi * fc)
        if filter_type == "lowpass":
            self.alpha = 1 / (1 + fs * self.RC)
        else:  # highpass
            self.alpha = self.RC / (self.RC + 1 / fs)

        self.state = None
        self.initialized = False

    def initialize(self, first_sample: np.ndarray):
        """Initialize filter state with first sample."""
        self.state = first_sample[0, :].copy()
        self.initialized = True

    def filter(self, data: np.ndarray) -> np.ndarray:
        """Apply EMA filter to data.

        Args:
            data: Input data of shape (samples, channels)

        Returns:
            Filtered data of same shape
        """
        if not self.initialized:
            self.initialize(data)

        output = np.empty_like(data)
        for i in range(data.shape[0]):
            self.state = self.alpha * data[i, :] + (1 - self.alpha) * self.state
            if self.filter_type == "lowpass":
                output[i, :] = self.state
            else:  # highpass: output = input - lowpass
                output[i, :] = data[i, :] - self.state
        return output


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


class MyoGestic(ScalableMainWindow):
    """
    Main window of the MyoGestic application.

    This class is the main window of the MyoGestic application. It contains the
    main user interface and connects the different parts of the application.

    Inherits from ScalableMainWindow to provide zoom-like scaling behavior,
    allowing the UI to scale proportionally when the window is resized.

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
        # Initialize with the original design dimensions from main_window.ui
        super().__init__(original_width=1000, original_height=960, allow_upscaling=True)

        # Setup UI on self (requires QMainWindow methods like setCentralWidget)
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

        # Connect device status signals for user feedback
        self.device__widget.connect_toggled.connect(self._on_device_connect_toggled)
        self.device__widget.stream_toggled.connect(self._on_device_stream_toggled)

        # Add tooltips for better usability
        self.ui.timeShownDoubleSpinBox.setToolTip("Adjust the time window displayed in the EMG plot (in seconds)")
        self.ui.toggleVispyPlotCheckBox.setToolTip("Show/hide the EMG signal plot while streaming")

        self.ui.timeShownDoubleSpinBox.valueChanged.connect(self._reconfigure_plot)

        # Device parameters
        self._device_name: DeviceType | None = None
        self._sampling_frequency = None
        self._samples_per_frame = None
        self._number_of_channels = None

        # EMG Filters for real-time processing (sessantaquattro)
        self._emg_filters: EMGfilters | None = None
        self._ema_highpass: ExponentialMovingAverage | None = None
        self._ema_lowpass: ExponentialMovingAverage | None = None

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

        # Active visual interfaces (multiple can be open simultaneously)
        self._active_visual_interfaces: dict[str, VisualInterface] = {}
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

        # Default Recording Interface (shown when no VI is open)
        self._default_recording_interface = DefaultRecordingInterface(self)
        self._default_recording_interface.initialize()
        # Hide VI-specific recording GroupBoxes initially (review is always hidden per-VI)
        for vi in self._visual_interfaces__dict.values():
            vi.recording_interface_ui.ui.recordRecordingGroupBox.hide()

        # Finalize recording layout: add the unified review widget at the bottom
        # (after all per-VI GroupBoxes have been added to the layout)
        self.protocols[0].finalize_layout()

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

        # Enable hybrid scaling - the plot widget stays native (for OpenGL compatibility)
        # while the tab widget (controls) scales proportionally
        # This must be called AFTER all UI setup is complete
        self._setup_hybrid_scaling()

    def _setup_hybrid_scaling(self) -> None:
        """
        Set up hybrid scaling with the controls panel scaled and the plot native.

        This extracts the tab widget and plot area, then uses enableHybridScaling
        to make the controls scale while keeping the OpenGL plot native.
        """
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

        # Create a container for the plot area (plot controls + plot widget)
        plot_container = QWidget()
        plot_layout = QVBoxLayout(plot_container)
        plot_layout.setContentsMargins(5, 5, 5, 5)
        plot_layout.setSpacing(5)

        # Create a horizontal layout for the plot controls
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addWidget(self.ui.toggleVispyPlotCheckBox)
        controls_layout.addWidget(self.ui.label_9)
        controls_layout.addWidget(self.ui.timeShownDoubleSpinBox)
        controls_layout.addStretch()

        # Add controls and plot to the container
        plot_layout.addLayout(controls_layout)
        plot_layout.addWidget(self._plot__widget)

        # Remove the minimum size constraint from the plot widget
        # so the splitter can resize proportionally
        self._plot__widget.setMinimumSize(QSize(0, 0))

        # Get the tab widget - it will be scaled
        tab_widget = self.ui.mindMoveTabWidget

        # Use the original design size for the tab widget
        # In the 1000x960 design, the tab widget is approximately 480px wide
        # (~48% of 1000px) and 920px tall (full height minus padding)
        scalable_size = QSize(480, 920)

        # Enable hybrid scaling
        self.enableHybridScaling(tab_widget, plot_container, scalable_size)

    def toggle_selected_visual_interface(self, name: str) -> None:
        """
        Toggles a visual interface on/off.

        This method adds or removes a visual interface from the active set.
        Multiple interfaces can be active simultaneously.
        It manages the visibility of per-VI recording GroupBoxes and the
        default recording GroupBox.

        Parameters
        ----------
        name : str
            Name of the visual interface to toggle.
        """
        vi = self._visual_interfaces__dict[name]

        if name in self._active_visual_interfaces:
            # VI is being closed
            del self._active_visual_interfaces[name]
            vi.recording_interface_ui.ui.recordRecordingGroupBox.hide()
            vi.enable_ui()

            # If no active VIs remain, show default recording interface
            if not self._active_visual_interfaces:
                self._default_recording_interface.show()
        else:
            # VI is being opened
            self._active_visual_interfaces[name] = vi

            # Hide default recording interface when any VI is active
            self._default_recording_interface.hide()

            # Show the per-VI recording GroupBox (task selector, etc.)
            vi.recording_interface_ui.ui.recordRecordingGroupBox.show()

        self._protocol__helper_class._pass_on_selected_visual_interface()


    @property
    def active_visual_interfaces(self) -> dict[str, "VisualInterface"]:
        """
        Get the dictionary of active visual interfaces.

        Returns
        -------
        dict[str, VisualInterface]
            Dictionary mapping VI names to their instances.
        """
        return self._active_visual_interfaces

    @property
    def selected_visual_interface(self) -> Optional["VisualInterface"]:
        """
        Backward-compatible property returning the first active visual interface.

        For recording purposes, returns the first (primary) active VI.
        Returns None if no VIs are active.

        Returns
        -------
        Optional[VisualInterface]
            The first active visual interface, or None if none are active.
        """
        if not self._active_visual_interfaces:
            return None
        # Return the first active VI (for recording purposes)
        return next(iter(self._active_visual_interfaces.values()))

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
            # Apply real-time EMA filters for sessantaquattro
            if self._device_name == "Sessantaquattro" and self._ema_highpass is not None:
                # Reshape data for filtering: (samples, channels)
                filtered_data = data[: self._number_of_channels].T

                # Apply filter chain: highpass (10 Hz) -> lowpass (500 Hz)
                filtered_data = self._ema_highpass.filter(filtered_data)
                filtered_data = self._ema_lowpass.filter(filtered_data)

                # Reshape back to (channels, samples)
                filtered_data = filtered_data.T
                scale_factor = 5

            else:
                # Default processing for other devices
                filtered_data = data[: self._number_of_channels]
                scale_factor = 5  # Default scale

            self._plot__widget.update_plot(filtered_data * scale_factor)

    def _on_device_connect_toggled(self, is_connected: bool) -> None:
        """Handle device connection status changes."""
        if is_connected:
            self.logger.print("Device connected successfully!")
            self.ui.statusbar.showMessage("Device connected - Ready to configure", 5000)
        else:
            self.logger.print("Device disconnected.")
            self.ui.statusbar.showMessage("Device disconnected", 5000)

    def _on_device_stream_toggled(self, is_streaming: bool) -> None:
        """Handle device streaming status changes."""
        if is_streaming:
            self.logger.print("Streaming started!")
            self.ui.statusbar.showMessage("Streaming EMG data...", 5000)
        else:
            self.logger.print("Streaming stopped.")
            self.ui.statusbar.showMessage("Streaming stopped", 5000)

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

        self.logger.print("Device configured successfully!")
        self.ui.statusbar.showMessage("Device configured - Ready to stream", 5000)

        device_information = self.device__widget.get_device_information()
        self._device_name = device_information["name"]
        self._sampling_frequency = device_information["sampling_frequency"]
        self._samples_per_frame = device_information["samples_per_frame"]
        self._number_of_channels = device_information["number_of_biosignal_channels"]

        # Initialize EMA filters for sessantaquattro
        if self._device_name == "Sessantaquattro":
            self.logger.print("Initializing EMA filters for Sessantaquattro...")
            hp_fc = 10   # Highpass cutoff (Hz)
            lp_fc = 500  # Lowpass cutoff (Hz)
            self._ema_highpass = ExponentialMovingAverage(
                fc=hp_fc,
                fs=self._sampling_frequency,
                filter_type="highpass",
                ch_numb=self._number_of_channels
            )
            self._ema_lowpass = ExponentialMovingAverage(
                fc=lp_fc,
                fs=self._sampling_frequency,
                filter_type="lowpass",
                ch_numb=self._number_of_channels
            )
            self.logger.print(f"EMA filters: HP={hp_fc}Hz (α={self._ema_highpass.alpha:.4f}), LP={lp_fc}Hz (α={self._ema_lowpass.alpha:.4f})")
            self._emg_filters = None  # Keep for legacy, not used
        else:
            self._ema_highpass = None
            self._ema_lowpass = None
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
