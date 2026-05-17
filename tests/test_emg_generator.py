"""Tests for the synthetic EMG generator's pure helpers.

The generator's `main()` opens an LSL outlet which is heavyweight and
flaky in sandboxed CI; we only cover the deterministic-pattern helper here.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np

from myogestic.tools.emg_generator import _class_pattern, _read_mode

# --- _class_pattern ---------------------------------------------------------


def test_class_pattern_shape_and_dtype():
    p = _class_pattern(1, 4, 32)
    assert p.shape == (32,)
    assert p.dtype == np.float32


def test_class_zero_is_all_zeros():
    """Rest = no per-channel envelope; callers add a low-noise floor."""
    p = _class_pattern(0, 4, 16)
    assert np.all(p == 0.0)


def test_different_classes_produce_different_patterns():
    n_classes, channels = 4, 32
    patterns = [_class_pattern(i, n_classes, channels) for i in range(1, n_classes)]
    for a, b in pairwise(patterns):
        assert not np.allclose(a, b), "non-rest classes should differ"


def test_pattern_peaks_at_one():
    p = _class_pattern(2, 4, 64)
    assert np.isclose(np.max(p), 1.0)


def test_pattern_is_deterministic_across_calls():
    a = _class_pattern(2, 5, 24)
    b = _class_pattern(2, 5, 24)
    assert np.array_equal(a, b)


def test_n_classes_one_is_all_zeros():
    """Edge case: caller passes nonsensical n_classes — return rest, no crash."""
    p = _class_pattern(1, 1, 8)
    assert p.shape == (8,) and np.all(p == 0.0)


# --- _read_mode -------------------------------------------------------------


class _FakeInlet:
    def __init__(self, value: float):
        self._value = value
        self._consumed = False

    def pull_chunk(self, timeout: float = 0.0):
        if self._consumed:
            return np.empty((0, 1)), []
        self._consumed = True
        return np.array([[self._value]], dtype=np.float32), [0.0]


def test_read_mode_clamps_to_class_range():
    """Generator must never push an out-of-range index into the chunk loop."""
    assert _read_mode(_FakeInlet(7.0), n_classes=4, mode_idx=0) == 3
    assert _read_mode(_FakeInlet(-2.0), n_classes=4, mode_idx=0) == 0


def test_read_mode_rounds_fractional_values():
    assert _read_mode(_FakeInlet(1.4), n_classes=4, mode_idx=0) == 1
    assert _read_mode(_FakeInlet(2.6), n_classes=4, mode_idx=0) == 3


def test_read_mode_keeps_previous_when_inlet_idle():
    inlet = _FakeInlet(2.0)
    inlet._consumed = True  # simulate empty pull
    assert _read_mode(inlet, n_classes=4, mode_idx=1) == 1


def test_read_mode_with_none_inlet_returns_previous():
    assert _read_mode(None, n_classes=4, mode_idx=2) == 2
