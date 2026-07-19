"""Perf regression: the signal viewer must never pay full-window decimation
cost for a stream at high channel counts.

Two fixes are covered here, at the two layers they now live in:

- `build_signal_frame` (`_state.py`) slices the visible window to the
  *enabled* columns only, before anything else touches it — a 256-channel
  stream showing 3 channels only ever carries 3 columns downstream, not
  256. It no longer decimates at all (see below).
- Decimation itself moved from `build_signal_frame` (a *shared* M4 pass
  over all enabled columns, whose per-channel index sets were then
  *unioned* onto one x-axis) into the per-channel plot loop
  (`_plot.plot_channel`, via `_state.m4_decimate_channel` /
  `resolve_decimation_target`). The old union made the reduction vanish at
  high channel counts: the union of many channels' distinct M4 picks
  approaches the full window (e.g. 64 channels over a 5 s / 2048 Hz window
  unioned to the *entire* window — zero point reduction). Decimating each
  channel independently, sized to the plot's own pixel width, bounds total
  draw points at `n_channels * N` instead, regardless of window length,
  sample rate, or channel count.

Uses an in-process synthetic `Source` (no LSL), matching the pattern in
`tests/test_recording_race.py` / `tests/test_stream_dtype.py`. The
decimation-*target-sizing* and per-channel M4 call are pure functions
(`resolve_decimation_target`, `m4_decimate_channel`) and are exercised
directly here — the actual plot loop that calls them
(`_plot.render_plot` / `plot_channel`) needs a live ImPlot context and
isn't covered by this headless suite.
"""

from __future__ import annotations

import numpy as np

from myogestic.stream import Stream, StreamInfo
from myogestic.widgets.signals._state import (
    ViewerState,
    build_signal_frame,
    m4_decimate_channel,
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
    # `n_pixels` no longer affects `build_signal_frame` at all (it stopped
    # decimating there) — it's only consulted later, by
    # `resolve_decimation_target`, when the plot loop sizes each channel's
    # M4 target. Kept as a parameter here for the tests below that exercise
    # that function directly.
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
    whether 3 columns or every column is enabled. The actual per-channel
    reduction now happens later; see
    `test_per_channel_decimation_bounds_total_draw_points_by_channel_count`."""
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


def test_per_channel_decimation_bounds_total_draw_points_by_channel_count():
    """The actual perf fix, reproducing the reported scenario: 64 channels
    over a 5 s / 2048 Hz window.

    Before this fix, the *union* of every enabled channel's M4 indices
    approached the full `(10240, 64)` window (~655k points) — no
    reduction at all. Decimating each channel independently instead bounds
    total draw points at `n_channels * N`, not `window * n_channels`.
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

    total_drawn = 0
    for ch in frame.channel_map:
        col = frame.data_win[:, ch]
        ts_ch, col_ch = m4_decimate_channel(frame.ts_win, col, n_out, v)
        assert len(ts_ch) == len(col_ch)
        # Bounded *per channel*, independent of how many other channels
        # are enabled.
        assert len(ts_ch) <= n_out
        total_drawn += len(ts_ch)

    # Bounded by channels * N (the fix)...
    assert total_drawn <= n_channels * n_out
    # ...and dramatically less than the old union's worst case, which
    # approached the entire (raw_len, n_channels) window.
    old_union_worst_case = raw_len * n_channels
    assert total_drawn < old_union_worst_case * 0.2


def test_m4_decimate_channel_below_threshold_returns_input_unchanged():
    t = np.arange(10, dtype=np.float64)
    col = np.arange(10, dtype=np.float32)
    v = ViewerState()

    t_out, col_out = m4_decimate_channel(t, col, n_out=100, v=v)

    np.testing.assert_array_equal(t_out, t)
    np.testing.assert_array_equal(col_out, col)


def test_m4_decimate_channel_paired_output_bounded_by_n_out():
    rng = np.random.default_rng(0)
    t = np.arange(5000, dtype=np.float64)
    col = rng.standard_normal(5000).astype(np.float32)
    v = ViewerState()

    t_out, col_out = m4_decimate_channel(t, col, n_out=200, v=v)

    assert len(t_out) == len(col_out)
    assert len(t_out) <= 200
    # Decimation must have actually reduced the point count.
    assert len(t_out) < len(col)


def test_resolve_decimation_target_scales_with_plot_width_up_to_the_cap():
    v = ViewerState(n_pixels=2000)

    narrow = resolve_decimation_target(plot_width_px=100.0, v=v)
    wide = resolve_decimation_target(plot_width_px=1000.0, v=v)

    assert narrow < wide
    assert wide <= v.n_pixels
    # tsdownsample's M4Downsampler requires a multiple of 4.
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
