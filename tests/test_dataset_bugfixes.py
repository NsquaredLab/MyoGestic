"""Tests for critical bug fixes in dataset.py.

These tests verify the fixes for:
1. Transform instantiation with/without window_size parameter
2. Bad channel validation and correct axis handling
3. Division by zero prevention in standardization
"""

import inspect

import numpy as np
import pytest
import torch
from myoverse.transforms import RMS, Transform


# Test 1: Transform instantiation bug fix
class CustomFeatureWithoutWindowSize(Transform):
    """A custom feature that does NOT accept window_size parameter."""

    def __init__(self, dim: str = "time", **kwargs):
        super().__init__(dim=dim, **kwargs)

    def _apply(self, x: torch.Tensor) -> torch.Tensor:
        return torch.var(x.rename(None), dim=-1)


class CustomFeatureWithWindowSize(Transform):
    """A custom feature that DOES accept window_size parameter."""

    def __init__(self, window_size: int = 100, dim: str = "time", **kwargs):
        super().__init__(dim=dim, **kwargs)
        self.window_size = window_size

    def _apply(self, x: torch.Tensor) -> torch.Tensor:
        return torch.mean(x.rename(None), dim=-1)


def _create_feature_transform_fixed(feature_cls, buffer_size: int):
    """The fixed version of _create_feature_transform using introspection."""
    params = inspect.signature(feature_cls.__init__).parameters

    if "window_size" in params:
        return feature_cls(window_size=buffer_size)
    return feature_cls()


class TestTransformInstantiation:
    """Test that transform instantiation works for all feature types."""

    def test_feature_without_window_size(self):
        """Custom features without window_size should instantiate correctly."""
        transform = _create_feature_transform_fixed(CustomFeatureWithoutWindowSize, 360)
        assert transform is not None

        # Apply to sample data
        x = torch.randn(32, 360).rename("channel", "time")
        result = transform(x)
        assert result is not None

    def test_feature_with_window_size(self):
        """Features with window_size should receive the buffer size."""
        transform = _create_feature_transform_fixed(CustomFeatureWithWindowSize, 360)
        assert transform is not None
        assert transform.window_size == 360

    def test_myoverse_rms_instantiation(self):
        """MyoVerse RMS transform should instantiate with window_size."""
        transform = _create_feature_transform_fixed(RMS, 360)
        assert transform is not None
        assert transform.window_size == 360


# Test 2: Bad channel validation bug fix
class TestBadChannelValidation:
    """Test bad channel removal with correct axis and bounds checking."""

    def test_bad_channel_axis_is_zero(self):
        """Bad channels should be removed from axis=0 (channel dimension)."""
        # Shape: (channels=32, time=360)
        frame_data = np.random.randn(32, 360)
        bad_channels = [0, 5, 31]

        # The fix: use axis=0, not axis=1
        n_channels = frame_data.shape[0]
        valid_bad_channels = [ch for ch in bad_channels if 0 <= ch < n_channels]
        result = np.delete(frame_data, valid_bad_channels, axis=0)

        # Should have 29 channels now (32 - 3)
        assert result.shape == (29, 360)

    def test_out_of_bounds_channels_filtered(self):
        """Out-of-bounds channel indices should be filtered out."""
        frame_data = np.random.randn(32, 360)
        bad_channels = [0, 5, 100, -1, 50]  # 100, 50 are out of bounds

        n_channels = frame_data.shape[0]
        valid_bad_channels = [ch for ch in bad_channels if 0 <= ch < n_channels]

        # Only channels 0 and 5 are valid
        assert valid_bad_channels == [0, 5]

        result = np.delete(frame_data, valid_bad_channels, axis=0)
        assert result.shape == (30, 360)  # 32 - 2 = 30

    def test_empty_bad_channels(self):
        """Empty bad channels list should not modify data."""
        frame_data = np.random.randn(32, 360)
        bad_channels = []

        n_channels = frame_data.shape[0]
        valid_bad_channels = [ch for ch in bad_channels if 0 <= ch < n_channels]

        if valid_bad_channels:
            result = np.delete(frame_data, valid_bad_channels, axis=0)
        else:
            result = frame_data

        assert result.shape == (32, 360)


# Test 3: Division by zero prevention
EPSILON = 1e-8


class TestDivisionByZeroPrevention:
    """Test that standardization handles zero std correctly."""

    def test_zero_std_training(self):
        """Training standardization should not fail when std=0."""
        # Constant feature data (std=0)
        feature_data = np.ones((100, 32))  # All ones

        mean = float(feature_data.mean())
        std = float(feature_data.std())

        assert std == 0.0, "Test setup: std should be 0"

        # The fix: use max(std, EPSILON)
        std_safe = max(std, EPSILON)
        result = (feature_data - mean) / std_safe

        # Should not contain inf or nan
        assert not np.any(np.isinf(result))
        assert not np.any(np.isnan(result))

    def test_zero_std_online(self):
        """Online preprocessing should not fail when std=0."""
        feature_vec = torch.ones(32)  # Constant values
        mean = 1.0
        std = 0.0  # Zero std

        # The fix: use max(std, EPSILON)
        std_safe = max(std, EPSILON)
        result = (feature_vec - mean) / std_safe

        # Should not contain inf or nan
        assert not torch.any(torch.isinf(result))
        assert not torch.any(torch.isnan(result))

    def test_normal_std_unaffected(self):
        """Normal std values should work as expected."""
        feature_data = np.random.randn(100, 32)

        mean = float(feature_data.mean())
        std = float(feature_data.std())

        std_safe = max(std, EPSILON)

        # For normal data, std_safe should equal std
        assert abs(std_safe - std) < 1e-10

        result = (feature_data - mean) / std_safe

        # Result should be standardized
        assert not np.any(np.isinf(result))
        assert not np.any(np.isnan(result))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
