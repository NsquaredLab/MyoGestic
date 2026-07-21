"""Panel widgets: image/logo, filter controls, logs, popouts, process launcher, recording."""

from myogestic.widgets.panels.app_logo import AppLogo
from myogestic.widgets.panels.filter_processor import (
    BUILTIN_FILTERS,
    FilterParam,
    FilterProcessor,
    FilterSpec,
    PostProcessor,
)
from myogestic.widgets.panels.image import Image
from myogestic.widgets.panels.log_panel import LogPanel
from myogestic.widgets.panels.popout import popout_panel
from myogestic.widgets.panels.process_launcher import ProcessLauncher
from myogestic.widgets.panels.recording import RecordingControls

__all__ = [
    "BUILTIN_FILTERS",
    "AppLogo",
    "FilterParam",
    "FilterProcessor",
    "FilterSpec",
    "Image",
    "LogPanel",
    "PostProcessor",
    "ProcessLauncher",
    "RecordingControls",
    "popout_panel",
]
