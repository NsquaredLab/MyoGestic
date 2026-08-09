"""Perf regression: the signal viewer must never pay full-window decimation
cost for a stream at high channel counts.

Two fixes are covered here, at the two layers they now live in:

- `build_signal_frame` (`_state.py`) slices the visible window to the
  *enabled* columns only, before anything else touches it — a 256-channel
  stream showing 3 channels only ever carries 3 columns downstream, not
  256. It does not decimate at all (see below).
- Decimation itself lives in `_state.minmax_grid_all_shared_x`, called once
  per frame from `_plot.render_plot`, over every enabled column at once
  (vectorized, no per-channel Python loop). Each channel keeps its own
  min/max envelope over a *shared* x-axis — there is no cross-channel index
  union, so total draw points stay bounded at `n_channels * n_out` instead
  of approaching the full window (the failure mode of an earlier
  shared-union design: 64 channels over a 5 s / 2048 Hz window unioned to
  the *entire* window, zero point reduction). Processing every channel
  together in one NumPy call (rather than one Python-level call per
  channel) is what gets this from ~15.7 ms/64ch down to ~0.9 ms/64ch.

Uses an in-process synthetic `Source` (no LSL), matching the pattern in
`tests/test_recording_race.py` / `tests/test_stream_dtype.py`. The
decimation-*target-sizing* and the vectorized decimator are pure functions
(`resolve_decimation_target`, `minmax_grid_all_shared_x`) and are exercised
directly here — the actual plot loop that calls them (`_plot.render_plot` /
`plot_channel`) needs a live ImPlot context and isn't covered by this
headless suite.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from myogestic.stream import Stream, StreamInfo
from myogestic.widgets.signals._state import (
    _DECIMATE_FALLBACK_POINTS,
    _DECIMATE_MIN_POINTS,
    ViewerState,
    build_signal_frame,
    minmax_grid_all_shared_x,
    resolve_decimation_target,
    resolve_enabled,
)


class _SynthSource:
    """Source protocol stub: deterministic multi-channel ramp, many small chunks."""

    def __init__(self, n_channels: int = 64, fs: float = 1000.0, chunk: int = 50) -> None:
        self._info = StreamInfo(n_channels=n_channels, fs=fs, dtype=np.dtype("float32"))
        self._chunk = chunk
        self._next_t = 0.0

    def connect(self) -> StreamInfo:
        return self._info

    def read(self):
        n = self._chunk
        # Per-channel offset so columns are distinguishable if ever inspected.
        base = np.arange(n, dtype=np.float32)[:, None]
        cols = np.arange(self._info.n_channels, dtype=np.float32)[None, :]
        data = base + cols
        ts = self._next_t + np.arange(n, dtype=np.float64) / self._info.fs
        self._next_t = ts[-1] + 1.0 / self._info.fs
        return data, ts

    def disconnect(self) -> None:
        pass


def _make_stream(
    n_channels: int = 64,
    n_steps: int = 20,
    fs: float = 1000.0,
    chunk: int = 50,
    buffer_ms: float = 5000,
) -> Stream:
    stream = Stream(
        "emg",
        source=_SynthSource(n_channels=n_channels, fs=fs, chunk=chunk),
        window_ms=100,
        buffer_ms=buffer_ms,
    )
    stream.reconnect()  # attaching is deliberate now; the loop never does it
    for _ in range(n_steps):
        stream._acquire_step()
    return stream


def _viewer_state(n_pixels: int = 2) -> ViewerState:
    # `n_pixels` no longer affects `build_signal_frame` at all (it never
    # decimates there) — it's only consulted later, by
    # `resolve_decimation_target`, when the plot loop sizes the shared
    # decimation target. Kept as a parameter here for the tests below that
    # exercise that function directly.
    return ViewerState(n_pixels=n_pixels, window=1000.0)


def test_frame_has_exactly_the_enabled_columns():
    stream = _make_stream(n_channels=64)
    v = _viewer_state()
    enabled = {0, 5, 10}

    frame = build_signal_frame(stream, v, enabled)

    assert frame is not None
    assert frame.data.shape[1] == 3
    # Mapping from `data` column -> true channel index, so callers can
    # still color/label traces by their real channel without renumbering.
    assert frame.channel_map == sorted(enabled)
    # The *total* channel count on the frame must still reflect the full
    # stream (used to size specs/labels), not the enabled subset.
    assert frame.n_channels == 64


def test_empty_enabled_set_yields_an_empty_frame():
    stream = _make_stream(n_channels=64)
    v = _viewer_state()

    frame = build_signal_frame(stream, v, set())

    assert frame is not None
    assert frame.data.shape[1] == 0
    assert frame.channel_map == []


def test_build_signal_frame_no_longer_decimates_regardless_of_channel_count():
    """`build_signal_frame`'s row count is now always the raw visible
    window's length — it stopped decimating, so it must be identical
    whether 3 columns or every column is enabled. The actual reduction now
    happens later; see
    `test_minmax_grid_all_shared_x_bounds_total_draw_points_by_channel_count`."""
    stream = _make_stream(n_channels=64)

    v_subset = _viewer_state()
    frame_subset = build_signal_frame(stream, v_subset, {0, 5, 10})

    v_all = _viewer_state()
    frame_all = build_signal_frame(stream, v_all, set(range(64)))

    assert frame_subset is not None
    assert frame_all is not None
    assert frame_subset.n_points == frame_all.n_points
    assert frame_subset.n_points == len(frame_subset.ts_win)


def test_small_stream_all_enabled_matches_full_width_shape():
    """Common-case regression: when every channel is enabled, the frame's
    width still equals the full channel count (no behavior change)."""
    stream = _make_stream(n_channels=4, n_steps=5)
    v = _viewer_state(n_pixels=2)
    enabled = {0, 1, 2, 3}

    frame = build_signal_frame(stream, v, enabled)

    assert frame is not None
    assert frame.data.shape[1] == 4
    assert frame.channel_map == [0, 1, 2, 3]


def test_frame_slices_to_enabled_columns_for_any_viewer_config():
    """Column-slicing to `enabled` must hold regardless of `ViewerState`
    config (e.g. a large `n_pixels`, which used to select a no-decimation
    path here but no longer has any effect on `build_signal_frame`)."""
    stream = _make_stream(n_channels=8, n_steps=1)
    v = ViewerState(n_pixels=10_000, window=1000.0)
    enabled = {1, 3}

    frame = build_signal_frame(stream, v, enabled)

    assert frame is not None
    assert frame.data.shape[1] == 2
    assert frame.channel_map == [1, 3]
    np.testing.assert_array_equal(frame.data, frame.data_win[:, [1, 3]])


def test_rms_env_frame_is_a_sparse_positive_envelope_within_the_window():
    """In rms_env mode `build_signal_frame` hands the plot a sparse RMS
    envelope: far fewer points than the raw window, all inside it, all
    non-negative, on its own hop time base (distinct from the visible-sample
    timestamps), with `x_origin` anchored to the visible left edge."""
    fs = 1000.0
    stream = _make_stream(n_channels=8, n_steps=30, fs=fs, chunk=50)
    v = ViewerState(window=0.5, display_filter="rms_env", rms_window_ms=100.0, rms_hop_ms=20.0)
    enabled = {0, 3, 7}

    frame = build_signal_frame(stream, v, enabled)
    assert frame is not None
    # Sparse: ~ window/hop points, far fewer than the ~500 raw samples.
    assert 0 < len(frame.trace_ts) < len(frame.ts_win)
    assert frame.data.shape == (len(frame.trace_ts), 3)
    # Its own time base, not the visible-sample timestamps.
    assert frame.trace_ts is not frame.ts_win
    # Every envelope point sits inside the visible window...
    vis_start = float(frame.ts_win[0])
    last_ts = float(frame.ts_win[-1])
    assert np.all(frame.trace_ts >= vis_start - 1e-9)
    assert np.all(frame.trace_ts <= last_ts + 1e-9)
    # ...and RMS is non-negative.
    assert np.all(frame.data[np.isfinite(frame.data)] >= 0.0)
    # x_origin anchors plot-x 0 to the visible window's left edge.
    assert frame.x_origin == pytest.approx(vis_start)
    # data_win stays the RAW full-width visible window (footer stats over raw).
    assert frame.data_win.shape[1] == 8


def test_non_rms_frame_trace_ts_equals_the_visible_window():
    """Regression: without rms_env, the plot's trace time base is exactly the
    visible-window timestamps and `x_origin` is their start (no drift)."""
    stream = _make_stream(n_channels=4, n_steps=10, fs=1000.0)
    v = ViewerState(window=0.2, display_filter="none")
    frame = build_signal_frame(stream, v, {0, 1, 2, 3})
    assert frame is not None
    np.testing.assert_array_equal(frame.trace_ts, frame.ts_win)
    assert frame.x_origin == pytest.approx(float(frame.ts_win[0]))


def test_minmax_grid_all_shared_x_bounds_total_draw_points_by_channel_count():
    """The actual perf fix, reproducing the reported scenario: 64 channels
    over a 5 s / 2048 Hz window.

    A naive per-channel *union* of M4 indices onto one shared x-axis would
    approach the full `(10240, 64)` window (~655k points) — no reduction at
    all. `minmax_grid_all_shared_x` instead keeps each channel's own
    min/max envelope over a shared bucket grid, bounding total draw points
    at `n_channels * N`, not `window * n_channels`.
    """
    fs = 2048.0
    n_channels = 64
    window_s = 5.0
    chunk = 1024
    n_steps = int(window_s * fs / chunk) + 3  # a bit more than one window's worth

    stream = _make_stream(
        n_channels=n_channels, n_steps=n_steps, fs=fs, chunk=chunk, buffer_ms=8000
    )
    v = ViewerState(n_pixels=2000, window=window_s)
    enabled = set(range(n_channels))

    frame = build_signal_frame(stream, v, enabled)
    assert frame is not None

    raw_len = len(frame.ts_win)
    # The fixture must have actually filled (close to) a full 5 s window,
    # otherwise this test would trivially pass without ever exercising
    # decimation.
    window_samples = int(window_s * fs)
    assert raw_len >= window_samples * 0.9

    # A plausible plot pixel width; the explicit n_pixels=2000 cap binds
    # here (800 * 3.0 detail = 2400, clamped to 2000; matches the reported
    # 64 ch -> 128k-point example: 64 * 2000).
    n_out = resolve_decimation_target(plot_width_px=800.0, v=v)
    assert n_out == 2000

    xs, ys = minmax_grid_all_shared_x(frame.ts_win, frame.data, n_out, v.window)

    assert ys.shape[0] == len(frame.channel_map) == n_channels
    assert ys.shape[1] == len(xs)
    # ~n_out (2 pts/bucket) plus up to 2 for the preserved global first/last
    # endpoints, plus up to 2 more since the absolute-time grid's phase
    # generally doesn't line up with this window's own start/end -- an
    # interval spanning exactly `n_buckets * bucket_dt` seconds can still
    # touch one extra partial bucket at the edge (`n_buckets + 1` occupied
    # buckets), regardless of channel count. Bounded *per channel row*,
    # independent of how many channels are enabled.
    assert xs.shape[0] <= n_out + 4

    total_drawn = ys.shape[0] * ys.shape[1]
    # Bounded by channels * N (the fix)...
    assert total_drawn <= n_channels * (n_out + 4)
    # ...and dramatically less than the old union's worst case, which
    # approached the entire (raw_len, n_channels) window.
    old_union_worst_case = raw_len * n_channels
    assert total_drawn < old_union_worst_case * 0.2


def test_minmax_grid_all_shared_x_below_threshold_is_a_passthrough():
    t = np.arange(10, dtype=np.float64)
    data = np.stack([np.arange(10, dtype=np.float32), np.arange(10, dtype=np.float32) + 1], axis=1)

    xs, ys = minmax_grid_all_shared_x(t, data, n_out=100, window_s=10.0)

    np.testing.assert_array_equal(xs, t - t[0])
    np.testing.assert_array_equal(ys, data.T)


def test_minmax_grid_all_shared_x_paired_output_bounded_by_n_out():
    # `t` must be sized to actually span `window_s` -- the grid-aligned
    # bucketing derives its fixed bucket width from `window_s`, not from
    # `t`'s own span, so a `t` that doesn't match `window_s` would place
    # almost every sample in its own bucket and defeat the point of this
    # test (see `test_minmax_grid_all_shared_x_is_stable_as_the_window_scrolls`
    # for why the width must come from `window_s`, not `t`).
    fs = 1000.0
    n = 5000
    n_channels = 3
    rng = np.random.default_rng(0)
    t = np.arange(n, dtype=np.float64) / fs
    data = rng.standard_normal((n, n_channels)).astype(np.float32)
    window_s = n / fs

    xs, ys = minmax_grid_all_shared_x(t, data, n_out=200, window_s=window_s)

    assert ys.shape == (n_channels, len(xs))
    # ~n_out (2 points/bucket) plus up to 4 slack: 2 for the preserved
    # global first/last endpoints, 2 more for a possible extra partial
    # bucket at the edge from absolute-grid/window phase misalignment (see
    # `test_minmax_grid_all_shared_x_bounds_total_draw_points_by_channel_count`).
    assert len(xs) <= 200 + 4
    # Decimation must have actually reduced the point count.
    assert len(xs) < n


def test_minmax_grid_all_shared_x_is_stable_as_the_window_scrolls():
    """Regression for the left-edge scrolling flicker.

    Decimation buckets must be anchored to *absolute* time, not to the
    window's own start. Here two overlapping windows of the same
    underlying signal are decimated with the same `window_s`/`n_out` — one
    a `k`-sample scroll ahead of the other, exactly like consecutive
    frames while the live plot scrolls. For any bucket whose full absolute
    time span lies inside the two windows' overlap (trimmed by a few
    bucket widths so we never compare a bucket that straddles either
    window's own edge -- those legitimately differ, e.g. via the
    forced-endpoint samples), its member samples are identical in both
    calls, so a correctly (absolute-time) anchored implementation must
    pick the *exact same* bucket-center x and min/max-derived y for that
    interior span in both decimations.

    Against a window-relative bucketing, "bucket i" instead covers
    *relative* index range `[edges[i], edges[i+1])`, which maps to a
    *different* absolute sample range in each window (shifted by `k`) — so
    the chosen envelope for the interior span would differ, and this test
    would fail against it (for `k` not a multiple of that implementation's
    bin width, which is what makes `k = 37` below a deliberate choice).
    """
    fs = 1000.0
    n_total = 20_000
    rng = np.random.default_rng(0)
    t_full = np.arange(n_total, dtype=np.float64) / fs
    sig_full = rng.standard_normal(n_total).astype(np.float32)
    data_full = sig_full[:, None]  # single channel, as a (n, 1) column

    window_s = 2.0
    n_out = 200
    a = 5000
    b = a + int(window_s * fs)
    k = 37  # a deliberately non-round scroll amount

    xs0, ys0 = minmax_grid_all_shared_x(t_full[a:b], data_full[a:b], n_out, window_s)
    xs1, ys1 = minmax_grid_all_shared_x(
        t_full[a + k : b + k], data_full[a + k : b + k], n_out, window_s
    )

    assert ys0.shape[1] == len(xs0)
    assert ys1.shape[1] == len(xs1)

    # `xs` is relative to each call's own window start -- put both back on
    # the shared absolute-time axis before comparing.
    abs0 = xs0 + t_full[a]
    abs1 = xs1 + t_full[a + k]

    # The overlap of the two windows, in absolute time, trimmed by a
    # several-bucket-wide margin at each end so only fully-interior
    # buckets (present, whole, in *both* windows) are compared.
    n_buckets = max(1, n_out // 2)
    bucket_dt = window_s / n_buckets
    margin = 3 * bucket_dt
    lo = t_full[a + k] + margin
    hi = t_full[b - 1] - margin
    assert lo < hi  # sanity: the trimmed interior must be non-empty

    def _points_in_interior(abs_t: np.ndarray, y_row: np.ndarray) -> dict[float, float]:
        mask = (abs_t >= lo) & (abs_t <= hi)
        return dict(zip(abs_t[mask].tolist(), y_row[mask].tolist(), strict=True))

    pts0 = _points_in_interior(abs0, ys0[0])
    pts1 = _points_in_interior(abs1, ys1[0])

    # A meaningful number of interior points must exist, otherwise the
    # dict-equality assertion below would pass vacuously.
    assert len(pts0) > n_out // 4
    assert pts0 == pts1


def test_minmax_grid_all_shared_x_renders_plausible_envelope_for_a_complex_10khz_signal():
    """Plausibility check against a realistic signal, not just noise/ramps.

    The other tests here use plain random noise or a linear ramp, which
    don't stress the same thing a real EMG-like trace would: several
    frequency components at once (including near Nyquist), a slow drift,
    broadband noise, and sharp single-sample transients. This builds such a
    signal at 10 kHz and checks that what actually gets handed to the
    plotter is still faithful to it -- the whole point of MinMax
    decimation over naive subsampling (which could silently skip a
    transient) or averaging (which would smear one out):

    - Each channel's global min/max survives decimation exactly (MinMax's
      core guarantee: every bucket's low/high are real samples drawn from
      that bucket, and the signal's true global extremum necessarily falls
      inside *some* bucket).
    - The envelope never overshoots the raw data's own range -- low/high
      are real samples, never interpolated/invented values.
    - A single-sample spike narrower than one decimation bucket, planted
      well inside the window (not at the forced first/last endpoints),
      is not silently averaged away.
    - The point count is still reduced by roughly two orders of magnitude,
      same as the synthetic-fixture tests above.
    """
    fs = 10_000.0
    duration_s = 2.0
    n = int(duration_s * fs)
    n_channels = 8
    n_out = 2000
    rng = np.random.default_rng(42)
    t = np.arange(n, dtype=np.float64) / fs

    # A handful of components spanning the visible band up to near Nyquist
    # (5 kHz), plus slow drift and broadband noise -- deliberately not just
    # one clean tone.
    freqs = (5.0, 50.0, 250.0, 1200.0, 4000.0)
    data = np.zeros((n, n_channels), dtype=np.float64)
    for ch in range(n_channels):
        sig = 0.3 * np.sin(2 * np.pi * 0.2 * t)  # slow drift
        for f in freqs:
            amp = rng.uniform(0.3, 1.0)
            phase = rng.uniform(0, 2 * np.pi)
            sig = sig + amp * np.sin(2 * np.pi * f * t + phase)
        sig = sig + 0.05 * rng.standard_normal(n)  # broadband noise
        data[:, ch] = sig

    # One single-sample outlier spike per channel, well inside the window
    # and far larger than anything the sinusoid mixture can produce, so it
    # is unambiguously that channel's true global extremum. Alternates
    # sign across channels so both the max- and min-side get covered.
    spike_val = 50.0
    spike_indices = rng.integers(int(0.1 * n), int(0.9 * n), size=n_channels)
    spike_is_max = [ch % 2 == 0 for ch in range(n_channels)]
    for ch, idx in enumerate(spike_indices):
        data[idx, ch] = spike_val if spike_is_max[ch] else -spike_val

    data = data.astype(np.float32)

    xs, ys = minmax_grid_all_shared_x(t, data, n_out, duration_s)

    # Reduction actually happened, by roughly two orders of magnitude.
    assert ys.shape[1] < n
    assert ys.shape[1] <= n_out + 4

    for ch in range(n_channels):
        raw_col = data[:, ch]
        raw_max, raw_min = float(raw_col.max()), float(raw_col.min())

        # Global extrema exactly preserved...
        assert float(ys[ch].max()) == pytest.approx(raw_max)
        assert float(ys[ch].min()) == pytest.approx(raw_min)
        # ...and the envelope never invents values outside the real range.
        assert ys[ch].max() <= raw_max + 1e-4
        assert ys[ch].min() >= raw_min - 1e-4

        # The planted spike is that channel's true extremum, so it having
        # survived decimation is exactly what the global-extrema check
        # above already proves -- pin it down explicitly here too.
        if spike_is_max[ch]:
            assert raw_max == pytest.approx(spike_val)
        else:
            assert raw_min == pytest.approx(-spike_val)


def test_minmax_grid_all_shared_x_keeps_extrema_of_a_degenerate_flat_timestamp_run():
    """A flat-timestamp run must not lose its envelope to the width cap.

    A device clock stall or a monotonic-clamped session drops many samples
    onto one timestamp, so they all land in a single bucket. The reduction
    caps the padded run width (`width`) so one pathological run can't force
    every bucket to that width and blow the `(n_buckets, width, n_channels)`
    allocation up to gigabytes -- but the cap must not silently drop that
    bucket's tail. Here the spike sits at the *end* of a 6000-sample flat
    run planted mid-window (far past the cap, and not the forced global
    last endpoint), so it survives only because runs longer than the cap get
    an exact recompute over their full extent.
    """
    fs = 10_000.0
    window_s = 2.0
    n_channels = 4
    n_out = 2000  # ~1000-bucket grid, so an uncapped `width` would multiply hugely

    # Rising timestamps, then a long flat plateau (the stall), then rising
    # again -- so the flat run is a genuine interior bucket, not the endpoint.
    n1 = int(0.5 * fs)
    t1 = np.arange(n1, dtype=np.float64) / fs
    flat_len = 6000
    t_flat = np.full(flat_len, t1[-1], dtype=np.float64)
    n2 = int(0.5 * fs)
    t2 = t1[-1] + np.arange(1, n2 + 1, dtype=np.float64) / fs
    t = np.concatenate([t1, t_flat, t2])
    n = t.size

    rng = np.random.default_rng(7)
    data = (0.1 * rng.standard_normal((n, n_channels))).astype(np.float32)
    # Plant each channel's true global max on the LAST sample of the flat run
    # -- its tail, which the width cap ignores unless the run is recomputed.
    spike = 99.0
    spike_idx = n1 + flat_len - 1
    assert spike_idx != n - 1  # not the forced global endpoint
    data[spike_idx, :] = spike

    xs, ys = minmax_grid_all_shared_x(t, data, n_out, window_s)

    for ch in range(n_channels):
        assert float(ys[ch].max()) == pytest.approx(spike)
    # The flat run collapses into its bucket; it does not expand the output.
    assert ys.shape[1] <= n_out + 4


def test_channel_diagnostics_matches_a_per_channel_loop():
    """The vectorized footer stats must equal a naive per-channel computation.

    `channel_diagnostics` is the throttled stats readout's math, extracted so
    it can be checked headlessly. It reduces only the requested (real-index)
    columns, in that order, and must reproduce rms/pp/mean exactly, including
    NaN propagation and the empty-window case.
    """
    from myogestic.widgets.signals._plot import channel_diagnostics

    rng = np.random.default_rng(3)
    data_win = rng.standard_normal((512, 8)).astype(np.float32)
    data_win[10, 5] = np.nan  # a NaN must propagate into channel 5's stats

    valid = [1, 5, 7]  # a subset, non-contiguous, in ascending order
    rms_all, pp_all, mean_all = channel_diagnostics(data_win, valid)
    assert rms_all.shape == pp_all.shape == mean_all.shape == (len(valid),)

    for i, ch in enumerate(valid):
        col = data_win[:, ch].astype(np.float64)
        exp_rms = np.sqrt(np.mean(col * col))
        exp_pp = col.max() - col.min()
        exp_mean = col.mean()
        if ch == 5:  # NaN column -> every stat is NaN
            assert np.isnan(rms_all[i]) and np.isnan(pp_all[i]) and np.isnan(mean_all[i])
            continue
        assert rms_all[i] == pytest.approx(exp_rms, rel=1e-5)
        assert pp_all[i] == pytest.approx(exp_pp, rel=1e-5)
        assert mean_all[i] == pytest.approx(exp_mean, rel=1e-5)

    # Empty window: zero-length reductions must not raise, return zeros.
    rms0, pp0, mean0 = channel_diagnostics(np.empty((0, 8), dtype=np.float32), valid)
    assert rms0.shape == (len(valid),)
    assert not np.any(rms0) and not np.any(pp0) and not np.any(mean0)


def test_stats_need_recompute_throttles_to_the_refresh_interval():
    """The footer stats recompute on first sight, on a channel-set change, and
    once per `_STATS_REFRESH_S` — otherwise the cached values stand.

    This is what keeps a wide/high-rate window from re-scanning the raw window
    on every frame: at 60 fps only ~10 frames/s recompute.
    """
    from myogestic.widgets.signals._plot import (
        _STATS_REFRESH_S,
        channel_diagnostics,
        stats_need_recompute,
    )

    data_win = np.random.default_rng(0).standard_normal((4096, 8)).astype(np.float32)
    valid = [0, 1, 2, 3]

    # No cache yet -> must recompute.
    assert stats_need_recompute(None, valid, now=0.0, last_t=0.0) is True

    # Build a cache "computed" at t=0 and step 60 fps frames across 1 s; count
    # how many frames the real predicate says to recompute.
    cache = (valid, *channel_diagnostics(data_win, valid))
    last_t = 0.0
    recomputes = 0
    for i in range(1, 61):
        now = i / 60.0
        if stats_need_recompute(cache, valid, now, last_t):
            recomputes += 1
            last_t = now
    assert recomputes <= 12, recomputes  # ~10 Hz, not 60 Hz

    # Within the interval, the same set does NOT recompute...
    assert stats_need_recompute(cache, valid, now=_STATS_REFRESH_S / 2, last_t=0.0) is False
    # ...but a changed enabled set forces an immediate recompute.
    assert stats_need_recompute(cache, [0, 1, 2], now=_STATS_REFRESH_S / 2, last_t=0.0) is True


def test_minmax_grid_all_shared_x_perf_well_under_10ms_for_64ch_5s_2048hz():
    """Non-flaky, loose perf micro-check: this is the call that replaced a
    ~15.7 ms/64ch per-channel Python loop with a ~0.9 ms/64ch vectorized
    pass. Assert an order of magnitude below the old per-channel cost
    rather than pinning to the exact expected value, so this doesn't flake
    on slower/shared CI hardware."""
    fs = 2048.0
    n_channels = 64
    window_s = 5.0
    n = int(window_s * fs)  # ~10240
    rng = np.random.default_rng(0)
    t = np.arange(n, dtype=np.float64) / fs
    data = rng.standard_normal((n, n_channels)).astype(np.float32)
    n_out = 2000

    # Warm-up call (first call may pay one-off allocator/cache costs).
    minmax_grid_all_shared_x(t, data, n_out, window_s)

    n_reps = 20
    start = time.perf_counter()
    for _ in range(n_reps):
        minmax_grid_all_shared_x(t, data, n_out, window_s)
    elapsed_ms = (time.perf_counter() - start) / n_reps * 1000

    print(f"minmax_grid_all_shared_x: {elapsed_ms:.3f} ms/call (64 ch, 5 s @ 2048 Hz)")
    assert elapsed_ms < 10.0


def test_resolve_decimation_target_scales_with_plot_width_up_to_the_cap():
    v = ViewerState(n_pixels=2000)

    narrow = resolve_decimation_target(plot_width_px=100.0, v=v)
    wide = resolve_decimation_target(plot_width_px=1000.0, v=v)

    assert narrow < wide
    assert wide <= v.n_pixels
    assert narrow % 4 == 0
    assert wide % 4 == 0


def test_resolve_decimation_target_falls_back_to_n_pixels_when_width_unknown():
    v = ViewerState(n_pixels=800)

    target = resolve_decimation_target(plot_width_px=0.0, v=v)

    assert target == 800


def test_detail_factor_sets_draw_density_relative_to_plot_width():
    """With no cap (default `n_pixels=None`), the drawn point count is
    `plot_width_px * detail_factor` (rounded down to a multiple of 4), so the
    "Detail" slider scales density directly instead of hitting a fixed cap."""
    width = 600.0

    full = resolve_decimation_target(width, ViewerState(detail_factor=3.0))
    half = resolve_decimation_target(width, ViewerState(detail_factor=1.0))
    coarse = resolve_decimation_target(width, ViewerState(detail_factor=0.5))

    assert full == 1800  # 600 * 3.0
    assert half == 600  # 600 * 1.0
    assert coarse == 300  # 600 * 0.5
    assert full > half > coarse


def test_default_has_no_cap_so_wide_plots_are_not_clamped():
    """The old default (`n_pixels=2000`) clamped wide plots below the
    width-relative target — the dead zone. The new default (`None`) removes
    it: a wide plot draws the full `width * 3` with no ceiling."""
    v = ViewerState()  # detail_factor=3.0, n_pixels=None
    assert v.n_pixels is None

    wide = resolve_decimation_target(plot_width_px=1600.0, v=v)

    assert wide == 4800  # 1600 * 3.0, NOT clamped to 2000


def test_tiny_plot_width_is_floored_not_collapsed():
    """A narrow (or barely laid-out) plot still keeps at least the floor of
    points so decimation never collapses the trace to near nothing."""
    target = resolve_decimation_target(plot_width_px=5.0, v=ViewerState(detail_factor=0.5))

    assert target >= _DECIMATE_MIN_POINTS


def test_width_unknown_falls_back_to_default_when_no_explicit_cap():
    """First frame (width reported `<= 0`) with no explicit `n_pixels` cap
    uses the module fallback, then self-corrects once the plot has a size."""
    target = resolve_decimation_target(plot_width_px=0.0, v=ViewerState())

    assert target == _DECIMATE_FALLBACK_POINTS


def test_initial_channels_seeds_first_open_only():
    """`initial_channels` picks the opening selection, but only once — a
    later user edit (simulated by mutating `v.channels` directly, as the
    toggle grid does) must survive the next `resolve_enabled` call."""
    v = ViewerState()

    enabled = resolve_enabled(v, "emg", 64, initial_channels=range(16))

    assert enabled == set(range(16))
    assert v.channels == set(range(16))

    v.channels = {2, 3, 40}  # simulate a user edit via the toggle grid
    enabled_again = resolve_enabled(v, "emg", 64, initial_channels=range(16))

    assert enabled_again == {2, 3, 40}


def test_initial_channels_ignored_on_later_first_sight_of_another_stream():
    """`initial_channels` is a one-shot hint for the *very first* selection
    this `ViewerState` ever makes — a stream never seen before, reached via
    a later switch, falls back to `resolve_initial`'s `None` policy rather
    than reapplying the original caller's hint."""
    v = ViewerState()
    resolve_enabled(v, "emg", 64, initial_channels=range(16))

    other = resolve_enabled(v, "aux", 8, initial_channels=range(16))

    # aux has 8 channels (<=32) -> None-policy default is "all", not the
    # emg-shaped range(16) hint.
    assert other == set(range(8))


def test_selectable_viewer_preserves_each_streams_own_selection():
    """A `selectable=True` viewer switching between two streams must
    restore each stream's own selection, not share/reset one set."""
    v = ViewerState()

    a = resolve_enabled(v, "emg", 8)
    assert a == set(range(8))
    v.channels = {1, 2}  # user edits stream A's selection

    b = resolve_enabled(v, "aux", 4)
    assert b == set(range(4))
    v.channels = {3}  # user edits stream B's selection

    back_to_a = resolve_enabled(v, "emg", 8)
    assert back_to_a == {1, 2}

    back_to_b = resolve_enabled(v, "aux", 4)
    assert back_to_b == {3}


def test_channel_count_change_on_same_stream_is_a_fresh_key():
    """A reconnect that changes `n_channels` for the *same* stream name
    must not reuse a selection captured at the old channel count (which
    could contain now-out-of-range indices), and must not clobber a
    previously-seen selection at that other channel count either."""
    v = ViewerState()

    resolve_enabled(v, "emg", 64)
    v.channels = {0, 40, 63}

    reconnected = resolve_enabled(v, "emg", 8)

    assert reconnected == set(range(8))
    assert max(reconnected) < 8

    back = resolve_enabled(v, "emg", 64)
    assert back == {0, 40, 63}


class _HumSource:
    """Source protocol stub: a 50 Hz mains hum plus a 23 Hz signal on every channel."""

    def __init__(self, n_channels: int = 2, fs: float = 2000.0, chunk: int = 100) -> None:
        self._info = StreamInfo(n_channels=n_channels, fs=fs, dtype=np.dtype("float32"))
        self._chunk = chunk
        self._next = 0

    def connect(self) -> StreamInfo:
        return self._info

    def read(self):
        n = self._chunk
        i = np.arange(self._next, self._next + n)
        self._next += n
        t = i / self._info.fs
        sig = (4.0 * np.sin(2 * np.pi * 50 * t) + 2.0 * np.sin(2 * np.pi * 23 * t)).astype(np.float32)
        data = np.repeat(sig[:, None], self._info.n_channels, axis=1)
        return data, t.astype(np.float64)

    def disconnect(self) -> None:
        pass


def _rms(a: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(a))))


def test_build_signal_frame_notch_attenuates_hum_end_to_end():
    """End-to-end: with the mains notch on, `build_signal_frame`'s drawn trace has the 50 Hz
    hum scrubbed (and keeps the 23 Hz signal), across a scrolling stream — exercising the
    stable-snapshot + epoch/sequence + `NotchCache` wiring, not just the cache in isolation."""
    fs = 2000.0
    stream = Stream("emg", source=_HumSource(fs=fs, chunk=100), window_ms=100, buffer_ms=5000)
    stream.reconnect()  # attaching is deliberate now; the loop never does it
    for _ in range(60):  # ~3 s buffered (>= window + notch warm-up)
        stream._acquire_step()

    v_off = ViewerState(window=1.0, mains_notch=0)
    v_on = ViewerState(window=1.0, mains_notch=50)
    f_off = build_signal_frame(stream, v_off, {0, 1})
    f_on = build_signal_frame(stream, v_on, {0, 1})
    assert f_off is not None and f_on is not None
    assert np.all(np.isfinite(f_on.data))
    # Drop the far-left settling edge, then the 50 Hz hum should be gone (RMS collapses toward
    # the 23 Hz component alone: sqrt(2) vs sqrt(10) ~= 0.45).
    settled = slice(len(f_on.data) // 2, None)
    assert _rms(f_on.data[settled]) < 0.6 * _rms(f_off.data[settled])

    # Keep scrolling on the SAME cache (the hot path); output stays finite + attenuated.
    for _ in range(20):
        stream._acquire_step()
        f_on = build_signal_frame(stream, v_on, {0, 1})
    assert f_on is not None and np.all(np.isfinite(f_on.data))
    assert _rms(f_on.data[len(f_on.data) // 2 :]) < 0.6 * _rms(f_off.data[settled])


# --- channel_scope enforcement in resolve_enabled --------------------------------


def test_scope_bounds_the_seed_and_survives_the_fast_path():
    """Scope must hold on EVERY path.

    `resolve_enabled` returns early when the key is unchanged, so enforcing the
    scope only while seeding/restoring would let anything that mutated
    `v.channels` in between (a click, a stale set) escape it.
    """
    v = ViewerState()
    scope = list(range(256, 320))  # electrode grid IN5 of a 320-ch stream

    enabled = resolve_enabled(v, "emg", 320, scope=scope)
    assert enabled  # NOT empty: the policy runs inside the scope
    assert enabled <= set(scope)

    # Simulate something slipping a foreign channel in, then re-resolve on the
    # unchanged key — the fast path must still clamp it.
    v.channels.add(0)
    again = resolve_enabled(v, "emg", 320, scope=scope)
    assert 0 not in again
    assert again <= set(scope)


def test_scope_is_part_of_the_selection_cache_key():
    """State is keyed by widget_id, not by Python instance, so a differently
    scoped viewer reusing an id must not inherit the other's selection."""
    v = ViewerState()
    a = set(resolve_enabled(v, "emg", 320, scope=list(range(0, 64))))
    b = set(resolve_enabled(v, "emg", 320, scope=list(range(256, 320))))

    assert a <= set(range(0, 64))
    assert b <= set(range(256, 320))
    assert not (b & a)


def test_explicit_initial_channels_are_clamped_to_scope():
    v = ViewerState()
    enabled = resolve_enabled(
        v, "emg", 320, initial_channels=[0, 257, 300], scope=list(range(256, 320))
    )
    assert enabled == {257, 300}  # 0 is outside the scope


def test_unscoped_resolve_enabled_is_unchanged():
    """Regression guard: `scope=None` must behave exactly as before."""
    a = resolve_enabled(ViewerState(), "emg", 8)
    b = resolve_enabled(ViewerState(), "emg", 8, scope=None)
    assert a == b == set(range(8))
    assert resolve_enabled(ViewerState(), "emg", 320) == set(range(16))


def test_the_control_rows_leave_the_id_stack_balanced(implot_frame):
    """The two control rows are ImGui tables; an unclosed one corrupts the frame.

    `begin_table` pushes an ID that only `end_table` pops, and the failure
    surfaces far from the cause — as ``Missing PopID()`` at whatever
    ``end_child`` the viewer happens to sit inside. Render it in a child window
    so that assert fires here instead of in somebody's app.
    """
    from imgui_bundle import imgui

    from myogestic import Stream
    from myogestic.core import Context
    from myogestic.sources import SyntheticSource
    from myogestic.widgets import SignalViewer

    ctx = Context()
    stream = Stream("emg", source=SyntheticSource(n_channels=64, fs=500.0), window_ms=500)
    assert stream.reconnect()
    stream.status = "connected"
    ctx.streams["emg"] = stream
    viewer = SignalViewer("emg")

    def draw() -> None:
        imgui.begin_child("cell", imgui.ImVec2(900, 400))
        viewer.ui(ctx)
        imgui.end_child()

    implot_frame(draw)


def test_a_collapsed_viewer_gives_the_footer_row_back_to_the_plot(imgui_frame):
    """Hiding the chrome must hand its space to the plot, not leave a dead strip.

    The footer row — fps, sample rate, buffer fill — is the only thing an
    auto-sized plot reserves for. It used to be a hardcoded 25 px subtracted
    whether or not the footer was drawn, so collapsing made the read-out vanish
    without the plot growing into the gap.
    """
    from imgui_bundle import imgui

    from myogestic.widgets.signals._plot import resolve_plot_height

    def check() -> None:
        expanded = resolve_plot_height(-1, show_controls=True)
        collapsed = resolve_plot_height(-1, show_controls=False)
        reclaimed = collapsed - expanded
        assert reclaimed > 0, "collapsing gained the plot nothing"
        assert reclaimed == pytest.approx(imgui.get_text_line_height_with_spacing())

    imgui_frame(check)


def test_an_explicit_plot_height_is_honoured_either_way(imgui_frame):
    """`RawSignalViewer` passes a fixed height; the footer must not eat into it."""
    from myogestic.widgets.signals._plot import resolve_plot_height

    def check() -> None:
        assert resolve_plot_height(300.0, show_controls=True) == 300.0
        assert resolve_plot_height(300.0, show_controls=False) == 300.0

    imgui_frame(check)


def _empty_state_height(*, implot_frame, **viewer_kwargs) -> float:
    """Vertical space the detached-stream empty state consumes.

    ``viewer_kwargs`` go straight to `SignalViewer`, so any flag that claims to
    remove chrome can be measured rather than eyeballed.
    """
    from imgui_bundle import imgui

    from myogestic import Stream
    from myogestic.core import Context
    from myogestic.sources import SyntheticSource
    from myogestic.widgets import SignalViewer

    ctx = Context()
    # Never connected: `stream.info is None`, so the viewer renders its empty state.
    ctx.streams["emg"] = Stream("emg", source=SyntheticSource(n_channels=4), window_ms=200)
    viewer = SignalViewer("emg", **viewer_kwargs)
    measured: list[float] = []

    def draw() -> None:
        imgui.begin_child("cell", imgui.ImVec2(600, 400))
        before = imgui.get_cursor_pos_y()
        viewer.ui(ctx)
        measured.append(imgui.get_cursor_pos_y() - before)
        imgui.end_child()

    implot_frame(draw)
    return measured[0]


def test_show_connect_false_removes_the_button_rather_than_hiding_it(implot_frame):
    """It must take no space, not just be invisible.

    An app with a `DevicePicker` turns this off so there is exactly one control
    named Connect. The viewer's own attaches whatever source the stream already
    holds — which stops matching the picker's dropdown the moment it changes.
    """
    from imgui_bundle import imgui

    with_button = _empty_state_height(show_connect=True, implot_frame=implot_frame)
    without = _empty_state_height(show_connect=False, implot_frame=implot_frame)

    assert without < with_button, "turning the button off reclaimed nothing"
    freed = with_button - without
    assert freed >= imgui.get_frame_height() * 0.5, f"only {freed:.1f}px freed"


def test_show_title_false_reclaims_the_header_row_rather_than_blanking_it(implot_frame):
    """The header must cost nothing when off, not render an empty strip.

    This exists for a viewer inside a tab: the tab label already names the
    panel, so a `panel_header` under it is the title twice. If the row were
    merely blanked the tab would still pay for it — the padding it was meant to
    remove would just be invisible instead of gone.
    """
    from imgui_bundle import imgui

    with_title = _empty_state_height(implot_frame=implot_frame)
    without = _empty_state_height(show_title=False, implot_frame=implot_frame)

    assert without < with_title, "hiding the title reclaimed no vertical space"
    freed = with_title - without
    assert freed >= imgui.get_frame_height() * 0.5, f"only {freed:.1f}px freed"


def _header_frame(implot_frame, monkeypatch, names, *, widget_id, click="", frames=1):
    """Render ``frames`` frames of a selectable viewer over ``names``.

    Returns ``(viewer_state, button_labels_from_the_last_frame)``. The header's
    buttons are stubbed rather than clicked through the input queue — the ids are
    this widget's own, so the stub reports exactly which controls were drawn, and
    ``click`` presses the one whose id ends with it.

    Parameters
    ----------
    names
        Streams to register. None of them is connected: the viewer draws its
        empty state under the header, and the header is what is under test.
    widget_id
        Viewer state is module-global, keyed by this — give every test its own.
    """
    from imgui_bundle import imgui

    from myogestic import Stream
    from myogestic.core import Context
    from myogestic.sources import SyntheticSource
    from myogestic.widgets import SignalViewer
    from myogestic.widgets.signals._state import get_viewer_state

    ctx = Context()
    for name in names:
        ctx.streams[name] = Stream(name, source=SyntheticSource(n_channels=4), window_ms=200)
    viewer = SignalViewer(names[0], selectable=True, widget_id=widget_id)

    drawn: list[str] = []

    def small_button(label, *args, **kwargs):
        drawn.append(label)
        return bool(click) and label.endswith(click)

    monkeypatch.setattr(imgui, "small_button", small_button)
    for _ in range(frames):
        drawn.clear()
        implot_frame(lambda: viewer.ui(ctx))

    v = get_viewer_state(
        ctx,
        widget_id,
        n_pixels=None,
        scale_mode="auto",
        y_range=(-1.0, 1.0),
        show_markers=False,
        window_s=5.0,
        stream_name=names[0],
    )
    return v, drawn


def test_the_stream_arrows_appear_only_when_there_is_another_stream_to_reach(
    implot_frame, monkeypatch
):
    """One stream must draw no arrows — every shipped example has exactly one.

    A pair of arrows that cycles back to the stream you are already on is a
    control that does nothing, in every single-stream app in the repo. They earn
    their place only once `ctx.streams` holds somewhere to go.
    """
    _, alone = _header_frame(implot_frame, monkeypatch, ["emg"], widget_id="thdr_alone")
    _, pair = _header_frame(implot_frame, monkeypatch, ["emg", "target"], widget_id="thdr_pair")

    assert not [b for b in alone if "_stream" in b], f"dead arrows drawn: {alone}"
    assert len(alone) == 1, f"the chrome toggle is the whole header: {alone}"
    assert [b for b in pair if b.endswith("_prev_stream")], pair
    assert [b for b in pair if b.endswith("_next_stream")], pair
    assert len(pair) == 3, f"arrows must be added to the toggle, not replace it: {pair}"


def test_next_steps_to_the_following_stream_and_wraps_round(implot_frame, monkeypatch):
    """Two buttons have to reach every stream, so the last one leads back to the first.

    The freeze goes with the switch: a paused viewer that changed stream would
    keep showing the *old* stream's frozen samples under the new stream's title
    until somebody happened to press Resume.
    """
    import numpy as np

    names = ["emg", "target"]
    v, _ = _header_frame(
        implot_frame, monkeypatch, names, widget_id="thdr_next", click="_next_stream"
    )
    assert v.selected_stream == "target"

    v.paused = True
    v.frozen_data = np.zeros((4, 4))
    v.frozen_ts = np.zeros(4)
    v, _ = _header_frame(
        implot_frame, monkeypatch, names, widget_id="thdr_next", click="_next_stream"
    )
    assert v.selected_stream == "emg", "the last stream must wrap back to the first"
    assert not v.paused and v.frozen_data is None and v.frozen_ts is None


def test_prev_steps_backwards_from_the_first_stream_to_the_last(implot_frame, monkeypatch):
    """Backwards from the first entry is the last one, not a clamp at zero."""
    v, _ = _header_frame(
        implot_frame,
        monkeypatch,
        ["emg", "target", "aux"],
        widget_id="thdr_prev",
        click="_prev_stream",
    )
    assert v.selected_stream == "aux"


# --- the "1:1" toggle: Detail alone cannot reach every sample ----------------
def test_detail_at_full_still_decimates_a_fast_stream():
    """The reason the toggle exists. Detail tops out a few points per pixel, so a
    2 kHz stream over a 5 s window is reduced however far right the slider goes."""
    from myogestic.widgets.signals._state import ViewerState, resolve_decimation_target

    v = ViewerState()  # detail_factor defaults to full
    n_out = resolve_decimation_target(600.0, v)

    assert n_out < 2000 * 5.0, "full detail already draws every sample — toggle is moot"


def test_one_to_one_asks_for_more_points_than_any_window_holds():
    """It works by *out-running* the reduction rather than by a separate code path:
    `minmax_grid_all_shared_x` returns its input untouched once ``n <= n_out``."""
    import numpy as np

    from myogestic.widgets.signals._state import (
        ViewerState,
        minmax_grid_all_shared_x,
        resolve_decimation_target,
    )

    n = 10_000
    data = np.random.default_rng(0).standard_normal((n, 8)).astype(np.float32)
    t = np.arange(n) / 2000.0

    v = ViewerState()
    reduced = minmax_grid_all_shared_x(t, data, resolve_decimation_target(600.0, v), 5.0)[1]
    v.one_to_one = True
    every = minmax_grid_all_shared_x(t, data, resolve_decimation_target(600.0, v), 5.0)[1]

    assert reduced.shape[1] < n, "decimation did nothing to compare against"
    assert every.shape[1] == n, "1:1 did not return every sample"
    assert np.allclose(every, data.T), "1:1 altered the samples it drew"


def test_one_to_one_survives_a_plot_with_no_width_yet():
    """First frame reports width <= 0 and falls back to a fixed target; the toggle
    must win over that too, or 1:1 flickers off for a frame on every layout change."""
    from myogestic.widgets.signals._state import ViewerState, resolve_decimation_target

    v = ViewerState(one_to_one=True)

    assert resolve_decimation_target(0.0, v) == resolve_decimation_target(1200.0, v)


def test_a_capped_n_pixels_does_not_override_one_to_one():
    """`n_pixels` is a cap for the *density* path. Applied to the toggle it would
    silently re-enable decimation for any app that sets one."""
    from myogestic.widgets.signals._state import ViewerState, resolve_decimation_target

    v = ViewerState(one_to_one=True, n_pixels=800)

    assert resolve_decimation_target(1200.0, v) > 100_000


def test_one_to_one_drops_itself_when_the_window_grows_past_its_budget(implot_frame):
    """The window slider can be dragged after the toggle is on, and 1:1 has no ceiling
    of its own — so the budget has to be re-checked every frame, not only at the click.

    Dropped rather than left on and quietly clamped: a toggle claiming to show every
    sample while showing a reduction is worse than one that turns itself off in view.
    """
    from imgui_bundle import imgui

    from myogestic import Stream
    from myogestic.core import Context
    from myogestic.sources import SyntheticSource
    from myogestic.widgets.signals._controls import _ONE_TO_ONE_MAX_POINTS, render_controls
    from myogestic.widgets.signals._state import ViewerState

    ctx = Context()
    stream = Stream("emg", source=SyntheticSource(n_channels=8, fs=2000.0), window_ms=500)
    assert stream.reconnect()
    ctx.streams["emg"] = stream
    enabled = set(range(8))

    def draw(v: ViewerState) -> None:
        def inner() -> None:
            imgui.begin_child("cell", imgui.ImVec2(900, 400))
            render_controls(ctx, "emg", "emg", stream, v, False, enabled=enabled, scope=[])
            imgui.end_child()

        implot_frame(inner)

    affordable = ViewerState(one_to_one=True, window=0.8)  # 12.8k points
    draw(affordable)
    assert affordable.one_to_one is True, "a modest window was refused"

    ruinous = ViewerState(one_to_one=True, window=60.0)  # 960k points
    assert _ONE_TO_ONE_MAX_POINTS < 60.0 * 2000.0 * 8
    draw(ruinous)
    assert ruinous.one_to_one is False, "1:1 stayed on for a window it cannot afford"

    stream.disconnect()


@pytest.mark.parametrize("start_on", [False, True])
def test_clicking_one_to_one_leaves_the_style_stack_balanced(implot_frame, start_on):
    """A click flips the flag *between* `push_selected` and `pop_selected`.

    Guarding the pop on the flag itself therefore disagrees with the push on the one
    frame that matters: turning on pops a colour never pushed (``PopStyleColor() too
    many times``), turning off pushes three and leaks them into every widget after.

    A layout pass alone cannot catch this — `small_button` returns False with no mouse,
    so the toggle never flips and both branches agree. The click has to be simulated.
    """
    from imgui_bundle import imgui

    from myogestic import Stream
    from myogestic.core import Context
    from myogestic.sources import SyntheticSource
    from myogestic.widgets.signals import _controls
    from myogestic.widgets.signals._state import ViewerState

    ctx = Context()
    stream = Stream("emg", source=SyntheticSource(n_channels=8, fs=2000.0), window_ms=500)
    assert stream.reconnect()
    ctx.streams["emg"] = stream
    v = ViewerState(one_to_one=start_on, window=0.5)

    real = imgui.small_button
    imgui.small_button = lambda label, *a, **k: (
        True if label.startswith("1:1##") else real(label, *a, **k)
    )
    try:
        def inner() -> None:
            imgui.begin_child("cell", imgui.ImVec2(900, 400))
            _controls.render_controls(
                ctx, "emg", "emg", stream, v, False, enabled=set(range(8)), scope=[]
            )
            imgui.end_child()

        implot_frame(inner)  # an unbalanced push or pop raises here
    finally:
        imgui.small_button = real
        stream.disconnect()

    assert v.one_to_one is not start_on, "the simulated click did not toggle anything"
