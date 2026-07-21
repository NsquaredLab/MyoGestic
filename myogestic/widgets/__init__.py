"""Reusable ImGui widgets for building MyoGestic ``@app.ui`` functions."""

from myogestic.widgets.common import panel_header
from myogestic.widgets.panels import (
    BUILTIN_FILTERS,
    AppLogo,
    FilterParam,
    FilterProcessor,
    FilterSpec,
    Image,
    LogPanel,
    PostProcessor,
    ProcessLauncher,
    RecordingControls,
    popout_panel,
)
from myogestic.widgets.plots import Heatmap, LinePlot, Scatter2D, Scatter3D
from myogestic.widgets.signals import (
    RawSignalViewer,
    SignalViewer,
    StreamPanel,
)
from myogestic.widgets.training import (
    FeatureSelector,
    PredictionLabel,
    SessionManager,
    TemplateInspector,
    TemplateInspectorRow,
    TrialPreview,
)
from myogestic.widgets.vhi import (
    VhiMovementPanel,
    VhiStateCache,
    VhiStateSnapshot,
    request_vhi_state_refresh,
    vhi_movement_palette,
)

__all__ = [
    "BUILTIN_FILTERS",
    "AppLogo",
    "FeatureSelector",
    "FilterParam",
    "FilterProcessor",
    "FilterSpec",
    "Heatmap",
    "Image",
    "LinePlot",
    "LogPanel",
    "PostProcessor",
    "PredictionLabel",
    "ProcessLauncher",
    "RawSignalViewer",
    "RecordingControls",
    "Scatter2D",
    "Scatter3D",
    "SessionManager",
    "SignalViewer",
    "StreamPanel",
    "TemplateInspector",
    "TemplateInspectorRow",
    "TrialPreview",
    "VhiMovementPanel",
    "VhiStateCache",
    "VhiStateSnapshot",
    "panel_header",
    "popout_panel",
    "request_vhi_state_refresh",
    "vhi_movement_palette",
]
