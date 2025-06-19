"""Constants specific to the Cursor Interface utilities."""

TASKS = ["Rest", "Dorsiflexion", "Plantarflexion", "Inversion", "Eversion"]  # Define the tasks (movements)
DIRECTIONS = ["Rest", "Up", "Down", "Right", "Left"]  # Define the directions the user can select

# Mapping between cursor movement directions and their corresponding target values
AXIS2TARGET_VALUES = {
    "Up": (0.0, 1.0),
    "Down": (0.0, -1.0),
    "Left": (-1.0, 0.0),
    "Right": (1.0, 0.0),
    "Rest": (0.0, 0.0),  # Added Rest for completeness, though movement won't occur
}

# Mapping between task names and their corresponding labels for cursor tasks. Inactive used when cursor is paused.
# Rest used when the cursor is active but not moving
CURSOR_TASK2LABEL_MAP = {
    "Inactive": -1,
    "Rest": 0,
    "Up": 1,
    "Down": 2,
    "Right": 3,
    "Left": 4,
}

# Mapping between FES movement names and their corresponding labels for FES tasks. Used to encode the task name to
# stream to the external FES device.
FES_MOVEMENT2LABEL_MAP = {
    "Rest": 0,
    "Dorsiflexion": 1,
    "Plantarflexion": 2,
    "Inversion": 3,
    "Eversion": 4,
}
