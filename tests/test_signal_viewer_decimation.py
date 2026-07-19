"""Perf regression: the viewer must decimate only the *enabled* channels.

Before this fix, `build_signal_frame` M4-decimated the visible window over
every channel in the stream, then the channel controls resolved which
channels to display — so limiting the view never reduced decimation cost.
A 256-channel stream showing 3 channels should pay the decimation cost of
3 channels, not 256.

Uses an in-process synthetic `Source` (no LSL), matching the pattern in
`tests/test_recording_race.py` / `tests/test_stream_dtype.py`.
"""

from __future__ import annotations

import numpy as np

from myogestic.stream import Stream, StreamInfo
from myogestic.widgets.signals._state import ViewerState, build_signal_frame, resolve_enabled


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


def _make_stream(n_channels: int = 64, n_steps: int = 20) -> Stream:
    stream = Stream(
        "emg", source=_SynthSource(n_channels=n_channels), window_ms=100, buffer_ms=5000
    )
    stream._acquire_step()  # first step connects + allocates buffers
    for _ in range(n_steps):
        stream._acquire_step()
    return stream


def _viewer_state(n_pixels: int = 2) -> ViewerState:
    # n_pixels=2 -> n_out = 8, well below the ~1000 raw samples the fixture
    # accumulates, so every frame in this module exercises the M4 path.
    return ViewerState(n_pixels=n_pixels, window=1000.0)


def test_decimated_frame_has_exactly_the_enabled_columns():
    stream = _make_stream(n_channels=64)
    v = _viewer_state()
    enabled = {0, 5, 10}

    frame = build_signal_frame(stream, v, enabled)

    assert frame is not None
    assert frame.is_decimated
    assert frame.data.shape[1] == 3
    # Mapping from decimated column -> true channel index, so callers can
    # still color/label traces by their real channel without renumbering.
    assert frame.channel_map == sorted(enabled)
    # The *total* channel count on the frame must still reflect the full
    # stream (used to size specs/labels), not the enabled subset.
    assert frame.n_channels == 64


def test_empty_enabled_set_yields_no_decimation_work():
    stream = _make_stream(n_channels=64)
    v = _viewer_state()

    frame = build_signal_frame(stream, v, set())

    assert frame is not None
    assert frame.data.shape[1] == 0
    assert frame.channel_map == []


def test_decimating_fewer_channels_is_cheaper_than_all_channels():
    """Direct evidence of the perf win: restricting the M4 index union to a
    handful of channels should never produce *more* output points than
    running it over every channel."""
    stream = _make_stream(n_channels=64)

    v_subset = _viewer_state()
    frame_subset = build_signal_frame(stream, v_subset, {0, 5, 10})

    v_all = _viewer_state()
    frame_all = build_signal_frame(stream, v_all, set(range(64)))

    assert frame_subset is not None
    assert frame_all is not None
    assert frame_subset.n_points <= frame_all.n_points


def test_small_stream_all_enabled_matches_full_width_shape():
    """Common-case regression: when every channel is enabled, the decimated
    frame's width still equals the full channel count (no behavior change)."""
    stream = _make_stream(n_channels=4, n_steps=5)
    v = _viewer_state(n_pixels=2)
    enabled = {0, 1, 2, 3}

    frame = build_signal_frame(stream, v, enabled)

    assert frame is not None
    assert frame.data.shape[1] == 4
    assert frame.channel_map == [0, 1, 2, 3]


def test_below_decimation_threshold_still_slices_to_enabled_columns():
    """When the raw visible window is small enough to skip M4 entirely, the
    returned frame must still be column-sliced to `enabled` (not full width)."""
    stream = _make_stream(n_channels=8, n_steps=1)
    v = ViewerState(n_pixels=10_000, window=1000.0)  # huge n_out -> no decimation
    enabled = {1, 3}

    frame = build_signal_frame(stream, v, enabled)

    assert frame is not None
    assert not frame.is_decimated
    assert frame.data.shape[1] == 2
    assert frame.channel_map == [1, 3]


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
