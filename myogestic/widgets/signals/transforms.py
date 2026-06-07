"""Visual-only signal transforms used by the signal viewer and previews."""

from __future__ import annotations

import numpy as np


def apply_display_filter(data: np.ndarray, mode: str, fs: float) -> np.ndarray:
    """Apply visual-only transforms. Recording/model input is unaffected."""
    if mode == "rectify":
        return np.abs(data)
    if mode == "dc_removal":
        return data - data.mean(axis=0, keepdims=True)
    if mode != "rms_env" or len(data) < 4:
        return data

    k = max(4, int(0.01 * fs))
    if k >= len(data):
        return data
    sq = (data.astype(np.float32)) ** 2
    csum = np.cumsum(sq, axis=0)
    denom = np.arange(1, k + 1, dtype=np.float32)[:, None]
    rms_warm = np.sqrt(np.maximum(csum[:k] / denom, 0.0))
    rms_tail = np.sqrt(np.maximum((csum[k:] - csum[:-k]) / k, 0.0))
    return np.concatenate([rms_warm, rms_tail])
