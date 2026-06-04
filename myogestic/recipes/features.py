"""Classic time-domain EMG features — the starter set every example used to copy-paste.

Use as-is, mix with your own, or replace entirely::

    from myogestic.recipes.features import rms, mav, wl
    from myogestic.widgets import FeatureSelector

    feats = FeatureSelector(
        {"RMS": rms, "MAV": mav, "WL": wl, "MyCustom": my_custom_fn},
        default=["RMS", "MAV"],
    )

All take an EMG window of shape ``(n_channels, n_samples)`` and return a
per-channel scalar vector ``(n_channels,)`` of dtype ``float32``.
"""

from __future__ import annotations

import numpy as np


def rms(emg: np.ndarray) -> np.ndarray:
    """Root mean square per channel."""
    return np.sqrt(np.mean(emg ** 2, axis=1)).astype(np.float32)


def mav(emg: np.ndarray) -> np.ndarray:
    """Mean absolute value per channel."""
    return np.mean(np.abs(emg), axis=1).astype(np.float32)


def wl(emg: np.ndarray) -> np.ndarray:
    """Waveform length per channel — sum of absolute first differences."""
    return np.sum(np.abs(np.diff(emg, axis=1)), axis=1).astype(np.float32)


def var(emg: np.ndarray) -> np.ndarray:
    """Variance per channel."""
    return np.var(emg, axis=1).astype(np.float32)


def zc(emg: np.ndarray) -> np.ndarray:
    """Zero-crossing count per channel."""
    sign_flips = np.diff(np.signbit(emg), axis=1)
    return np.sum(sign_flips, axis=1).astype(np.float32)


__all__ = ["mav", "rms", "var", "wl", "zc"]
