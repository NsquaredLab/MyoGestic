"""Constants specific to the Cursor Interface utilities."""

TASKS = ["Rest", "Dorsiflexion", "Plantarflexion", "Inversion", "Eversion"]  # Define the tasks (movements)
DIRECTIONS = ["Rest", "Up", "Down", "Left", "Right"]  # Define the directions the user can select

# Cursor Interface Constants
CURSOR_SAMPLING_RATE = 60  # Hz - Rate at which cursor position is updated
CURSOR_STREAMING_RATE = 60  # Hz - Rate at which cursor positions are being transmitted

AXIS_END_VALUES = {
    "Up": (0.0, 1.0),
    "Down": (0.0, -1.0),
    "Left": (-1.0, 0.0),
    "Right": (1.0, 0.0),
    "Rest": (0.0, 0.0),  # Added Rest for completeness, though movement won't occur
}

CURSOR_TASK_LABEL_MAP = {
    "Inactive": -1,
    "Rest": 0,
    "Up": 1,
    "Down": 2,
    "Right": 3,
    "Left": 4,
}
