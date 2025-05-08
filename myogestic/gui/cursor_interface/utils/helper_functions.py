import math
import numpy as np  # Import numpy

# from myogestic.gui.cursor_interface.constants import AXIS_END_VALUES # Updated import - Incorrect path
from myogestic.gui.cursor_interface.utils.constants import (
    AXIS_END_VALUES,
    CURSOR_SAMPLING_RATE,
)  # Corrected import path


def generate_sinusoid_trajectory(
    signal_frequency: float, direction: str, sampling_rate: float = CURSOR_SAMPLING_RATE, amplitude: float = 1.0
) -> np.ndarray:
    """Generates a full period trajectory array (x, y) for sinusoidal movement.

    Moves from (0,0) towards the target coordinate defined by AXIS_END_VALUES[direction]
    and back to (0,0) sinusoidally over one period.

    Args:
        signal_frequency: The frequency of the sine wave in Hz (how many periods per second).
        direction: The target direction ("Up", "Down", "Left", "Right").
        sampling_rate: The number of points to calculate for the trajectory (Hz).
        amplitude: The maximum displacement factor (defaults to 1.0).

    Returns:
        A numpy array of shape (num_steps, 2) containing (x, y) coordinates.
        Returns an empty array if signal_frequency or sampling_rate is non-positive.
    """
    if signal_frequency <= 0 or sampling_rate <= 0:
        return np.empty((0, 2))  # Return empty array for invalid inputs

    # Calculate number of steps for one full period
    num_steps = int(round(sampling_rate / signal_frequency))
    if num_steps <= 0:
        return np.empty((0, 2))

    # Get the target coordinate for the direction
    target_x, target_y = AXIS_END_VALUES.get(direction, (0.0, 0.0))

    trajectory = np.zeros((num_steps, 2))
    time_steps = np.linspace(0, 1.0 / signal_frequency, num_steps, endpoint=False)

    for i, t in enumerate(time_steps):
        # Calculate the displacement magnitude (0 -> amplitude -> 0)
        angle = 2 * math.pi * signal_frequency * t
        displacement_magnitude = amplitude * (1 - math.cos(angle)) / 2.0

        # Scale the target coordinates by the displacement magnitude
        x_pos = target_x * displacement_magnitude
        y_pos = target_y * displacement_magnitude
        trajectory[i] = [x_pos, y_pos]

    return trajectory


# Remove the old function if it exists (or keep if needed elsewhere)
# def calculate_sinusoidal_displacement(...)
