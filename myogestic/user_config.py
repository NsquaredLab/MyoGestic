from typing import Literal

import numpy as np
from biosignal_device_interface.constants.devices.core.base_device_constants import (
    DeviceType,
)
from myoverse.datasets.filters.temporal import RMSFilter
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.multioutput import MultiOutputRegressor

from myogestic.gui.widgets.output_systems.neuroorthosis import NeuroOrthosisOutputSystem
from myogestic.models.definitions import sklearn_models
from myogestic.utils.config import CONFIG_REGISTRY

# What channels to use for training
CHANNELS: list[int] = list(np.arange(32))

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
GROUND_TRUTH_INDICES_TO_KEEP: list[int] | Literal["all"] = [0, 2, 3, 4, 5]

# Register models
CONFIG_REGISTRY.register_model(
    "Linear Regressor Per Finger",
    lambda **params: MultiOutputRegressor(LinearRegression(**params)),
    False,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
)

CONFIG_REGISTRY.register_model(
    "Ridge Regressor Per Finger",
    lambda **params: MultiOutputRegressor(Ridge(**params)),
    False,
    sklearn_models.save,
    sklearn_models.load,
    sklearn_models.train,
    sklearn_models.predict,
)

CONFIG_REGISTRY.register_output_system("NEUROORTHOSIS", NeuroOrthosisOutputSystem)


# Register features
class RMSFilterFixedWindow(RMSFilter):
    def __init__(
        self, input_is_chunked: bool, is_output: bool = False, name: str = None
    ):
        super().__init__(
            window_size=120,
            is_output=is_output,
            name=name,
            input_is_chunked=input_is_chunked,
        )


CONFIG_REGISTRY.register_feature("RMS Small Window", RMSFilterFixedWindow)
