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
    main_window : MyoGestic
        The main window of the MyoGestic application.

    Attributes
    ----------
    main_window : MyoGestic
        The main window of the MyoGestic application.
    available_protocols : list[RecordProtocol | TrainingProtocol | OnlineProtocol]
        The available protocols of the MyoGestic application. The protocols are:
        - RecordProtocol
        - TrainingProtocol
        - OnlineProtocol
    _current_protocol : RecordProtocol | TrainingProtocol | OnlineProtocol | None
        The current protocol that is selected by the user.
    """

    def __init__(self, main_window: MyoGestic) -> None:
        super().__init__(main_window)

        self.main_window = main_window

        # Initialize Protocol UI
        self._setup_protocol_ui()

        # Initialize Protocol
        self._current_protocol: Optional[
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
            self._protocol_mode__stacked_widget.setCurrentIndex(index)
            self._current_protocol = self.available_protocols[index]

    def _pass_on_selected_visual_interface(self) -> None:
        for protocol in self.available_protocols:
            protocol._selected_visual_interface = (
                self.main_window.selected_visual_interface
            )
            protocol._active_visual_interfaces = (
                self.main_window.active_visual_interfaces
            )

        # Rebuild the shared task selector in the RecordProtocol
        record_protocol = self.available_protocols[0]
        record_protocol._rebuild_shared_task_selector()

    def _setup_protocol_ui(self):
        self._protocol_mode__stacked_widget = (
            self.main_window.ui.protocolModeStackedWidget
        )
        self._protocol_mode__stacked_widget.setCurrentIndex(0)

        self._protocol_record__radio_button = (
            self.main_window.ui.protocolRecordRadioButton
        )
        self._protocol_record__radio_button.setChecked(True)
        self._protocol_record__radio_button.setToolTip(
            "Record EMG data with visual interface feedback for training"
        )
        self._protocol_record__radio_button.toggled.connect(
            lambda checked: self._protocol_toggled(0, checked)
        )

        self._protocol_training__radio_button = (
            self.main_window.ui.protocolTrainingRadioButton
        )
        self._protocol_training__radio_button.setToolTip(
            "Create datasets from recordings and train machine learning models"
        )
        self._protocol_training__radio_button.toggled.connect(
            lambda checked: self._protocol_toggled(1, checked)
        )

        self._protocol_online__radio_button = (
            self.main_window.ui.protocolOnlineRadioButton
        )
        self._protocol_online__radio_button.setToolTip(
            "Run real-time predictions using trained models"
        )
        self._protocol_online__radio_button.toggled.connect(
            lambda checked: self._protocol_toggled(2, checked)
        )
