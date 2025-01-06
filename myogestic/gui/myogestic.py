from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QCheckBox, QLabel, QMainWindow, QGroupBox, QVBoxLayout
from biosignal_device_interface.constants.devices.core.base_device_constants import (
    DeviceType,
)

from myogestic.gui.main_window_v2 import Ui_MyoGestic
from myogestic.gui.biosignal import Ui_BioSignalInterface
from myogestic.gui.protocols.protocol import Protocol
from myogestic.gui.widgets.logger import CustomLogger
from myogestic.gui.widgets.output import VirtualHandInterface
from myogestic.utils.constants import BASE_PATH
from myogestic.utils.config import (
    _set_config_registry,
    custom_message_handler,
    CONFIG_REGISTRY,
)  # noqa

if TYPE_CHECKING:
    from biosignal_device_interface.gui.device_template_widgets.otb.otb_devices_widget import (
        OTBDevicesWidget,
    )
    from biosignal_device_interface.gui.plot_widgets.biosignal_plot_widget import (
        BiosignalPlotWidget,
    )

from PySide6.QtCore import qInstallMessageHandler, QtMsgType


class MyoGestic(QMainWindow):
    """
    Main window of the MyoGestic application.

    This class is the main window of the MyoGestic application. It contains the
    main user interface and connects the different parts of the application.

    Attributes
    ----------
    ui : Ui_MyoGestic
        The main user interface of the application.
    update_fps_label : QLabel
        Label for displaying the current update rate of the application.
    fps_buffer : list[float]
        Buffer for storing the update rates of the application.
    time_since_last_fps_update : float
        Time of the last update rate calculation.
    logging_text_edit : QTextEdit
        Text edit widget for logging messages.
    logger : CustomLogger
        Custom logger for logging messages.
    plot : VispyBiosignalPlot
        Plot widget for displaying biosignal data.
    current_bad_channels : list[int] | None
        List of bad channels.
    display_time : int
        Time for displaying the biosignal data.
    device_widget : DeviceWidget
        Widget for configuring and connecting devices.
    device_name : Device
        Name of the connected device.
    sampling_frequency : float
        Sampling frequency of the connected device.
    samples_per_frame : int
        Number of samples per frame.
    number_of_channels : int
        Number of biosignal channels.
    virtual_hand_interface : VirtualHandInterface
        Interface for controlling the virtual hand.
    protocol : Protocol
        Protocol for controlling the application.
    toggle_vispy_plot_check_box : QCheckBox
        Check box for toggling the biosignal plot.
    """

    def __init__(self):
        super().__init__()

        _set_config_registry()

        self.ui = Ui_MyoGestic()
        self.ui.setupUi(self)

        # Install the custom message handler
        qInstallMessageHandler(custom_message_handler)

        # Logging
        self.update_fps_label: QLabel = self.ui.appUpdateFPSLabel
        self.update_fps_label.setText("")
        self.fps_buffer: list[float] = []
        self.time_since_last_fps_update: float = time.time()
        self.logging_text_edit = self.ui.loggingTextEdit
        self.logger: CustomLogger = CustomLogger(self.logging_text_edit)
        self.logger.print("MyoGestic started")

        # Tab Widget
        self.tab_widget = self.ui.mindMoveTabWidget
        self.tab_widget.setCurrentIndex(0)

        # Plot Setup
        self.plot: BiosignalPlotWidget = self.ui.vispyPlotWidget
        self.current_bad_channels: list | None = []
        self.plot.bad_channels_updated.connect(self._update_bad_channels)
        self.display_time = self.ui.timeShownDoubleSpinBox.value()

        # Device Setup
        self.bio_signal_interface = Ui_BioSignalInterface()
        self.bio_signal_interface.setupUi(self)
        self.device_widget: OTBDevicesWidget = self.bio_signal_interface.devicesWidget

        self.ui.setupVerticalLayout.addWidget(self.bio_signal_interface.groupBox)

        self.device_widget.biosignal_data_arrived.connect(self.update)
        self.device_widget.configure_toggled.connect(self._prepare_plot)

        self.ui.timeShownDoubleSpinBox.valueChanged.connect(self._reconfigure_plot)

        # Device parameters
        self.device_name: DeviceType = None
        self.sampling_frequency = None
        self.samples_per_frame = None
        self.number_of_channels = None

        BASE_PATH.mkdir(exist_ok=True, parents=True)

        status_bar = self.ui.statusbar
        status_bar.showMessage(f"Data path: {Path.cwd() / BASE_PATH}")

        # Visual Interface(s) Setup
        self.ui.visualInterfacesGroupBox = QGroupBox("Visual Interfaces")
        self.ui.visualInterfacesGroupBox.setObjectName("visualInterfacesGroupBox")
        self.ui.visualInterfacesVerticalLayout = QVBoxLayout()
        self.ui.setupVerticalLayout.addWidget(self.ui.visualInterfacesGroupBox)
        self.ui.visualInterfacesGroupBox.setLayout(
            self.ui.visualInterfacesVerticalLayout
        )
        self.ui.visualInterfacesVerticalLayout.setContentsMargins(*([15] * 4))

        self.selected_visual_interface = None
        self.visual_interfaces = {}
        for name, main_class in CONFIG_REGISTRY.visual_interfaces_map.items():
            self.visual_interfaces[name] = main_class(self, name=name)

        # Output Setup
        # self.virtual_hand_interface = VirtualHandInterface(self)

        # Protocol Setup
        self.protocol = Protocol(self)

        # Preferences
        self.toggle_vispy_plot_check_box: QCheckBox = self.ui.toggleVispyPlotCheckBox

        self.device_widget.device_selection_combo_box.setCurrentIndex(
            DeviceType.OTB_QUATTROCENTO_LIGHT.value
        )
        # Add shortcuts
        # Toggle plotting shortcut
        toggle_plotting = QShortcut(QKeySequence(Qt.CTRL | Qt.Key_T), self)
        toggle_plotting.activated.connect(self.toggle_vispy_plot_check_box.toggle)

    def _toggle_selected_visual_interface(self, name: str) -> None:
        """
        Toggle the selected visual interface.

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
            for visual_interface in self.visual_interfaces.values():
                visual_interface.enable()
            self.selected_visual_interface = None
        else:
            for visual_interface in self.visual_interfaces.values():
                if visual_interface.name != name:
                    visual_interface.disable()
            self.selected_visual_interface = self.visual_interfaces[name]

        self.protocol._pass_on_selected_visual_interface()


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
        self.current_bad_channels = np.nonzero(bad_channels == 0)[0].tolist()

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
        time_difference = time.time() - self.time_since_last_fps_update
        if time_difference != 0:
            fps = 1 / time_difference
        else:
            fps = 0

        self.fps_buffer.append(fps)
        self.time_since_last_fps_update = time.time()
        self.update_fps_label.setText(f"FPS: {round(np.mean(self.fps_buffer))}")

        # EMG Data
        if self.toggle_vispy_plot_check_box.isChecked():
            self.plot.update_plot(data[: self.number_of_channels] * 5)

    def _prepare_plot(self, is_configured: bool) -> None:
        """
        Prepare the plot.

        This method prepares the plot for displaying biosignal data.

        Returns
        -------
        None
        """
        if not is_configured:
            return

        device_information = self.device_widget.get_device_information()
        self.device_name = device_information["name"]
        self.sampling_frequency = device_information["sampling_frequency"]
        self.samples_per_frame = device_information["samples_per_frame"]
        self.number_of_channels = device_information["number_of_biosignal_channels"]

        self.plot.configure(
            display_time=self.display_time,
            sampling_frequency=self.sampling_frequency,
            lines=self.number_of_channels,
        )

        frames_per_second = int(self.sampling_frequency / self.samples_per_frame)
        fps_buffer = np.zeros(int(frames_per_second))
        self.fps_buffer = fps_buffer.tolist()

    def _reconfigure_plot(self, value) -> None:
        """
        Reconfigure the plot.

        This method reconfigures the plot for displaying biosignal data based on the given value in seconds.

        Returns
        -------
        None
        """
        if self.sampling_frequency is None or self.number_of_channels is None:
            return

        self.plot.configure(
            display_time=value,
            sampling_frequency=self.sampling_frequency,
            lines=self.number_of_channels,
        )
        self.plot.resize(0, 0)

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
        self.device_widget.closeEvent(event)

        for visual_interface in self.visual_interfaces.values():
            visual_interface.close_event(event)

        super().closeEvent(event)
