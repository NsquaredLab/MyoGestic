"""Signal-viewer widgets for live stream data (raw traces, decimated viewer, panel)."""

from myogestic.widgets.signals.device_picker import (
    DEFAULT_DEVICES,
    LSL_DEVICE,
    OTB_DEVICES,
    SYNTHETIC_DEVICE,
    DeviceOption,
    DeviceParam,
    DevicePicker,
    DeviceSpec,
)
from myogestic.widgets.signals.raw import RawSignalViewer
from myogestic.widgets.signals.stream_panel import StreamPanel
from myogestic.widgets.signals.viewer import SignalViewer

__all__ = [
    "DEFAULT_DEVICES",
    "LSL_DEVICE",
    "OTB_DEVICES",
    "SYNTHETIC_DEVICE",
    "DeviceSpec",
    "DevicePicker",
    "DeviceParam",
    "DeviceOption",
    "RawSignalViewer",
    "SignalViewer",
    "StreamPanel",
]
