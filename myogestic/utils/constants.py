import sys
from pathlib import Path

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
