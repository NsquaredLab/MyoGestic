"""Tests for the ChannelGrid topology and StreamInfo.channel_grids field."""

from myogestic.stream import ChannelGrid, StreamInfo
from myogestic.widgets.signals._channel_grid import auto_shape, normalize_layout


def test_channel_grid_columns_and_streaminfo_field():
    g = ChannelGrid("IN1", [[0, 1], [2, None]])
    assert g.columns == [0, 1, 2]  # row-major, skips None
    info = StreamInfo(n_channels=3, fs=2048.0, channel_grids=[g])
    assert info.channel_grids[0].label == "IN1"
    assert StreamInfo(n_channels=3, fs=2048.0).channel_grids is None  # default
    # a malformed layout must NOT raise at construction (viewer validates)
    StreamInfo(n_channels=2, fs=2048.0, channel_grids=[ChannelGrid("x", [[9, 9]])])


def test_auto_shape_covers_all_columns_near_square():
    cells = auto_shape(list(range(10)))
    flat = [c for row in cells for c in row if c is not None]
    assert flat == list(range(10))  # every column, in order
    assert all(len(row) == len(cells[0]) for row in cells)  # rectangular
    assert len(cells[0]) <= 4 and len(cells) <= 4  # near-square (ceil(sqrt(10))=4)


def test_normalize_none_makes_one_auto_grid():
    layout = normalize_layout(None, 8)
    assert len(layout) == 1 and sorted(layout[0].columns) == list(range(8))


def test_normalize_drops_out_of_range_and_dupes_then_falls_back_if_empty():
    good = normalize_layout([ChannelGrid("IN1", [[0, 1, 99], [1, 2]])], 4)
    assert sorted(good[0].columns) == [0, 1, 2]  # 99 dropped, dup 1 dropped
    empty = normalize_layout([ChannelGrid("bad", [[50]])], 4)
    assert sorted(empty[0].columns) == [0, 1, 2, 3]  # invalid -> auto "all"


def test_normalize_nulls_invalid_cells_in_place_for_rectangular_grid():
    # Rectangular (both rows length 3) -> nulled in place, NOT re-auto-shaped.
    layout = normalize_layout([ChannelGrid("R", [[0, 1, 99], [1, 2, None]])], 4)
    assert layout[0].cells == [[0, 1, None], [None, 2, None]]  # 99 out-of-range, dup 1 nulled
    assert layout[0].columns == [0, 1, 2]
