"""
===========================================================
Add a Post-Prediction Filter
===========================================================

This example demonstrates how to create and register a new **real-time**
post-prediction filter in MyoGestic, allowing you to process or smooth
model outputs in real time after predictions are made.

.. important::
   The post-prediction filters will only affect regression outputs.

.. note::
   Reference examples can be found in ``default_config.py``.

Why Register a New Real-Time Filter?
------------------------------------
By registering a filter through the provided registry, you can seamlessly
incorporate custom signal-processing steps without modifying core code.

.. admonition:: We Recommend Implementing any Additions in *user_config.py*

   The *user_config.py* module is specifically designed for end-users to register
   and configure their own custom components such as models, features,
   and filters. This keeps your modifications modular, reduces conflicts with
   core MyoGestic settings, and simplifies upgrades in the future.

   .. important::
      By registering your addition in ``user_config.py``, you ensure that your custom
      configuration stays separate from core MyoGestic functionality and remains
      compatible with future updates.

Example Overview
---------------
1. **Create** a filtering function.
2. **Register** it in the "Config Registry" so that it is recognized by MyoGestic.

"""

# %%
# -----------------------------------
# Step 1: Define a Filtering Function
# -----------------------------------
# The input of a filter function is a list of lists containing float values outputted by a regression model.
#
# This list represents 5 seconds of temporal data, with the last entry (position -1) corresponding to the most recent prediction.
#
# The user can define how to process this data.
#
# The function should return a filtered list or array of the same size, ensuring that the most recent prediction (position -1) remains the filtered current prediction.

import numpy as np
from scipy.ndimage import gaussian_filter
def my_awesome_gaussian_filter(data):
    return gaussian_filter(np.array(data), 15, 0, axes=(0,))

# %%
# ---------------------------------------------
# Step 2: Register the Filter in user_config.py
# ---------------------------------------------

from myogestic.utils.config import CONFIG_REGISTRY  # Ensure CONFIG_REGISTRY is accessible

CONFIG_REGISTRY.register_real_time_filter(
    name="MyAwesomeMovingAverage",
    function=my_awesome_gaussian_filter,
)
