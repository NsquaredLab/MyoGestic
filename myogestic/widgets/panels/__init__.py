"""Panel widgets: logo, filter controls, logs, popouts, process launcher, recording."""

from myogestic.widgets.panels.app_logo import app_logo
from myogestic.widgets.panels.filter_controls import FilterControl
from myogestic.widgets.panels.log_panel import log_panel
from myogestic.widgets.panels.popout import popout_panel
from myogestic.widgets.panels.process_launcher import process_launcher
from myogestic.widgets.panels.recording import recording_controls

__all__ = [
    "FilterControl",
    "app_logo",
    "log_panel",
    "popout_panel",
    "process_launcher",
    "recording_controls",
]
