"""
===========================================================
Add a Post-Prediction Filter
===========================================================

This example demonstrates how to create and register a new **real-time**
post-prediction filter in MyoGestic, allowing you to smooth or transform
model outputs in real time after predictions are made.

Post-prediction filters are applied during the **Online** protocol.  Each
time a new prediction arrives, the filter receives the entire history
buffer (up to 5 seconds of past predictions) and must return a filtered
array of the same shape.  The most recent entry (position ``-1``) in the
returned array is used as the current prediction.

.. important::
   Post-prediction filters only affect **regression** outputs.
   Classification predictions are discrete labels and are not filtered.

.. note::
   Built-in filters (Identity, Gaussian, Savgol) are defined in
   :mod:`~myogestic.default_config`.

Why Register a New Real-Time Filter?
-------------------------------------
By registering a filter through ``CONFIG_REGISTRY``, you can seamlessly
incorporate custom signal-processing steps without modifying core code.
Your filter will appear in the **Online** tab's filter dropdown.

.. admonition:: Add your filter in :mod:`~myogestic.user_config`

   The :mod:`~myogestic.user_config` module is specifically designed for users to
   register their own components.  This keeps your additions separate
   from core MyoGestic code and simplifies future upgrades.

Example Overview
-----------------
1. **Define** a filtering function.
2. **Register** it in ``CONFIG_REGISTRY`` so that MyoGestic recognises it.

"""

# %%
# -----------------------------------
# Step 1: Define a Filtering Function
# -----------------------------------
# A filter function receives a **list of lists** of float values -- the
# buffered regression outputs from recent predictions.  The buffer grows
# over time (up to ~5 seconds of data), with the most recent prediction
# at position ``-1``.
#
# The function must return a filtered array **of the same shape**.  The
# entry at position ``-1`` in the returned array becomes the current
# (filtered) prediction sent to the output system.

import numpy as np
from scipy.ndimage import gaussian_filter


def my_awesome_gaussian_filter(data):
    """Apply a 1-D Gaussian filter along the time axis (axis 0).

    Parameters
    ----------
    data : list[list[float]]
        Buffered regression predictions.  Shape is ``(n_timesteps, n_dof)``.

    Returns
    -------
    np.ndarray
        Smoothed predictions with the same shape as the input.
    """
    return gaussian_filter(np.array(data), sigma=15, order=0, axes=(0,))


# %%
# ---------------------------------------------------
# Step 2: Register the Filter in CONFIG_REGISTRY
# ---------------------------------------------------
# Place this code in :mod:`~myogestic.user_config`.  The filter name must be unique
# and will appear in the Online tab's filter dropdown.

from myogestic.utils.config import CONFIG_REGISTRY

CONFIG_REGISTRY.register_real_time_filter(
    name="MyAwesomeGaussian",
    function=my_awesome_gaussian_filter,
)

# %%
# ----------------------------
# Reference: Built-in Filters
# ----------------------------
# The following filters are registered in :mod:`~myogestic.default_config`:
#
# .. code-block:: python
#
#    # Identity -- pass through unchanged
#    CONFIG_REGISTRY.register_real_time_filter("Identity", lambda x: x)
#
#    # Gaussian -- smooth with sigma=15
#    CONFIG_REGISTRY.register_real_time_filter(
#        "Gaussian",
#        lambda x: gaussian_filter(np.array(x), 15, 0, axes=(0,)),
#    )
#
#    # Savgol -- Savitzky-Golay filter
#    CONFIG_REGISTRY.register_real_time_filter(
#        "Savgol",
#        lambda x: savgol_filter(np.array(x), 111, 3, axis=0),
#    )
