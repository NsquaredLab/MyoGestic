"""
====================================
Adding a Custom Biosignal Feature
====================================

Below is an example of how to create and register a new feature by inheriting from
a base filter class from `MyoVerse <https://nsquaredlab.github.io/MyoVerse/modules/filters.html>`_.

This custom feature calculates the variance of the input signal.

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
----------------
1. **Define** a new feature class inheriting from the base class.
2. **Implement** the core logic in the ``_filter`` method.
3. **Register** the feature so it becomes available globally.

"""

import numpy as np
from myogestic.utils.config import CONFIG_REGISTRY
# Ensure this import references your actual base class location:
from myoverse.datasets.filters._template import FilterBaseClass


# %%
# --------------------------------
# Step 1: Inherit and define logic
# --------------------------------
class MyVarianceFeature(FilterBaseClass):
    """
    A feature that computes the variance of the input signal.

    Parameters
    ----------
    input_is_chunked : bool, optional
        Indicates whether the input data is chunked.
    allowed_input_type : Literal["both", "chunked", "not chunked"], optional
        Whether the filter accepts chunked, unchunked, or both.
    is_output : bool, optional
        If True, this feature's output is set as a final output in the pipeline.
    """

    def _filter(self, input_array: np.ndarray) -> np.ndarray:
        """
        Compute the variance of the input signal.

        Parameters
        ----------
        input_array : np.ndarray
            The data on which variance is computed.

        Returns
        -------
        np.ndarray
            The variance output as a single-element array, for consistency.
        """
        return np.array([np.var(input_array)], dtype=float)


# %%
# -----------------------------------------------
# Step 2: Register the custom feature
# -----------------------------------------------
CONFIG_REGISTRY.register_feature("My Variance Feature", MyVarianceFeature)


# %%
# -----------------------------------------------
# Example Usage
# -----------------------------------------------
if __name__ == "__main__":
    # Create a small signal for demonstration
    sample_data = np.array([1.2, 2.5, 2.7, 2.8, 3.1])

    # Instantiate and apply the feature
    feature_instance = MyVarianceFeature(
        input_is_chunked=False,
        allowed_input_type="not chunked"
    )
    variance_value = feature_instance(sample_data)

    print(f"Variance of {sample_data} = {variance_value[0]:.4f}")
