"""Tests for the sparse RMS-envelope helper `compute_rms_trace`.

The live viewer draws an RMS envelope by computing one trailing-RMS value per
hop endpoint (configurable window + shift), on an absolute-time grid, over a
slice that includes pre-roll before the visible left edge. These tests pin the
properties that keep that envelope correct and scroll-stable.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from myogestic.widgets.signals.transforms import compute_rms_trace


def _uniform(n, n_ch, fs, seed=0):
    ts = np.arange(n, dtype=np.float64) / fs
    data = np.random.default_rng(seed).standard_normal((n, n_ch)).astype(np.float32)
    return ts, data


def test_endpoint_value_matches_a_manual_trailing_window():
    """Each emitted value is sqrt(mean(x**2)) over (end - window, end]."""
    fs = 2000.0
    ts, data = _uniform(4000, 3, fs)
    window_ms, hop_ms = 100.0, 25.0
    rms_ts, rms_data = compute_rms_trace(ts, data, fs, window_ms, hop_ms)
    assert len(rms_ts) > 0
    window_s = window_ms / 1000.0
    for j in (0, len(rms_ts) // 2, len(rms_ts) - 1):
        end = rms_ts[j]
        mask = (ts > end - window_s) & (ts <= end)
        ref = np.sqrt(np.mean(data[mask].astype(np.float64) ** 2, axis=0))
        assert rms_data[j] == pytest.approx(ref, rel=1e-6)


def test_endpoints_are_on_the_absolute_hop_grid_and_causal():
    """Endpoints are multiples of the hop period, each with a full window of
    history behind it (so `start >= ts[0]`), and none past the last sample."""
    fs = 1000.0
    ts, data = _uniform(5000, 2, fs)
    window_ms, hop_ms = 200.0, 50.0
    rms_ts, _ = compute_rms_trace(ts, data, fs, window_ms, hop_ms)
    hop_s = hop_ms / 1000.0
    # On the grid: every endpoint is an integer multiple of the hop period.
    assert np.allclose(rms_ts / hop_s, np.round(rms_ts / hop_s))
    # Causal + in range: full window of history, and within the data.
    assert rms_ts[0] - window_ms / 1000.0 >= ts[0] - 1e-9
    assert rms_ts[-1] <= ts[-1] + 1e-9


def test_scroll_stability_shared_endpoints_are_identical():
    """Dropping early samples (as the live window scrolls) must not change the
    RMS at endpoints whose window still lies fully inside both slices."""
    fs = 2000.0
    ts, data = _uniform(8000, 4, fs)
    window_ms, hop_ms = 150.0, 20.0
    ends_a, rms_a = compute_rms_trace(ts, data, fs, window_ms, hop_ms)
    # A later view of the same stream: the first 1500 samples have scrolled off.
    k = 1500
    ends_b, rms_b = compute_rms_trace(ts[k:], data[k:], fs, window_ms, hop_ms)

    # Endpoints present in both, compared by absolute time.
    a_index = {round(t, 9): i for i, t in enumerate(ends_a)}
    shared = [(a_index[round(t, 9)], j) for j, t in enumerate(ends_b) if round(t, 9) in a_index]
    assert len(shared) > 10  # meaningful overlap
    for ia, jb in shared:
        # Not bit-exact: the two slices' float64 prefix sums round differently,
        # but the difference is ~1e-12 (invisible). What matters is the envelope
        # does not visibly shift as it scrolls.
        np.testing.assert_allclose(rms_a[ia], rms_b[jb], rtol=1e-9, atol=1e-12)


def test_preroll_makes_the_left_edge_a_full_window():
    """With pre-roll before the visible edge, the first visible endpoint uses a
    full window; the same endpoint has no output when the slice starts at it."""
    fs = 2000.0
    ts, data = _uniform(6000, 1, fs)
    window_ms, hop_ms = 100.0, 20.0
    window_s = window_ms / 1000.0

    # "visible" window is the second half; pre-roll = one RMS window before it.
    vis_start = ts[3000]
    preroll_mask = ts >= vis_start - window_s
    ends_pr, rms_pr = compute_rms_trace(ts[preroll_mask], data[preroll_mask], fs, window_ms, hop_ms)
    # The first endpoint at/after vis_start is a full, correct window...
    first_vis = ends_pr[ends_pr >= vis_start][0]
    fv_i = int(np.where(ends_pr == first_vis)[0][0])
    ref = np.sqrt(np.mean(data[(ts > first_vis - window_s) & (ts <= first_vis)] ** 2, axis=0))
    assert rms_pr[fv_i] == pytest.approx(ref, rel=1e-6)

    # ...but if the slice starts exactly at the visible edge (no pre-roll), that
    # endpoint lacks a full window and is simply not emitted (not a partial).
    vis_mask = ts >= vis_start
    ends_no, _ = compute_rms_trace(ts[vis_mask], data[vis_mask], fs, window_ms, hop_ms)
    assert not np.any(np.isclose(ends_no, first_vis))


def test_short_buffer_yields_no_partial_windows():
    """Fewer samples than one window -> empty, never a partial-window value."""
    fs = 1000.0
    ts, data = _uniform(50, 4, fs)  # 50 ms of data
    rms_ts, rms_data = compute_rms_trace(ts, data, fs, window_ms=200.0, hop_ms=50.0)
    assert rms_ts.shape == (0,)
    assert rms_data.shape == (0, 4)


def test_nan_only_poisons_its_own_window_then_recovers():
    """A dropout NaN marks the windows spanning it NaN, and clean windows before
    and after stay finite (the cumulative sum is not poisoned)."""
    fs = 1000.0
    ts, data = _uniform(4000, 2, fs)
    window_ms, hop_ms = 100.0, 50.0
    window_s = window_ms / 1000.0
    bad_t = ts[2000]
    data[2000, 0] = np.nan  # single dropout in channel 0

    rms_ts, rms_data = compute_rms_trace(ts, data, fs, window_ms, hop_ms)
    spans_bad = (rms_ts >= bad_t) & (rms_ts - window_s < bad_t)
    assert np.all(np.isnan(rms_data[spans_bad, 0]))          # windows over the dropout
    assert np.all(np.isfinite(rms_data[~spans_bad, 0]))      # everything else recovers
    assert np.all(np.isfinite(rms_data[:, 1]))               # clean channel untouched


def test_float64_accumulation_is_accurate_on_a_dc_offset_signal():
    """A big DC offset over a long window is where a float32 cumulative sum
    loses precision; the float64 accumulation must stay accurate."""
    fs = 2000.0
    n = 120_000
    ts = np.arange(n, dtype=np.float64) / fs
    rng = np.random.default_rng(1)
    data = (1000.0 + 0.5 * rng.standard_normal((n, 1))).astype(np.float32)
    # One long window ending at the last sample.
    window_ms = 5000.0
    rms_ts, rms_data = compute_rms_trace(ts, data, fs, window_ms, hop_ms=window_ms)
    assert len(rms_ts) >= 1
    end = rms_ts[-1]
    mask = (ts > end - window_ms / 1000.0) & (ts <= end)
    ref = np.sqrt(np.mean(data[mask].astype(np.float64) ** 2))
    assert rms_data[-1, 0] == pytest.approx(ref, rel=1e-6)


def test_zero_hop_degenerates_to_per_sample_and_stays_bounded():
    """hop_ms <= 0 means a one-sample hop (smooth per-sample envelope); output
    is one point per sample within the valid region, not an error."""
    fs = 1000.0
    ts, data = _uniform(2000, 1, fs)
    rms_ts, rms_data = compute_rms_trace(ts, data, fs, window_ms=100.0, hop_ms=0.0)
    # ~ one point per sample after the first full window (1900 give or take).
    assert 1800 <= len(rms_ts) <= 2000
    assert rms_data.shape == (len(rms_ts), 1)


def test_empty_input_returns_empty_without_raising():
    """A size-0 input (e.g. a bare 1-D empty array from a direct caller) must
    return the correct-shape empty result, not raise on the internal reshape."""
    rms_ts, rms_data = compute_rms_trace(np.empty(0), np.empty(0), 1000.0, 100.0, 20.0)
    assert rms_ts.shape == (0,)
    assert rms_data.ndim == 2 and rms_data.shape[0] == 0


def test_perf_reasonable_for_many_channels():
    """256 ch over a 5 s + pre-roll window at 2 kHz stays well under a frame."""
    fs = 2000.0
    ts, data = _uniform(int(5.2 * fs), 256, fs)
    compute_rms_trace(ts, data, fs, 150.0, 20.0)  # warm
    t0 = time.perf_counter()
    for _ in range(10):
        compute_rms_trace(ts, data, fs, 150.0, 20.0)
    ms = (time.perf_counter() - t0) / 10 * 1000
    print(f"compute_rms_trace 256ch/5.2s@2kHz: {ms:.2f} ms")
    # 256 simultaneous envelopes is an extreme; the realistic 16-channel case
    # is ~16x cheaper. This only guards against a *gross* regression (a real
    # one would be seconds), so the bound is deliberately generous: ~24 ms
    # locally but ~45 ms on shared CI runners, which flaked a tighter 45 ms
    # bound. 250 ms keeps comfortable headroom without hiding a real blow-up.
    assert ms < 250.0
