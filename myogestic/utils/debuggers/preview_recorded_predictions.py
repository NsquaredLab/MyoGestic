import pickle
from pathlib import Path

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np

from myogestic.user_config import CHANNELS


def get_last_created_file(directory_path):
    # Create a Path object for the directory
    directory = Path(directory_path)

    # Get all files in the directory
    files = [file for file in directory.iterdir() if file.is_file()]

    if not files:
        return None  # If no files are found

    # Sort files by creation time (use key=file.stat().st_ctime for creation time on Unix)
    last_created_file = max(files, key=lambda file: file.stat().st_ctime)

    return last_created_file


last_file = get_last_created_file("../../data/predictions")

data = pickle.load(open(last_file, "rb"))

emg = data["emg"]
emg_timings = data["emg_timings"]

kinematics = data["kinematics"]
kinematics_timings = data["kinematics_timings"]

predictions_before_filters = data["predictions_before_filters"]
predictions_before_filters_timings = data["predictions_before_filters_timings"]

predictions_after_filters = data["predictions_after_filters"]
predictions_after_filters_timings = data["predictions_after_filters_timings"]

predicted_hand = np.array(data["predicted_hand"])
predicted_hand_timings = data["predicted_hand_timings"]

selected_real_time_filters = data["selected_real_time_filters"]


# Create a figure
fig = plt.figure(figsize=(10, 6))

# Set up a GridSpec with a 2x2 layout, reserving more space for the left column
gs = gridspec.GridSpec(6, 2)

# First subplot (top left)
ax1 = fig.add_subplot(gs[:3, 0])
samples = np.arange(0, emg.shape[1])
for i in CHANNELS:
    for j in range(emg.shape[-1]):
        ax1.plot(samples + (j * emg.shape[1]), emg[i, :, j] + i, color="black")
ax1.set_title("EMG")

ax2 = fig.add_subplot(gs[3:, 0])
for i, joint in enumerate(kinematics):
    ax2.plot(kinematics_timings, joint + i)
ax2.set_title("Requested Kinematics")

ax3 = fig.add_subplot(gs[:2, 1])
for i, joint in enumerate(predictions_before_filters):
    ax3.plot(predictions_before_filters_timings, joint + i)
ax3.set_title("Predictions Before Filters")

ax4 = fig.add_subplot(gs[2:4, 1])
for i, joint in enumerate(predictions_after_filters):
    ax4.plot(predictions_after_filters_timings, joint + i)
ax4.set_title("Predictions After Filters")

ax5 = fig.add_subplot(gs[4:, 1])
for i, joint in enumerate(predicted_hand[[0, 2, 3, 4, 5]]):
    ax5.plot(predicted_hand_timings, joint + i)
ax5.set_title("Predicted Hand")

# Adjust layout so that subplots fit nicely
fig.tight_layout()

# Show the figure
plt.show()
