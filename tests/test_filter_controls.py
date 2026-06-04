"""Tests for FilterControl. The ImGui rendering needs a live context, so
we exercise only the pure state/parameter logic here."""

import numpy as np
import pytest

from myogestic.filters import GaussianFilter, IdentityFilter, OneEuroFilter
from myogestic.widgets.panels.filter_controls import FilterControl


def test_default_constructs_one_euro():
    c = FilterControl(hz=32)
    assert c.name == "one_euro"
    assert isinstance(c.filter, OneEuroFilter)
    assert c.filter.freq == 32.0


def test_explicit_default_constructs_named_filter():
    c = FilterControl(default="gaussian")
    assert isinstance(c.filter, GaussianFilter)
    c = FilterControl(default="identity")
    assert isinstance(c.filter, IdentityFilter)


def test_rejects_unknown_default():
    with pytest.raises(ValueError, match="default must be"):
        FilterControl(default="kalman")


def test_callable_delegates_to_active_filter():
    """FilterControl is itself callable — applies the active filter."""
    c = FilterControl(default="identity")
    x = np.array([1.0, 2.0, 3.0])
    assert np.array_equal(c(x), x)


def test_reset_clears_active_filter_state():
    """`.reset()` delegates to the underlying filter's reset (history cleared)."""
    c = FilterControl(default="one_euro", hz=50)
    c(np.array([1.0]))
    c(np.array([2.0]))
    # Internal state populated
    assert c.filter._x_prev is not None  # type: ignore[attr-defined]
    c.reset()
    assert c.filter._x_prev is None  # type: ignore[attr-defined]
    # First call after reset returns input verbatim
    out = c(np.array([10.0]))
    assert np.isclose(out[0], 10.0)
