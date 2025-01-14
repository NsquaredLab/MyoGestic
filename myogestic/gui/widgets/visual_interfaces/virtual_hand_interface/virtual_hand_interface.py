from typing import Type

from PySide6.QtCore import SignalInstance

from myogestic.gui.widgets.templates.visual_interface import VisualInterfaceTemplate, SetupUITemplate, \
    RecordingUITemplate
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface.recording_interface import \
    VirtualHandInterfaceRecordingUI
from myogestic.gui.widgets.visual_interfaces.virtual_hand_interface.setup_interface import VirtualHandInterfaceSetupUI


class VirtualHandInterface(VisualInterfaceTemplate):
    def __init__(
        self,
        main_window,
        name="VirtualHandInterface",
        setup_interface_ui: Type[SetupUITemplate] = VirtualHandInterfaceSetupUI,
        recording_interface_ui: Type[RecordingUITemplate] = VirtualHandInterfaceRecordingUI,
    ):
        super().__init__(main_window, name, setup_interface_ui, recording_interface_ui)

        self.predicted_hand_signal: SignalInstance = self.setup_interface_ui.__predicted_hand_signal # noqa
