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
    stream._acquire_step()  # first step connects + allocates buffers
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

    # A plausible plot pixel width; the default n_pixels=2000 cap binds
    # here (matches the reported 64 ch -> 128k-point example: 64 * 2000).
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
