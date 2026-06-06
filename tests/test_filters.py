"""Tests for myogestic.outputs.filters output-smoothing layer."""

import numpy as np
import pytest

from myogestic.outputs.filters import (
    GaussianFilter,
    IdentityFilter,
    OneEuroFilter,
    make_filter,
)


def test_identity_passthrough():
    f = IdentityFilter()
    x = np.array([1.0, 2.0, 3.0])
    assert np.array_equal(f(x), x)
    f.reset()


def test_gaussian_first_call_returns_input():
    """Single sample → weighted mean of 1 sample = the sample itself."""
    f = GaussianFilter(n_vectors=5, sigma=1.0)
    x = np.array([1.0, 2.0, 3.0])
    out = f(x)
    assert np.allclose(out, x)


def test_gaussian_smooths_step_input():
    """Step from 0→10 should be smoothed (output starts below 10 and rises)."""
    f = GaussianFilter(n_vectors=5, sigma=1.0)
    # Prime with zeros, then jump to 10.
    for _ in range(5):
        f(np.zeros(2))
    out = f(np.full(2, 10.0))
    assert (out > 0).all() and (out < 10).all()


def test_gaussian_rejects_bad_args():
    with pytest.raises(ValueError, match="n_vectors"):
        GaussianFilter(n_vectors=0)
    with pytest.raises(ValueError, match="sigma"):
        GaussianFilter(sigma=0)


def test_one_euro_first_call_returns_input():
    f = OneEuroFilter(hz=50)
    x = np.array([1.0, 2.0, 3.0])
    out = f(x)
    assert np.allclose(out, x)


def test_one_euro_converges_on_constant_signal():
    """If we feed the same value forever, output → that value."""
    f = OneEuroFilter(hz=50, min_cutoff_hz=1.0)
    x = np.array([5.0, -3.0])
    last = f(x)
    for _ in range(200):
        last = f(x)
    assert np.allclose(last, x, atol=1e-3)


def test_one_euro_reset_clears_state():
    f = OneEuroFilter(hz=50)
    f(np.array([1.0]))
    f(np.array([2.0]))
    f.reset()
    # After reset, first call returns input verbatim again.
    out = f(np.array([10.0]))
    assert np.isclose(out[0], 10.0)


def test_one_euro_rejects_bad_args():
    with pytest.raises(ValueError, match="hz"):
        OneEuroFilter(hz=0)
    with pytest.raises(ValueError, match="min_cutoff_hz"):
        OneEuroFilter(min_cutoff_hz=0)
    with pytest.raises(ValueError, match="derivative_cutoff_hz"):
        OneEuroFilter(derivative_cutoff_hz=0)


def test_make_filter_dispatches():
    assert isinstance(make_filter("identity"), IdentityFilter)
    assert isinstance(make_filter("gaussian"), GaussianFilter)
    assert isinstance(make_filter("one_euro", hz=32), OneEuroFilter)
    # Case-insensitive
    assert isinstance(make_filter("IDENTITY"), IdentityFilter)


def test_make_filter_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown filter"):
        make_filter("kalman")


def test_one_euro_with_explicit_timestamps():
    """Passing real timestamps gives different smoothing than the hz fallback
    when calls aren't perfectly periodic."""
    f1 = OneEuroFilter(hz=50)  # uses 0.02s default dt
    f2 = OneEuroFilter(hz=50)  # will use real dt via t arg

    # Feed identical first samples
    f1(np.array([0.0]))
    f2(np.array([0.0]), timestamp=0.0)

    # Then a step at "real" 0.1s (dt=0.1) — much slower than hz fallback (0.02)
    out_fallback = f1(np.array([10.0]))
    out_explicit = f2(np.array([10.0]), timestamp=0.1)

    # Explicit longer-dt call → less smoothing (closer to input) since alpha grows with dt
    assert out_explicit[0] > out_fallback[0]


def test_filter_preserves_input_dtype():
    """Output dtype matches input dtype (float32 in → float32 out, etc.)."""
    f = OneEuroFilter(hz=50)
    x32 = np.array([1.0, 2.0], dtype=np.float32)
    assert f(x32).dtype == np.float32
    f.reset()
    x64 = np.array([1.0, 2.0], dtype=np.float64)
    assert f(x64).dtype == np.float64

    g = GaussianFilter(n_vectors=3)
    assert g(np.array([1.0, 2.0], dtype=np.float32)).dtype == np.float32


def test_make_filter_one_euro_propagates_hz():
    f = make_filter("one_euro", hz=32)
    assert isinstance(f, OneEuroFilter)
    assert f.hz == 32.0


def test_make_filter_kwargs_tune_filter():
    """Extra kwargs are forwarded to the underlying filter constructor."""
    g = make_filter("gaussian", n_vectors=10, sigma=2.0)
    assert isinstance(g, GaussianFilter)
    assert g.n_vectors == 10
    assert g.sigma == 2.0

    o = make_filter("one_euro", hz=32, beta=0.05)
    assert isinstance(o, OneEuroFilter)
    assert o.beta == 0.05
    assert o.hz == 32.0


def test_make_filter_rejects_unknown_kwargs():
    with pytest.raises(TypeError):
        make_filter("identity", n_vectors=5)


def test_gaussian_rejects_non_1d_input():
    f = GaussianFilter(n_vectors=3)
    with pytest.raises(ValueError, match="1-D"):
        f(np.zeros((3, 4)))
