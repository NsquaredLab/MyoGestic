"""
====================================
Adding a Custom Biosignal Feature
====================================

Below is an example of how to create and register a new feature by inheriting from
the base Transform class from `MyoVerse <https://nsquaredlab.github.io/MyoVerse/>`_.

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
1. **Define** a new feature class inheriting from Transform (TensorTransform).
2. **Implement** the core logic in the ``_apply`` method.
3. **Register** the feature so it becomes available globally.

"""

import torch
from myoverse.transforms import Transform
from myoverse.transforms.base import get_dim_index

from myogestic.utils.config import CONFIG_REGISTRY


# %%
# --------------------------------
# Step 1: Inherit and define logic
# --------------------------------
class MyVarianceFeature(Transform):
    """
    A feature that computes the variance of the input signal.

    This transform operates on PyTorch tensors with named dimensions.

    Parameters
    ----------
    dim : str, optional
        The dimension along which to compute variance. Default is 'time'.
    keepdim : bool, optional
        Whether to keep the reduced dimension. Default is False.
    """

    def __init__(self, dim: str = "time", keepdim: bool = False, **kwargs):
        super().__init__(dim=dim, **kwargs)
        self.keepdim = keepdim

    def _apply(self, x: torch.Tensor) -> torch.Tensor:
        """
        Compute the variance of the input signal.

        Parameters
        ----------
        x : torch.Tensor
            The input tensor with named dimensions.

        Returns
        -------
        torch.Tensor
            The variance computed along the specified dimension.
        """
        dim_idx = get_dim_index(x, self.dim)
        names = x.names

        result = torch.var(x.rename(None), dim=dim_idx, keepdim=self.keepdim)

        # Restore dimension names if input had named dimensions
        if names[0] is None:
            return result

        if self.keepdim:
            return result.rename(*names)

        new_names = [n for i, n in enumerate(names) if i != dim_idx]
        if new_names:
            return result.rename(*new_names)

        return result


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
    sample_data = torch.tensor([1.2, 2.5, 2.7, 2.8, 3.1])
    sample_data = sample_data.rename("time")

    # Instantiate and apply the feature
    feature_instance = MyVarianceFeature(dim="time")
    variance_value = feature_instance(sample_data)

    print(f"Variance of {sample_data.rename(None).numpy()} = {variance_value.item():.4f}")
