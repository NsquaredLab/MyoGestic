"""Pure decoders: raw OTB frame bytes -> (n_samples, n_channels) float32.

OTB streams are channels-contiguous per sample-instant (Fortran/column-major
when shaped (n_channels, n_samples)); we transpose to sample-major to match the
MyoGestic Source contract. Muovi is big-endian; Quattrocento is little-endian
(see decode_le_int16 in Task 7).
"""
from __future__ import annotations

import numpy as np


def decode_be_int16(raw: bytes, n_channels: int) -> np.ndarray:
    """Big-endian signed int16, channels-contiguous -> (n_samples, n_channels) f32."""
    flat = np.frombuffer(raw, dtype=">i2").astype(np.float32)
    return flat.reshape(n_channels, -1, order="F").T


def decode_be_int24(raw: bytes, n_channels: int) -> np.ndarray:
    """Big-endian signed int24, channels-contiguous -> (n_samples, n_channels) f32.

    NumPy has no int24 dtype: read 3-byte groups MSB-first and sign-extend.
    """
    b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
    vals = (b[:, 0] << 16) | (b[:, 1] << 8) | b[:, 2]
    neg = vals >= 0x800000
    vals[neg] -= 0x1000000
    return vals.astype(np.float32).reshape(n_channels, -1, order="F").T


def decode_le_int16(raw: bytes, n_channels: int) -> np.ndarray:
    """Little-endian signed int16, channels-contiguous -> (n_samples, n_channels) f32."""
    flat = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    return flat.reshape(n_channels, -1, order="F").T
