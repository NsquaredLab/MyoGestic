import sys
from pathlib import Path

REQUIRED_RECORDING_KEYS = {
    "biosignal",
    "biosignal_timings",
    "ground_truth",
    "ground_truth_timings",
    "recording_label",
    "task",
    "ground_truth_sampling_frequency",
    "device_information",
    "recording_time",
    "use_as_classification",
    "bad_channels",
}

# PORTS
MYOGESTIC_UDP_PORT = 1233

BASE_PATH = Path("data")

# _MEIPASS is a PyInstaller specific attribute that is set when the application is run as a frozen executable.
if hasattr(sys, "_MEIPASS"):
    # BASE_PATH = os.path.expanduser("~")
    # BASE_PATH = os.path.join(BASE_PATH, "MyoGestic")
    BASE_PATH = Path.home() / "MyoGestic"

RECORDING_DIR_PATH = BASE_PATH / "recordings"
MODELS_DIR_PATH = BASE_PATH / "models"
DATASETS_DIR_PATH = BASE_PATH / "datasets"
PREDICTIONS_DIR_PATH = BASE_PATH / "predictions"

MONITORING_WIDGETS_EXCHANGE_DIR_PATH = BASE_PATH / "monitoring_widgets_exchange"

# Repeatable Texts
NO_DATASET_SELECTED_INFO = "No dataset selected!"
