from typing import Literal

import torch
from biosignal_device_interface.constants.devices.core.base_device_constants import DeviceType
from myoverse.transforms import RMS, Transform

from myogestic.gui.widgets.output_systems.neuroorthosis import NeuroOrthosisOutputSystem
from myogestic.utils.config import CONFIG_REGISTRY

# What channels to use for training
CHANNELS: list[int] = list(range(32))

# What device to show in the GUI by default. Useful for experiments.
DEFAULT_DEVICE_TO_USE = DeviceType.OTB_QUATTROCENTO_LIGHT.value

# Processing buffer sizes
# If BUFFER_SIZE__SAMPLES is set, the buffer for all devices will be this many samples long
# This might not be the best approach because 360 samples mean different time windows for different frequencies
# If BUFFER_SIZE__CHUNKS is set, the buffer for all devices will be this many chunks long.
# Set BUFFER_SIZE__SAMPLES to -1 to use BUFFER_SIZE__CHUNKS
BUFFER_SIZE__SAMPLES: int = -1
BUFFER_SIZE__CHUNKS: int = 20

# Ground Truth Settings
# The indices of the ground truth to keep. This can be useful if you know for your experiment that some ground truth indices are always 0.

GROUND_TRUTH_INDICES_TO_KEEP: dict[Literal, list] | Literal["all"] = {
    "VHI": [0, 2, 3, 4, 5],
    "VCI": [0, 1],
    "KHI": [0, 1, 2, 3, 4, 5, 6],
    "Default": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],  # All 10 VHI-style movements
}

CONFIG_REGISTRY.register_output_system("NEUROORTHOSIS", NeuroOrthosisOutputSystem)


class RMSSmallWindow(Transform):
    """RMS transform with sliding window (120 samples, stride 1).

    Computes RMS over a 120-sample window that slides 1 sample at a time.
    For a 360-sample input, this produces 241 output time points (360 - 120 + 1).
    """

    def __init__(self, dim: str = "time", window_size: int = 120, stride: int = 1, **kwargs):
        super().__init__(dim=dim, **kwargs)
        self.window_size = window_size
        self.stride = stride

    def _apply(self, x: torch.Tensor) -> torch.Tensor:
        # x shape: (channels, time) with named dimensions
        dim_idx = x.names.index(self.dim) if x.names[0] is not None else -1

        # Remove names for unfold operation
        x_unnamed = x.rename(None)

        # Use unfold to create sliding windows: (channels, n_windows, window_size)
        windows = x_unnamed.unfold(dim_idx, self.window_size, self.stride)

        # Compute RMS over each window (last dimension)
        rms = torch.sqrt(torch.mean(windows ** 2, dim=-1))

        # Restore dimension names
        return rms.rename(*x.names)


# RMS Small Window now uses sliding window (stride=1), preserving temporal resolution.
# 360 samples → 241 time points, compatible with RaulNet's Conv3d layers.
CONFIG_REGISTRY.register_feature(
    "RMS Small Window", RMSSmallWindow, requires_temporal_preservation=True
)
