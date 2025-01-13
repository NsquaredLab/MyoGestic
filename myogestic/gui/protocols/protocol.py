from __future__ import annotations

from typing import Optional, TYPE_CHECKING, Union

from PySide6.QtCore import QObject

from myogestic.gui.protocols.online import OnlineProtocol
from myogestic.gui.protocols.record import RecordProtocol
from myogestic.gui.protocols.training import TrainingProtocol

if TYPE_CHECKING:
    from myogestic.gui.myogestic import MyoGestic


class Protocol(QObject):
    """
    Class for handling the different protocols of the MyoGestic application.

    Parameters
    ----------
    parent : MyoGestic | None
        The parent object of the protocol object.

    Attributes
    ----------
    main_window : MyoGestic
        The main window of the MyoGestic application.
    protocol_mode_stacked_widget : QStackedWidget
        Stacked widget for displaying the different protocol modes.
    protocol_record_radio_button : QRadioButton
        Radio button for the record protocol.
    protocol_training_radio_button : QRadioButton
        Radio button for the training protocol.
    protocol_online_radio_button : QRadioButton
        Radio button for the online protocol.
    current_protocol : RecordProtocol | TrainingProtocol | OnlineProtocol | None
        The current protocol object.
    available_protocols : list[RecordProtocol | TrainingProtocol | OnlineProtocol]
    """

    def __init__(self, parent: MyoGestic | None = ...) -> None:
        super().__init__(parent)

        self.main_window = parent

        # Initialize Protocol UI
        self._setup_protocol_ui()

        # Initialize Protocol
        self.current_protocol: Optional[
            Union[RecordProtocol, TrainingProtocol, OnlineProtocol]
        ] = None

        self.available_protocols: list[
            Union[RecordProtocol, TrainingProtocol, OnlineProtocol]
        ] = [
            RecordProtocol(self.main_window),
            TrainingProtocol(self.main_window),
            OnlineProtocol(self.main_window),
        ]

    def _protocol_toggled(self, index: int, checked: bool) -> None:
        if checked:
            self.protocol_mode_stacked_widget.setCurrentIndex(index)
            self.current_protocol = self.available_protocols[index]

    def _pass_on_selected_visual_interface(self) -> None:
        for protocol in self.available_protocols:
            protocol.selected_visual_interface = (
                self.main_window.selected_visual_interface
            )

    def _setup_protocol_ui(self):
        self.protocol_mode_stacked_widget = (
            self.main_window.ui.protocolModeStackedWidget
        )
        self.protocol_mode_stacked_widget.setCurrentIndex(0)
        self.protocol_record_radio_button = (
            self.main_window.ui.protocolRecordRadioButton
        )
        self.protocol_record_radio_button.setChecked(True)
        self.protocol_record_radio_button.toggled.connect(
            lambda checked: self._protocol_toggled(0, checked)
        )
        self.protocol_training_radio_button = (
            self.main_window.ui.protocolTrainingRadioButton
        )
        self.protocol_training_radio_button.toggled.connect(
            lambda checked: self._protocol_toggled(1, checked)
        )

        self.protocol_online_radio_button = (
            self.main_window.ui.protocolOnlineRadioButton
        )
        self.protocol_online_radio_button.toggled.connect(
            lambda checked: self._protocol_toggled(2, checked)
        )
